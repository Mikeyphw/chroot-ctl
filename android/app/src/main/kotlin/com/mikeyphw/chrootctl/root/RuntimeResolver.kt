package com.mikeyphw.chrootctl.root

import android.system.Os
import java.io.File
import java.security.MessageDigest
import org.json.JSONObject

internal data class BridgeRuntime(
    val argv: List<String>,
    val backend: String,
    val executable: String,
)

internal object RuntimeResolver {
    private val dataRoot = File(File.separator, "data")
    private val adbRoot = File(dataRoot, "adb")
    private val ksuRoot = File(adbRoot, "ksu")
    private val activeModuleDir = File(adbRoot, "modules/chrootctl-magisk")
    private val pendingModuleDirs = listOf(
        File(adbRoot, "modules_update/chrootctl-magisk"),
        File(ksuRoot, "modules_update/chrootctl-magisk"),
    )
    private val rootModuleExecutableCandidates = listOf(
        File(activeModuleDir, "system/bin/chrootctl"),
    )
    private val externalExecutableCandidates = listOf(
        File(File.separator, "system/bin/chrootctl"),
        File(adbRoot, "chrootctl/bin/chrootctl"),
    )

    private data class CachedRuntime(val runtime: BridgeRuntime, val generation: String)

    @Volatile private var cachedRuntime: CachedRuntime? = null
    @Volatile private var lastDiagnostic: String = "No compatible chrootctl Android bridge runtime has been resolved"

    fun resolve(): BridgeRuntime? {
        cachedRuntime?.let { cached ->
            if (runtimeGeneration(cached.runtime) == cached.generation) return cached.runtime
            cachedRuntime = null
        }
        return synchronized(this) {
            cachedRuntime?.let { cached ->
                if (runtimeGeneration(cached.runtime) == cached.generation) return@synchronized cached.runtime
                cachedRuntime = null
            }
            val activeModuleClaimsAuthority = activeModuleDir.exists() &&
                !File(activeModuleDir, "disable").exists() &&
                !File(activeModuleDir, "remove").exists()
            val candidates = buildList {
                rootModuleExecutableCandidates.filter(::isActiveModuleExecutable).forEach { executable ->
                    add(BridgeRuntime(listOf(executable.path, "app"), "chrootctl-module", executable.path))
                }
                // Once an enabled module exists it owns runtime resolution. A
                // corrupt or stale module must fail closed instead of silently
                // executing an unrelated external development runtime. GO14
                // deliberately removed every Python-module fallback.
                if (!activeModuleClaimsAuthority) {
                    externalExecutableCandidates.filter(::isTrustedRootExecutable).forEach { executable ->
                        add(BridgeRuntime(listOf(executable.path, "app"), "chrootctl", executable.path))
                    }
                }
            }
            val selected = selectCompatibleRuntime(candidates, ::isCompatible)
            if (selected == null) {
                val pending = pendingModuleDirs.filter(File::exists)
                val pendingNote = if (pending.isEmpty()) "" else " Pending module update(s) were detected but are intentionally not executable until activation after reboot."
                val base = when {
                    activeModuleClaimsAuthority -> "An enabled chrootctl module is installed, but its sealed bundled-native runtime is unsafe, incompatible, or did not expose the protocol-1 Android bridge; external runtime fallback was refused"
                    candidates.isEmpty() -> "No active root-managed Go chrootctl executable was found in the module, /system, or /data/adb/chrootctl"
                    else -> "Found root-managed Go chrootctl executable candidates, but none exposed the protocol-1 Android bridge"
                }
                lastDiagnostic = base + pendingNote
            } else {
                lastDiagnostic = "Using compatible bridge runtime at ${selected.executable}"
            }
            cachedRuntime = selected?.let { runtime -> runtimeGeneration(runtime)?.let { generation -> CachedRuntime(runtime, generation) } }
            selected
        }
    }

    fun diagnostic(): String = lastDiagnostic

    fun invalidate(runtime: BridgeRuntime) {
        synchronized(this) {
            if (cachedRuntime?.runtime == runtime) cachedRuntime = null
        }
    }

