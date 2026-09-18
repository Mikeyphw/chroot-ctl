package com.mikeyphw.chrootctl.root

import android.os.Build
import android.system.Os
import java.io.File
import java.security.MessageDigest
import org.json.JSONObject

internal data class BridgeRuntime(
    val argv: List<String>,
    val backend: String,
    val executable: String,
)

internal data class BinaryCandidateProbe(
    val path: String,
    val source: String,
    val exists: Boolean,
    val executable: Boolean,
    val trusted: Boolean,
    val compatible: Boolean,
    val exitCode: Int?,
    val detail: String,
)

internal data class BinaryResolutionReport(
    val code: String,
    val selectedPath: String?,
    val selectedSource: String?,
    val moduleInstalled: Boolean,
    val moduleDisabled: Boolean,
    val moduleSealReady: Boolean,
    val pendingUpdate: Boolean,
    val path: String,
    val rootProvider: String,
    val abi: String,
    val candidates: List<BinaryCandidateProbe>,
) {
    fun summary(): String {
        if (code == "OK") return "Using compatible chrootctl bridge at $selectedPath ($selectedSource)"
        val checked = candidates.joinToString("; ") { probe -> "${probe.path}: ${probe.detail}" }
        val action = when (code) {
            "MODULE_NOT_INSTALLED" -> "Install the chrootctl root module and reboot."
            "MODULE_DISABLED" -> "Enable the chrootctl root module and reboot."
            "MODULE_SEAL_INVALID" -> "Reinstall/update the chrootctl module; its package/runtime seal is invalid."
            "BINARY_NOT_EXECUTABLE" -> "Reinstall/update the module so its launcher has executable permissions."
            "BINARY_VERSION_INCOMPATIBLE" -> "Update the chrootctl module and Android app to compatible versions."
            "BINARY_EXEC_FAILED" -> "The launcher was found but could not run; inspect its exit details and reinstall the module if needed."
            "VERSION_PROBE_FAILED" -> "The launcher did not complete its compatibility probe; inspect the candidate details."
            "UNSUPPORTED_ABI" -> "This module runtime requires arm64-v8a; install a build matching this device ABI."
            "BINARY_UNTRUSTED" -> "Reinstall the module so the launcher is root-owned and not writable by group/others."
            else -> "Reinstall/update the chrootctl module and reboot so a public launcher is exposed."
        }
        return "$code. $action Checked: $checked" + if (pendingUpdate) " A pending module update exists and requires reboot." else ""
    }

    fun toJson(): JSONObject = JSONObject()
        .put("code", code)
        .put("selectedPath", selectedPath ?: JSONObject.NULL)
        .put("selectedSource", selectedSource ?: JSONObject.NULL)
        .put("moduleInstalled", moduleInstalled)
        .put("moduleDisabled", moduleDisabled)
        .put("moduleSealReady", moduleSealReady)
        .put("pendingUpdate", pendingUpdate)
        .put("path", path)
        .put("rootProvider", rootProvider)
        .put("abi", abi)
        .put("candidates", org.json.JSONArray(candidates.map { probe -> JSONObject()
            .put("path", probe.path).put("source", probe.source).put("exists", probe.exists)
            .put("executable", probe.executable).put("trusted", probe.trusted).put("compatible", probe.compatible)
            .put("exitCode", probe.exitCode ?: JSONObject.NULL).put("detail", probe.detail) }))

    companion object {
        fun initial() = BinaryResolutionReport("NOT_PROBED", null, null, false, false, false, false, rootBridgeEnvironment().getValue("PATH"), "not-probed", "unknown", emptyList())
    }
}

private data class BinaryCandidate(val path: File, val source: String, val moduleInternal: Boolean)
private data class CompatibilityProbe(val compatible: Boolean, val exitCode: Int?, val detail: String)

private fun currentDeviceAbi(): String = Build.SUPPORTED_ABIS.firstOrNull() ?: "unknown"

