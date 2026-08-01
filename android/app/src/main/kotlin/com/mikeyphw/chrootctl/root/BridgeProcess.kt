package com.mikeyphw.chrootctl.root

import java.io.File
import java.io.OutputStream
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit

internal data class BridgeProcessResult(
    val exitCode: Int,
    val output: String,
    val timedOut: Boolean = false,
)

internal class BridgeProcess(private val runtime: BridgeRuntime) {
    fun invoke(arguments: List<String>, requestJson: String? = null, timeoutSeconds: Long = 30): BridgeProcessResult {
        val process = start(arguments)
        process.outputStream.bufferedWriter(StandardCharsets.UTF_8).use { writer ->
            if (requestJson != null) writer.write(requestJson)
        }
        val finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS)
        if (!finished) {
            process.destroy()
            if (!process.waitFor(2, TimeUnit.SECONDS)) process.destroyForcibly()
            return BridgeProcessResult(-1, "Bridge process timed out", timedOut = true)
        }
        return BridgeProcessResult(process.exitValue(), process.inputStream.bufferedReader().use { reader -> reader.readText() })
    }

    fun stream(arguments: List<String>, requestJson: String, output: OutputStream): Int {
        val process = start(arguments)
        process.outputStream.bufferedWriter(StandardCharsets.UTF_8).use { writer -> writer.write(requestJson) }
        process.inputStream.use { input -> output.use { target -> input.copyTo(target, DEFAULT_BUFFER_SIZE) } }
        return process.waitFor()
    }

    private fun start(arguments: List<String>): Process {
        val command = runtime.argv + arguments
        return ProcessBuilder(command)
            .redirectErrorStream(true)
            .apply {
                val dataRoot = File(File.separator, "data")
                val adbRoot = File(dataRoot, "adb")
                val termuxRoot = File(File(dataRoot, "data"), "com.termux")
                val termuxFiles = File(termuxRoot, "files")
                val termuxUsrBin = File(termuxFiles, "usr/bin")
                val bridgeBin = File(adbRoot, "chrootctl/bin")
                environment()["HOME"] = File(termuxFiles, "home").path
                environment()["PATH"] = listOf(bridgeBin, termuxUsrBin, File(File.separator, "system/bin"), File(File.separator, "system/xbin")).joinToString(File.pathSeparator) { it.path }
                environment()["PYTHONUNBUFFERED"] = "1"
            }
            .start()
    }
}