    private fun isCompatible(runtime: BridgeRuntime): Boolean {
        val result = runCatching {
            BridgeProcess(runtime).invoke(listOf("capabilities"), timeoutSeconds = PROBE_TIMEOUT_SECONDS)
        }.getOrNull() ?: return false
        val accepted = validateBridgeProcessResult(runtime, result) as? BridgeOutputValidation.Accepted ?: return false
        val envelope = runCatching { JSONObject(accepted.json) }.getOrNull() ?: return false
        val data = envelope.optJSONObject("data") ?: return false
        return result.exitCode == 0 &&
            envelope.optBoolean("ok") &&
            data.optInt("protocolVersion", -1) == BRIDGE_PROTOCOL_VERSION
    }



    private fun isActiveModuleExecutable(path: File): Boolean {
        if (!isExecutable(path)) return false
        val activeCanonical = runCatching { activeModuleDir.canonicalFile }.getOrNull() ?: return false
        if (activeCanonical != activeModuleDir.absoluteFile || activeModuleDir.toPath().let(java.nio.file.Files::isSymbolicLink)) return false
        val executableCanonical = runCatching { path.canonicalFile }.getOrNull() ?: return false
        if (executableCanonical != path.absoluteFile || path.toPath().let(java.nio.file.Files::isSymbolicLink)) return false
        if (!executableCanonical.path.startsWith(activeCanonical.path + File.separator)) return false
        if (File(activeModuleDir, "disable").exists() || File(activeModuleDir, "remove").exists()) return false
        val prop = File(activeModuleDir, "module.prop")
        if (!isCanonicalModuleFile(prop)) return false
        val propFields = runCatching {
            prop.useLines { lines ->
                lines.mapNotNull { raw ->
                    val line = raw.trim()
                    if (line.isEmpty() || line.startsWith("#") || '=' !in line) null
                    else line.substringBefore('=') to line.substringAfter('=')
                }.toMap()
            }
        }.getOrNull() ?: return false
        if (propFields["id"] != MODULE_ID) return false
        if (propFields["versionCode"]?.toIntOrNull()?.let { it < MIN_SUPPORTED_MODULE_VERSION_CODE } != false) return false

        val compatibilityFile = File(activeModuleDir, "config/chrootctl/compatibility-manifest.json")
        if (!isCanonicalModuleFile(compatibilityFile)) return false
        val compatibility = runCatching { JSONObject(compatibilityFile.readText()) }.getOrNull() ?: return false
        val module = compatibility.optJSONObject("module") ?: return false
        val android = compatibility.optJSONObject("androidApp") ?: return false
        val moduleVersionCode = module.optInt("versionCode", -1)
        val minimumBridge = module.optInt("minimumSupportedBridgeProtocolVersion", -1)
        val minimumModule = android.optInt("minimumSupportedModuleVersionCode", -1)
        val commonCompatible = compatibility.optString("project") == "chrootctl" &&
            compatibility.optInt("bridgeProtocolVersion", -1) == BRIDGE_PROTOCOL_VERSION &&
            module.optString("id") == MODULE_ID &&
            moduleVersionCode >= MIN_SUPPORTED_MODULE_VERSION_CODE &&
            minimumBridge in 1..BRIDGE_PROTOCOL_VERSION &&
            android.optString("applicationId") == "com.mikeyphw.chrootctl" &&
            minimumModule in 1..moduleVersionCode
        val identityCompatible = compatibility.optInt("schemaVersion", -1) == COMPATIBILITY_SCHEMA_VERSION &&
            compatibility.optJSONObject("backend")?.let { backend ->
                compatibility.optJSONObject("nativeRuntime")?.let { runtime ->
                    backend.optString("implementation") == EXPECTED_BACKEND_IMPLEMENTATION &&
                        backend.optString("version") == EXPECTED_BACKEND_VERSION &&
                        runtime.optInt("schemaVersion", -1) == NATIVE_RUNTIME_SCHEMA_VERSION &&
                        runtime.optString("kind") == NATIVE_RUNTIME_KIND &&
                        runtime.optString("platform") == NATIVE_RUNTIME_PLATFORM &&
                        runtime.optString("abi") == NATIVE_RUNTIME_ABI &&
                        runtime.optString("entrypoint") == NATIVE_RUNTIME_ENTRYPOINT
                }
            } == true
        return commonCompatible && identityCompatible && isModulePackageSealReady() && isNativeRuntimeReady()
    }