internal object RuntimeResolver {
    private val dataRoot = File(File.separator, "data")
    private val adbRoot = File(dataRoot, "adb")
    private val ksuRoot = File(adbRoot, "ksu")
    private val activeModuleDir = File(adbRoot, "modules/chrootctl-magisk")
    private val pendingModuleDirs = listOf(
        File(adbRoot, "modules_update/chrootctl-magisk"),
        File(ksuRoot, "modules_update/chrootctl-magisk"),
    )
    // Public launchers come first. The app executes the resolved absolute path;
    // PATH is discovery context only, never an execution contract.
    private val publicExecutableCandidates = listOf(
        File(adbRoot, "chrootctl/bin/chrootctl"),
        File(File.separator, "system/bin/chrootctl"),
        File(File.separator, "system/xbin/chrootctl"),
    )
    private val rootModuleExecutableCandidates = listOf(
        File(activeModuleDir, "system/bin/chrootctl"),
    )

    private data class CachedRuntime(val runtime: BridgeRuntime, val generation: String)

    @Volatile private var cachedRuntime: CachedRuntime? = null
    @Volatile private var lastReport: BinaryResolutionReport = BinaryResolutionReport.initial()

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
            val moduleInstalled = activeModuleDir.exists()
            val moduleDisabled = File(activeModuleDir, "disable").exists() || File(activeModuleDir, "remove").exists()
            val activeModuleClaimsAuthority = moduleInstalled && !moduleDisabled
            val moduleSealReady = activeModuleClaimsAuthority && isModulePackageSealReady() && isNativeRuntimeReady()
            val pending = pendingModuleDirs.filter(File::exists)

            val ordered = mutableListOf<BinaryCandidate>().apply {
                // A healthy active module authorizes its public launchers. This lets
                // /data/adb/chrootctl/bin survive magic-mount differences while still
                // failing closed if the installed module package/runtime seal is bad.
                if (!activeModuleClaimsAuthority || moduleSealReady) {
                    publicExecutableCandidates.forEach { path ->
                        add(BinaryCandidate(path, "public-launcher", false))
                    }
                }
                rootModuleExecutableCandidates.forEach { path ->
                    add(BinaryCandidate(path, "module-launcher", true))
                }
            }

            val probes = mutableListOf<BinaryCandidateProbe>()
            val shellLookup = discoverFromRootPath()
            if (shellLookup != null && ordered.none { it.path.path == shellLookup }) {
                ordered.add(BinaryCandidate(File(shellLookup), "root-path", false))
            }
            var selected: BridgeRuntime? = null
            for (candidate in ordered) {
                val path = candidate.path
                val exists = path.isFile
                val executable = exists && path.canExecute()
                val trusted = when {
                    !exists -> false
                    candidate.moduleInternal -> isActiveModuleExecutable(path)
                    activeModuleClaimsAuthority && !moduleSealReady -> false
                    else -> isTrustedRootExecutable(path)
                }
                if (!exists || !executable || !trusted) {
                    probes += BinaryCandidateProbe(path.path, candidate.source, exists, executable, trusted, false, null,
                        when {
                            !exists -> "not found"
                            !executable -> "not executable"
                            !trusted -> "failed root ownership/path trust checks"
                            else -> "rejected"
                        })
                    continue
                }
                val runtime = BridgeRuntime(listOf(path.path, "app"), candidate.source, path.path)
                val probe = probeCompatibility(runtime)
                probes += BinaryCandidateProbe(path.path, candidate.source, true, true, true, probe.compatible, probe.exitCode, probe.detail)
                if (probe.compatible) {
                    selected = runtime
                    break
                }
            }

