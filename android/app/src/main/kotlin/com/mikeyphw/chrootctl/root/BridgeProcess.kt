package com.mikeyphw.chrootctl.root

import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.nio.charset.StandardCharsets
import java.util.Collections
import java.util.concurrent.TimeUnit

internal data class BridgeProcessResult(
    val exitCode: Int,
    val output: String,
    val errorOutput: String = "",
    val timedOut: Boolean = false,
)

internal class BridgeProcess(private val runtime: BridgeRuntime) {
    fun invoke(arguments: List<String>, requestJson: String? = null, timeoutSeconds: Long = 30): BridgeProcessResult {
        val process = start(arguments)
        val stdout = ByteArrayOutputStream()
        val stderr = ByteArrayOutputStream()
        val drainFailures = drainFailureBuffer()
        val stdoutReader = drain(process.inputStream, stdout, "chrootctl-bridge-stdout", drainFailures)
        val stderrReader = drain(process.errorStream, stderr, "chrootctl-bridge-stderr", drainFailures)
        process.outputStream.bufferedWriter(StandardCharsets.UTF_8).use { writer ->
            if (requestJson != null) writer.write(requestJson)
        }
        val finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS)
        if (!finished) {
            process.destroy()
            if (!process.waitFor(2, TimeUnit.SECONDS)) process.destroyForcibly()
        }
        stdoutReader.join(READER_JOIN_TIMEOUT_MS)
        stderrReader.join(READER_JOIN_TIMEOUT_MS)
        return BridgeProcessResult(
            exitCode = if (finished) process.exitValue() else -1,
            output = String(stdout.toByteArray(), StandardCharsets.UTF_8),
            errorOutput = bridgeErrorOutput(stderr, drainFailures),
            timedOut = !finished,
        )
    }

    fun stream(arguments: List<String>, requestJson: String, output: OutputStream): Int {
        val process = start(arguments)
        val stderr = ByteArrayOutputStream()
        val drainFailures = drainFailureBuffer()
        val stderrReader = drain(process.errorStream, stderr, "chrootctl-bridge-stream-stderr", drainFailures)
        process.outputStream.bufferedWriter(StandardCharsets.UTF_8).use { writer -> writer.write(requestJson) }
        process.inputStream.use { input -> output.use { target -> input.copyTo(target, DEFAULT_BUFFER_SIZE) } }
        val exitCode = process.waitFor()
        stderrReader.join(READER_JOIN_TIMEOUT_MS)
        return exitCode
    }

    private fun start(arguments: List<String>): Process {
        val command = runtime.argv + arguments
        return ProcessBuilder(command)
            .apply {
                val dataRoot = File(File.separator, "data")
                val adbRoot = File(dataRoot, "adb")
                val termuxRoot = File(File(dataRoot, "data"), "com.termux")
                val termuxFiles = File(termuxRoot, "files")
                val termuxUsrBin = File(termuxFiles, "usr/bin")
                val termuxLocalBin = File(termuxFiles, "home/.local/bin")
                val bridgeBin = File(adbRoot, "chrootctl/bin")
                environment()["HOME"] = File(termuxFiles, "home").path
                environment()["PATH"] = listOf(
                    bridgeBin,
                    termuxLocalBin,
                    termuxUsrBin,
                    File(File.separator, "system/bin"),
                    File(File.separator, "system/xbin"),
                ).joinToString(File.pathSeparator) { it.path }
                environment()["PYTHONUNBUFFERED"] = "1"
            }
            .start()
    }

    private fun drainFailureBuffer(): MutableList<String> = Collections.synchronizedList(mutableListOf<String>())

    private fun bridgeErrorOutput(stderr: ByteArrayOutputStream, drainFailures: List<String>): String {
        val bridgeStderr = String(stderr.toByteArray(), StandardCharsets.UTF_8)
        if (drainFailures.isEmpty()) return bridgeStderr
        val drainDiagnostics = drainFailures.joinToString(separator = "\n") { failure ->
            "android-stream-drain: $failure"
        }
        return listOf(bridgeStderr, drainDiagnostics)
            .filter { it.isNotBlank() }
            .joinToString(separator = "\n")
    }

    private fun drain(
        input: java.io.InputStream,
        output: OutputStream,
        name: String,
        failures: MutableList<String>,
    ): Thread = Thread({
        try {
            input.use { source -> source.copyTo(output, DEFAULT_BUFFER_SIZE) }
        } catch (error: Throwable) {
            failures += drainFailureMessage(name, error)
        }
    }, name).apply {
        isDaemon = true
        uncaughtExceptionHandler = Thread.UncaughtExceptionHandler { thread, error ->
            failures += drainFailureMessage(thread.name, error)
        }
        start()
    }

    private fun drainFailureMessage(name: String, error: Throwable): String {
        val message = when (error) {
            is IOException -> error.message ?: error.javaClass.simpleName
            else -> error.message ?: error.javaClass.simpleName
        }
        return "$name closed without crashing the root service: $message"
    }

    private companion object {
        const val READER_JOIN_TIMEOUT_MS = 2_000L
    }
}
