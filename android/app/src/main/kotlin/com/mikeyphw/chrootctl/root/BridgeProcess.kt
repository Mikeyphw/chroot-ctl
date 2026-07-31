package com.mikeyphw.chrootctl.root

import java.io.OutputStream
import java.io.OutputStreamWriter
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
                environment()["HOME"] = "/data/data/com.termux/files/home"
                environment()["PATH"] = "/data/adb/chrootctl/bin:/data/data/com.termux/files/usr/bin:/system/bin:/system/xbin"
                environment()["PYTHONUNBUFFERED"] = "1"
            }
            .start()
    }
}