            val code = when {
                selected != null -> "OK"
                !moduleInstalled && probes.none { it.exists } -> "MODULE_NOT_INSTALLED"
                moduleDisabled -> "MODULE_DISABLED"
                activeModuleClaimsAuthority && !moduleSealReady -> "MODULE_SEAL_INVALID"
                Build.SUPPORTED_ABIS.none { it == "arm64-v8a" } -> "UNSUPPORTED_ABI"
                probes.any { it.exists && !it.executable } -> "BINARY_NOT_EXECUTABLE"
                probes.any { it.trusted && !it.compatible && it.detail.startsWith("execution failed") } -> "BINARY_EXEC_FAILED"
                probes.any { it.trusted && !it.compatible && it.detail.contains("timed out") } -> "VERSION_PROBE_FAILED"
                probes.any { it.trusted && !it.compatible } -> "BINARY_VERSION_INCOMPATIBLE"
                probes.any { it.exists && !it.trusted } -> "BINARY_UNTRUSTED"
                else -> "PUBLIC_LAUNCHER_MISSING"
            }
            lastReport = BinaryResolutionReport(
                code = code,
                selectedPath = selected?.executable,
                selectedSource = selected?.backend,
                moduleInstalled = moduleInstalled,
                moduleDisabled = moduleDisabled,
                moduleSealReady = moduleSealReady,
                pendingUpdate = pending.isNotEmpty(),
                path = rootBridgeEnvironment().getValue("PATH"),
                rootProvider = detectRootProvider(),
                abi = currentDeviceAbi(),
                candidates = probes,
            )
            cachedRuntime = selected?.let { runtime -> runtimeGeneration(runtime)?.let { generation -> CachedRuntime(runtime, generation) } }
            selected
        }
    }

    fun diagnostic(): String = lastReport.summary()

    fun diagnosticJson(): JSONObject = lastReport.toJson()

    fun invalidate(runtime: BridgeRuntime) {
        synchronized(this) {
            if (cachedRuntime?.runtime == runtime) cachedRuntime = null
        }
    }

    private fun discoverFromRootPath(): String? = runCatching {
        val process = ProcessBuilder(
            "/system/bin/sh", "-c",
            "PATH=/data/adb/chrootctl/bin:/system/bin:/system/xbin:/vendor/bin:/product/bin; command -v chrootctl",
        ).redirectErrorStream(true).start()
        if (!process.waitFor(PROBE_TIMEOUT_SECONDS, java.util.concurrent.TimeUnit.SECONDS)) {
            process.destroyForcibly()
            return@runCatching null
        }
        if (process.exitValue() != 0) return@runCatching null
        process.inputStream.bufferedReader().use { it.readLine() }
            ?.trim()?.takeIf { it.startsWith("/") && !it.contains('\n') }
    }.getOrNull()

    private fun detectRootProvider(): String = when {
        File(adbRoot, "ksu").exists() -> "KernelSU"
        File(adbRoot, "ap").exists() -> "APatch"
        File(adbRoot, "magisk").exists() || File(adbRoot, "magisk.db").exists() -> "Magisk"
        else -> "unknown"
    }

    private fun probeCompatibility(runtime: BridgeRuntime): CompatibilityProbe {
        val result = runCatching {
            BridgeProcess(runtime).invoke(listOf("capabilities"), timeoutSeconds = PROBE_TIMEOUT_SECONDS)
        }.getOrElse { error ->
            return CompatibilityProbe(false, null, "execution failed: ${error.message ?: error.javaClass.simpleName}")
        }
        if (result.timedOut) return CompatibilityProbe(false, result.exitCode, "capabilities probe timed out")
        val validation = validateBridgeProcessResult(runtime, result)
        val accepted = validation as? BridgeOutputValidation.Accepted
            ?: return CompatibilityProbe(false, result.exitCode, (validation as BridgeOutputValidation.Rejected).message)
        val envelope = runCatching { JSONObject(accepted.json) }.getOrNull()
            ?: return CompatibilityProbe(false, result.exitCode, "capabilities returned invalid JSON")
        val data = envelope.optJSONObject("data")
            ?: return CompatibilityProbe(false, result.exitCode, "capabilities response had no data object")
        val protocol = data.optInt("protocolVersion", -1)
        val compatible = result.exitCode == 0 && envelope.optBoolean("ok") && protocol == BRIDGE_PROTOCOL_VERSION
        return CompatibilityProbe(compatible, result.exitCode, if (compatible) "protocol-$protocol bridge ready" else "protocol $protocol is incompatible; expected $BRIDGE_PROTOCOL_VERSION")
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
            .filter { it != MODULE_PACKAGE_MANIFEST_PATH && !isModuleManagerMetadata(it) }
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

    // Root module managers own these top-level state markers. They are not
    // package payload and may be created after the package seal is generated.
    // Keep the allow-list deliberately narrow: nested files and arbitrary
    // manager additions must still fail the exact sealed-inventory check.
    internal fun isModuleManagerMetadata(path: String): Boolean = path in MODULE_MANAGER_METADATA

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
        val moduleClaimsAuthority = activeModuleDir.exists()
        val files = if (active || moduleClaimsAuthority) {
            val runtimeRoot = File(activeModuleDir, NATIVE_RUNTIME_ROOT)
            buildList {
                add(executable)
                add(activeModuleDir)
                add(File(activeModuleDir, "disable"))
                add(File(activeModuleDir, "remove"))
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
    private val MODULE_MANAGER_METADATA = setOf("update", "disable", "remove", "skip_mount")
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