    private fun isModulePackageSealReady(): Boolean {
        val packageManifestFile = File(activeModuleDir, MODULE_PACKAGE_MANIFEST_PATH)
        if (!isCanonicalModuleFile(packageManifestFile)) return false
        val packageManifest = runCatching { JSONObject(packageManifestFile.readText()) }.getOrNull() ?: return false
        val identityCompatible = packageManifest.optInt("schemaVersion", -1) == MODULE_PACKAGE_SCHEMA_VERSION &&
            packageManifest.optString("moduleId") == MODULE_ID &&
            packageManifest.optInt("moduleVersionCode", -1) >= MIN_SUPPORTED_MODULE_VERSION_CODE &&
            packageManifest.optString("backendVersion") == EXPECTED_BACKEND_VERSION &&
            packageManifest.optInt("bridgeProtocolVersion", -1) == BRIDGE_PROTOCOL_VERSION &&
            packageManifest.optInt("runtimeSchemaVersion", -1) == NATIVE_RUNTIME_SCHEMA_VERSION &&
            packageManifest.optString("runtimeKind") == NATIVE_RUNTIME_KIND &&
            packageManifest.optString("runtimeAbi") == NATIVE_RUNTIME_ABI &&
            packageManifest.optString("runtimeEntrypoint") == NATIVE_RUNTIME_ENTRYPOINT
        if (!identityCompatible) return false
        val files = packageManifest.optJSONArray("files") ?: return false
        if (files.length() == 0) return false
        val seen = linkedSetOf<String>()
        for (index in 0 until files.length()) {
            val metadata = files.optJSONObject(index) ?: return false
            val relative = metadata.optString("path")
            if (!isSafeModuleRelativePath(relative) || !seen.add(relative)) return false
            val file = File(activeModuleDir, relative)
            if (!isCanonicalModuleFile(file)) return false
            if (metadata.optLong("size", -1L) != file.length()) return false
            if (metadata.optString("sha256") != sha256(file)) return false
            if (metadata.optBoolean("executable", false) != file.canExecute()) return false
        }
        val actual = activeModuleDir.walkTopDown()
            .filter { it.isFile }
            .map { it.relativeTo(activeModuleDir).invariantSeparatorsPath }
            .filter { it != MODULE_PACKAGE_MANIFEST_PATH }
            .toSet()
        return actual == seen &&
            "system/bin/chrootctl" in seen &&
            "runtime/$NATIVE_RUNTIME_ABI/$NATIVE_RUNTIME_ENTRYPOINT" in seen &&
            "uninstall.sh" in seen
    }

    private fun isNativeRuntimeReady(): Boolean {
        val runtimeRoot = File(activeModuleDir, NATIVE_RUNTIME_ROOT)
        if (!isCanonicalModuleDir(runtimeRoot)) return false
        val manifestFile = File(runtimeRoot, "runtime-manifest.json")
        if (!isCanonicalModuleFile(manifestFile)) return false
        val manifest = runCatching { JSONObject(manifestFile.readText()) }.getOrNull() ?: return false
        val versionCompatible = manifest.optInt("schemaVersion", -1) == NATIVE_RUNTIME_SCHEMA_VERSION &&
            manifest.optString("runtimeKind") == NATIVE_RUNTIME_KIND &&
            manifest.optString("backendVersion") == EXPECTED_BACKEND_VERSION
        if (!versionCompatible ||
            manifest.optString("platform") != NATIVE_RUNTIME_PLATFORM ||
            manifest.optString("abi") != NATIVE_RUNTIME_ABI ||
            manifest.optString("entrypoint") != NATIVE_RUNTIME_ENTRYPOINT ||
            manifest.optInt("bridgeProtocolVersion", -1) != BRIDGE_PROTOCOL_VERSION
        ) return false

        val inventory = manifest.optJSONArray("files") ?: return false
        if (inventory.length() == 0) return false
        val seen = linkedSetOf<String>()
        for (index in 0 until inventory.length()) {
            val metadata = inventory.optJSONObject(index) ?: return false
            val relative = metadata.optString("path")
            if (!isSafeNativeRelativePath(relative) || !seen.add(relative)) return false
            val file = File(runtimeRoot, relative)
            if (!isCanonicalModuleFile(file)) return false
            if (metadata.optLong("size", -1L) != file.length()) return false
            if (metadata.optString("sha256") != sha256(file)) return false
            if (metadata.optBoolean("executable", false) != file.canExecute()) return false
        }
        val actual = runtimeRoot.walkTopDown()
            .filter { it.isFile }
            .map { it.relativeTo(runtimeRoot).invariantSeparatorsPath }
            .filter { it != "runtime-manifest.json" }
            .toSet()
        if (actual != seen) return false

        val entrypoint = File(runtimeRoot, NATIVE_RUNTIME_ENTRYPOINT)
        if (!isCanonicalModuleFile(entrypoint) || !entrypoint.canExecute() || NATIVE_RUNTIME_ENTRYPOINT !in seen) return false
        return validateAndroidArm64Elf(entrypoint)
    }

