package com.mikeyphw.chrootctl.root

import java.io.File
import org.json.JSONObject

internal data class BridgeRuntime(
    val argv: List<String>,
    val backend: String,
    val executable: String,
)

internal object RuntimeResolver {
    private val dataRoot = File(File.separator, "data")
    private val adbRoot = File(dataRoot, "adb")
    private val termuxRoot = File(File(dataRoot, "data"), "com.termux")
    private val termuxFiles = File(termuxRoot, "files")
    private val termuxUsr = File(termuxFiles, "usr")
    private val termuxHome = File(termuxFiles, "home")

    private val ksuRoot = File(adbRoot, "ksu")
    private val activeModuleDir = File(adbRoot, "modules/chrootctl-magisk")
    private val pendingModuleDirs = listOf(
        File(adbRoot, "modules_update/chrootctl-magisk"),
        File(ksuRoot, "modules_update/chrootctl-magisk"),
    )
    private val rootModuleExecutableCandidates = listOf(
        File(activeModuleDir, "system/bin/chrootctl"),
    )
    private val executableCandidates = rootModuleExecutableCandidates + listOf(
        File(File.separator, "system/bin/chrootctl"),
        File(adbRoot, "chrootctl/bin/chrootctl"),
        File(termuxHome, ".local/bin/chrootctl"),
        File(termuxUsr, "bin/chrootctl"),
    )
    private val pythonCandidates = listOf(
        File(adbRoot, "chrootctl/python/bin/python3"),
        File(termuxUsr, "bin/python3"),
        File(termuxUsr, "bin/python"),
    )

    @Volatile private var cachedRuntime: BridgeRuntime? = null
    @Volatile private var lastDiagnostic: String = "No compatible chrootctl Android bridge runtime has been resolved"

    fun resolve(): BridgeRuntime? {
        cachedRuntime?.let { cached ->
            if (isRuntimeCandidateUsable(cached)) return cached
            cachedRuntime = null
        }
        return synchronized(this) {
            cachedRuntime?.let { return@synchronized it }
            val override = System.getenv("CHROOTCTL_EXECUTABLE")?.takeIf(String::isNotBlank)
            var overrideFailure: String? = null
            if (override != null) {
                val candidate = File(override)
                val runtime = BridgeRuntime(listOf(override, "app"), "override", override)
                if (isExecutable(candidate) && isCompatible(runtime)) {
                    lastDiagnostic = "Using compatible bridge runtime at $override"
                    cachedRuntime = runtime
                    return@synchronized runtime
                }
                overrideFailure = "CHROOTCTL_EXECUTABLE was incompatible; normal active-runtime discovery continued"
            }

            val candidates = buildList {
                rootModuleExecutableCandidates.filter(::isActiveModuleExecutable).forEach { executable ->
                    add(BridgeRuntime(listOf(executable.path, "app"), "chrootctl-module", executable.path))
                }
                executableCandidates.filter { executable ->
                    executable !in rootModuleExecutableCandidates && isExecutable(executable)
                }.forEach { executable ->
                    add(BridgeRuntime(listOf(executable.path, "app"), "chrootctl", executable.path))
                }
                pythonCandidates.filter(::isExecutable).forEach { python ->
                    add(BridgeRuntime(listOf(python.path, "-m", "chrootctl.bridge.cli"), "python-module", python.path))
                }
            }
            val selected = selectCompatibleRuntime(candidates, ::isCompatible)
            if (selected == null) {
                val pending = pendingModuleDirs.filter(File::exists)
                val pendingNote = if (pending.isEmpty()) "" else " Pending module update(s) were detected but are intentionally not executable until activation after reboot."
                val base = if (candidates.isEmpty()) {
                    "No active chrootctl executable or Python runtime was found in /data/adb/modules, system, legacy adb-root, or Termux locations"
                } else {
                    "Found active chrootctl runtime candidates, but none exposed the protocol-1 Android bridge"
                }
                lastDiagnostic = listOfNotNull(overrideFailure, base + pendingNote).joinToString(". ")
            } else {
                lastDiagnostic = "Using compatible bridge runtime at ${selected.executable}"
            }
            cachedRuntime = selected
            selected
        }
    }

