package com.mikeyphw.chrootctl.root

import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.nio.charset.StandardCharsets
import java.util.Collections
import java.util.concurrent.TimeUnit

internal data class BridgeProcessResult(
    val exitCode: Int,
    val output: String,
    val errorOutput: String = "",
    val timedOut: Boolean = false,
    val truncated: Boolean = false,
)

internal class BridgeProcess(private val runtime: BridgeRuntime) {
    fun invoke(arguments: List<String>, requestJson: String? = null, timeoutSeconds: Long = 30): BridgeProcessResult {
        val process = start(arguments)
        val stdout = BoundedOutputStream(MAX_CAPTURE_BYTES)
        val stderr = BoundedOutputStream(MAX_CAPTURE_BYTES)
        val drainFailures = drainFailureBuffer()
        val stdoutReader = drain(process.inputStream, stdout, "chrootctl-bridge-stdout", drainFailures)
        val stderrReader = drain(process.errorStream, stderr, "chrootctl-bridge-stderr", drainFailures)
        process.outputStream.bufferedWriter(StandardCharsets.UTF_8).use { writer ->
            if (requestJson != null) writer.write(requestJson)
        }
        val finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS)
        if (!finished) terminate(process)
        stdoutReader.join(READER_JOIN_TIMEOUT_MS)
        stderrReader.join(READER_JOIN_TIMEOUT_MS)
        return BridgeProcessResult(
            exitCode = if (finished) process.exitValue() else -1,
            output = stdout.asString(),
            errorOutput = bridgeErrorOutput(stderr, drainFailures),
            timedOut = !finished,
            truncated = stdout.truncated || stderr.truncated,
        )
    }

    fun stream(
        arguments: List<String>,
        requestJson: String,
        output: OutputStream,
        timeoutSeconds: Long = STREAM_TIMEOUT_SECONDS,
    ): Int {
        val process = start(arguments)
        val stderr = BoundedOutputStream(MAX_CAPTURE_BYTES)
        val drainFailures = drainFailureBuffer()
        val stderrReader = drain(process.errorStream, stderr, "chrootctl-bridge-stream-stderr", drainFailures)
        val stdoutReader = drainStreaming(process.inputStream, output, "chrootctl-bridge-stream-stdout", drainFailures)
        process.outputStream.bufferedWriter(StandardCharsets.UTF_8).use { writer -> writer.write(requestJson) }
        val finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS)
        if (!finished) {
            drainFailures += "chrootctl-bridge-stream timed out after ${timeoutSeconds}s"
            terminate(process)
        }
        stdoutReader.join(READER_JOIN_TIMEOUT_MS)
        stderrReader.join(READER_JOIN_TIMEOUT_MS)
        runCatching { output.flush() }
        return if (finished) process.exitValue() else -1
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
            }
            .start()
    }

    private fun terminate(process: Process) {
        process.destroy()
        if (!process.waitFor(TERMINATE_GRACE_SECONDS, TimeUnit.SECONDS)) {
            process.destroyForcibly()
            process.waitFor(TERMINATE_GRACE_SECONDS, TimeUnit.SECONDS)
        }
    }

    private fun drainFailureBuffer(): MutableList<String> = Collections.synchronizedList(mutableListOf<String>())

    private fun bridgeErrorOutput(stderr: BoundedOutputStream, drainFailures: List<String>): String {
        val bridgeStderr = stderr.asString()
        val truncation = if (stderr.truncated) "android-stream-drain: stderr capture truncated at $MAX_CAPTURE_BYTES bytes" else ""
        val drainDiagnostics = drainFailures.joinToString(separator = "\n") { failure ->
            "android-stream-drain: $failure"
        }
        return listOf(bridgeStderr, truncation, drainDiagnostics)
            .filter { it.isNotBlank() }
            .joinToString(separator = "\n")
    }

    private fun drain(
        input: InputStream,
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

    private fun drainStreaming(
        input: InputStream,
        output: OutputStream,
        name: String,
        failures: MutableList<String>,
    ): Thread = Thread({
        input.use { source ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            var target: OutputStream = output
            while (true) {
                val count = try {
                    source.read(buffer)
                } catch (error: Throwable) {
                    failures += drainFailureMessage(name, error)
                    break
                }
                if (count < 0) break
                try {
                    target.write(buffer, 0, count)
                    target.flush()
                } catch (error: Throwable) {
                    failures += drainFailureMessage(name, error)
                    target = DiscardingOutputStream
                }
            }
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

    private class BoundedOutputStream(private val limit: Int) : OutputStream() {
        private val buffer = ByteArrayOutputStream(minOf(limit, 64 * 1024))
        var truncated: Boolean = false
            private set

        override fun write(value: Int) {
            if (buffer.size() < limit) buffer.write(value) else truncated = true
        }

        override fun write(bytes: ByteArray, offset: Int, length: Int) {
            val remaining = (limit - buffer.size()).coerceAtLeast(0)
            val accepted = minOf(length, remaining)
            if (accepted > 0) buffer.write(bytes, offset, accepted)
            if (accepted < length) truncated = true
        }

        fun asString(): String = String(buffer.toByteArray(), StandardCharsets.UTF_8)
    }

    private object DiscardingOutputStream : OutputStream() {
        override fun write(value: Int) = Unit
        override fun write(bytes: ByteArray, offset: Int, length: Int) = Unit
    }

    private companion object {
        const val MAX_CAPTURE_BYTES = 512 * 1024
        const val READER_JOIN_TIMEOUT_MS = 2_000L
        const val TERMINATE_GRACE_SECONDS = 2L
        const val STREAM_TIMEOUT_SECONDS = 6 * 60 * 60L
    }
}