    private fun isSafeNativeRelativePath(path: String): Boolean {
        if (path.isBlank() || path.startsWith('/') || path.startsWith("\\")) return false
        val segments = path.replace('\\', '/').split('/')
        return segments.none { it.isBlank() || it == "." || it == ".." } && path != "runtime-manifest.json"
    }

    private fun isSafeModuleRelativePath(path: String): Boolean {
        if (path.isBlank() || path == MODULE_PACKAGE_MANIFEST_PATH || path.startsWith('/') || path.startsWith("\\")) return false
        val segments = path.replace('\\', '/').split('/')
        return segments.none { it.isBlank() || it == "." || it == ".." }
    }

    private fun sha256(path: File): String = runCatching {
        val digest = MessageDigest.getInstance("SHA-256")
        path.inputStream().buffered().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                if (read > 0) digest.update(buffer, 0, read)
            }
        }
        digest.digest().joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
    }.getOrDefault("")

    private fun isCanonicalModuleDir(path: File): Boolean {
        if (!path.isDirectory || path.toPath().let(java.nio.file.Files::isSymbolicLink)) return false
        val canonical = runCatching { path.canonicalFile }.getOrNull() ?: return false
        val activeCanonical = runCatching { activeModuleDir.canonicalFile }.getOrNull() ?: return false
        return canonical == path.absoluteFile && canonical.path.startsWith(activeCanonical.path + File.separator)
    }

    private fun isCanonicalModuleFile(path: File): Boolean {
        if (!path.isFile || path.toPath().let(java.nio.file.Files::isSymbolicLink)) return false
        val canonical = runCatching { path.canonicalFile }.getOrNull() ?: return false
        val activeCanonical = runCatching { activeModuleDir.canonicalFile }.getOrNull() ?: return false
        return canonical == path.absoluteFile && canonical.path.startsWith(activeCanonical.path + File.separator)
    }

    private fun isTrustedRootExecutable(path: File): Boolean {
        if (!isExecutable(path) || path.toPath().let(java.nio.file.Files::isSymbolicLink)) return false
        val canonical = runCatching { path.canonicalFile }.getOrNull() ?: return false
        if (canonical != path.absoluteFile) return false
        val stat = runCatching { Os.lstat(path.path) }.getOrNull() ?: return false
        return trustedRootExecutableMetadata(stat.st_uid.toInt(), stat.st_mode)
    }

    private fun isExecutable(path: File): Boolean = path.isFile && path.canExecute()

    private fun runtimeGeneration(runtime: BridgeRuntime): String? {
        val executable = File(runtime.executable)
        val active = executable.path.startsWith(activeModuleDir.path + File.separator)
        if (!active && !isTrustedRootExecutable(executable)) return null
        if (active) {
            if (File(activeModuleDir, "disable").exists() || File(activeModuleDir, "remove").exists()) return null
            if (!activeModuleDir.exists()) return null
        }
        val files = if (active) {
            val runtimeRoot = File(activeModuleDir, NATIVE_RUNTIME_ROOT)
            buildList {
                add(activeModuleDir)
                add(File(activeModuleDir, "module.prop"))
                add(File(activeModuleDir, "config/chrootctl/compatibility-manifest.json"))
                add(File(activeModuleDir, MODULE_PACKAGE_MANIFEST_PATH))
                add(runtimeRoot)
                if (runtimeRoot.exists()) addAll(runtimeRoot.walkTopDown().drop(1).toList())
            }.distinctBy { it.absolutePath }.sortedBy { it.absolutePath }
        } else {
            listOf(executable)
        }
        return files.joinToString("|") { fileIdentity(it) }
    }

    private fun fileIdentity(file: File): String {
        val absolute = file.absoluteFile
        val canonical = runCatching { file.canonicalFile }.getOrNull() ?: return "invalid:${absolute.path}"
        if (canonical != absolute || java.nio.file.Files.isSymbolicLink(absolute.toPath())) return "unsafe:${absolute.path}"
        val stat = runCatching { Os.lstat(absolute.path) }.getOrNull() ?: return "missing:${absolute.path}"
        return listOf(
            absolute.path, stat.st_dev, stat.st_ino, stat.st_mode, stat.st_uid, stat.st_gid, stat.st_size, stat.st_mtime,
        ).joinToString(":")
    }

    private const val PROBE_TIMEOUT_SECONDS = 10L
    private const val BRIDGE_PROTOCOL_VERSION = 1
    private const val COMPATIBILITY_SCHEMA_VERSION = 3
    private const val NATIVE_RUNTIME_SCHEMA_VERSION = 2
    private const val NATIVE_RUNTIME_KIND = "go-native"
    private const val NATIVE_RUNTIME_PLATFORM = "android"
    private const val NATIVE_RUNTIME_ABI = "arm64-v8a"
    private const val NATIVE_RUNTIME_ROOT = "runtime/arm64-v8a"
    private const val NATIVE_RUNTIME_ENTRYPOINT = "chrootctl"
    private const val MODULE_PACKAGE_SCHEMA_VERSION = 1
    private const val MODULE_PACKAGE_MANIFEST_PATH = "config/chrootctl/module-package-manifest.json"
    private const val MODULE_ID = "chrootctl-magisk"
    private const val MIN_SUPPORTED_MODULE_VERSION_CODE = 15
    private const val EXPECTED_BACKEND_IMPLEMENTATION = "go"
    private const val EXPECTED_BACKEND_VERSION = "0.11.0"
}