    fun diagnostic(): String = lastDiagnostic

    fun invalidate(runtime: BridgeRuntime) {
        synchronized(this) {
            if (cachedRuntime == runtime) cachedRuntime = null
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

    private fun isRuntimeCandidateUsable(runtime: BridgeRuntime): Boolean {
        val path = File(runtime.executable)
        return if (path.path.startsWith(activeModuleDir.path + File.separator)) {
            isActiveModuleExecutable(path)
        } else {
            isExecutable(path)
        }
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
        if (propFields["version"] != EXPECTED_MODULE_VERSION) return false
        if (propFields["versionCode"]?.toIntOrNull() != MIN_SUPPORTED_MODULE_VERSION_CODE) return false

        val compatibilityFile = File(activeModuleDir, "config/chrootctl/compatibility-manifest.json")
        if (!isCanonicalModuleFile(compatibilityFile)) return false
        val compatibility = runCatching { JSONObject(compatibilityFile.readText()) }.getOrNull() ?: return false
        val module = compatibility.optJSONObject("module") ?: return false
        val python = compatibility.optJSONObject("pythonPackage") ?: return false
        val android = compatibility.optJSONObject("androidApp") ?: return false
        return compatibility.optInt("schemaVersion", -1) == COMPATIBILITY_SCHEMA_VERSION &&
            compatibility.optString("project") == "chrootctl" &&
            compatibility.optInt("bridgeProtocolVersion", -1) == BRIDGE_PROTOCOL_VERSION &&
            module.optString("id") == MODULE_ID &&
            module.optString("version") == EXPECTED_MODULE_VERSION &&
            module.optInt("versionCode", -1) == MIN_SUPPORTED_MODULE_VERSION_CODE &&
            module.optInt("minimumSupportedBridgeProtocolVersion", -1) == BRIDGE_PROTOCOL_VERSION &&
            python.optString("name") == "chrootctl" &&
            python.optString("version") == EXPECTED_PYTHON_PACKAGE_VERSION &&
            android.optString("applicationId") == "com.mikeyphw.chrootctl" &&
            android.optString("versionName") == EXPECTED_ANDROID_VERSION_NAME &&
            android.optInt("versionCode", -1) == EXPECTED_ANDROID_VERSION_CODE &&
            android.optInt("minimumSupportedModuleVersionCode", -1) == MIN_SUPPORTED_MODULE_VERSION_CODE
    }

    private fun isCanonicalModuleFile(path: File): Boolean {
        if (!path.isFile || path.toPath().let(java.nio.file.Files::isSymbolicLink)) return false
        val canonical = runCatching { path.canonicalFile }.getOrNull() ?: return false
        val activeCanonical = runCatching { activeModuleDir.canonicalFile }.getOrNull() ?: return false
        return canonical == path.absoluteFile && canonical.path.startsWith(activeCanonical.path + File.separator)
    }

    private fun isExecutable(path: File): Boolean = path.isFile && path.canExecute()

    private const val PROBE_TIMEOUT_SECONDS = 2L
    private const val BRIDGE_PROTOCOL_VERSION = 1
    private const val COMPATIBILITY_SCHEMA_VERSION = 2
    private const val MODULE_ID = "chrootctl-magisk"
    private const val EXPECTED_MODULE_VERSION = "1.3.0"
    private const val MIN_SUPPORTED_MODULE_VERSION_CODE = 15
    private const val EXPECTED_PYTHON_PACKAGE_VERSION = "0.11.0"
    private const val EXPECTED_ANDROID_VERSION_NAME = "0.1.0-phase29"
    private const val EXPECTED_ANDROID_VERSION_CODE = 1
}

internal fun selectCompatibleRuntime(
    candidates: List<BridgeRuntime>,
    probe: (BridgeRuntime) -> Boolean,
): BridgeRuntime? = candidates.firstOrNull(probe)