internal fun validateAndroidArm64Elf(file: File): Boolean = runCatching {
    val bytes = file.inputStream().buffered().use { input ->
        val header = ByteArray(64)
        if (input.read(header) != header.size) return@runCatching false
        header
    }
    if (!isAndroidArm64ElfHeader(bytes)) return@runCatching false
    val raf = java.io.RandomAccessFile(file, "r")
    raf.use {
        val phoff = littleEndianLong(bytes, 32)
        val phentsize = littleEndianU16(bytes, 54)
        val phnum = littleEndianU16(bytes, 56)
        if (phoff < 0 || phentsize < 56 || phnum < 0 || phnum > 4096) return@runCatching false
        var interpreter: String? = null
        repeat(phnum) { index ->
            val off = phoff + index.toLong() * phentsize
            if (off < 0 || off + phentsize > raf.length()) return@runCatching false
            raf.seek(off)
            val ph = ByteArray(phentsize)
            raf.readFully(ph)
            if (littleEndianInt(ph, 0) == 3) { // PT_INTERP
                val fileOffset = littleEndianLong(ph, 8)
                val fileSize = littleEndianLong(ph, 32)
                if (fileOffset < 0 || fileSize <= 0 || fileSize > 4096 || fileOffset + fileSize > raf.length()) return@runCatching false
                val raw = ByteArray(fileSize.toInt())
                raf.seek(fileOffset)
                raf.readFully(raw)
                interpreter = raw.toString(Charsets.UTF_8).trimEnd('\u0000')
            }
        }
        interpreter == null || interpreter == "/system/bin/linker64" || interpreter?.endsWith("/linker64") == true && interpreter?.startsWith("/apex/") == true
    }
}.getOrDefault(false)

internal fun isAndroidArm64ElfHeader(header: ByteArray): Boolean =
    header.size >= 64 &&
        header[0] == 0x7f.toByte() && header[1] == 'E'.code.toByte() && header[2] == 'L'.code.toByte() && header[3] == 'F'.code.toByte() &&
        header[4].toInt() == 2 && header[5].toInt() == 1 && littleEndianU16(header, 18) == EM_AARCH64

private const val EM_AARCH64 = 183

private fun littleEndianU16(bytes: ByteArray, offset: Int): Int =
    (bytes[offset].toInt() and 0xff) or ((bytes[offset + 1].toInt() and 0xff) shl 8)

private fun littleEndianInt(bytes: ByteArray, offset: Int): Int =
    (0 until 4).fold(0) { acc, index -> acc or ((bytes[offset + index].toInt() and 0xff) shl (index * 8)) }

private fun littleEndianLong(bytes: ByteArray, offset: Int): Long =
    (0 until 8).fold(0L) { acc, index -> acc or ((bytes[offset + index].toLong() and 0xffL) shl (index * 8)) }

internal fun trustedRootExecutableMetadata(uid: Int, mode: Int): Boolean =
    uid == 0 && (mode and 0x12) == 0

internal fun selectCompatibleRuntime(
    candidates: List<BridgeRuntime>,
    probe: (BridgeRuntime) -> Boolean,
): BridgeRuntime? = candidates.firstOrNull(probe)
