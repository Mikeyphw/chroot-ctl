package com.mikeyphw.chrootctl.root

import android.system.Os
import android.system.OsConstants
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

internal data class BridgeStreamResult(
    val exitCode: Int,
    val timedOut: Boolean,
    val errorOutput: String,
    val truncated: Boolean,
)

internal fun rootBridgeEnvironment(): Map<String, String> = linkedMapOf(
    "HOME" to "/data/adb/chrootctl",
    "PATH" to "/data/adb/chrootctl/bin:/system/bin:/system/xbin:/vendor/bin:/product/bin",
    "TMPDIR" to "/data/local/tmp",
    "LANG" to "C.UTF-8",
    "LC_ALL" to "C.UTF-8",
)

internal class BridgeProcess(private val runtime: BridgeRuntime) {
    fun invoke(arguments: List<String>, requestJson: String? = null, timeoutSeconds: Long = 30): BridgeProcessResult {
        val process = start(arguments)
        val stdout = BoundedOutputStream(MAX_CAPTURE_BYTES)
        val stderr = BoundedOutputStream(MAX_CAPTURE_BYTES)
        val drainFailures = drainFailureBuffer()
        val stdoutReader = drain(process.inputStream, stdout, "chrootctl-bridge-stdout", drainFailures)
        val stderrReader = drain(process.errorStream, stderr, "chrootctl-bridge-stderr", drainFailures)
        var finished = false
        var timedOut = false
        try {
            process.outputStream.bufferedWriter(StandardCharsets.UTF_8).use { writer ->
                if (requestJson != null) writer.write(requestJson)
            }
            finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS)
            timedOut = !finished
            if (timedOut) terminateTree(process, drainFailures)
        } catch (interrupted: InterruptedException) {
            drainFailures += "chrootctl-bridge wait interrupted"
            terminateTree(process, drainFailures)
            Thread.currentThread().interrupt()
            throw interrupted
        } finally {
            if (!finished && process.isAlive) terminateTree(process, drainFailures)
            stdoutReader.join(READER_JOIN_TIMEOUT_MS)
            stderrReader.join(READER_JOIN_TIMEOUT_MS)
        }
        return BridgeProcessResult(
            exitCode = if (finished) process.exitValue() else -1,
            output = stdout.asString(),
            errorOutput = bridgeErrorOutput(stderr, drainFailures),
            timedOut = timedOut,
            truncated = stdout.truncated || stderr.truncated,
        )
    }

    fun stream(
        arguments: List<String>,
        requestJson: String,
        output: OutputStream,
        timeoutSeconds: Long = STREAM_TIMEOUT_SECONDS,
    ): BridgeStreamResult {
        val process = start(arguments)
        val stderr = BoundedOutputStream(MAX_CAPTURE_BYTES)
        val drainFailures = drainFailureBuffer()
        val stderrReader = drain(process.errorStream, stderr, "chrootctl-bridge-stream-stderr", drainFailures)
        val stdoutReader = drainStreaming(process.inputStream, output, "chrootctl-bridge-stream-stdout", drainFailures)
        var finished = false
        var timedOut = false
        try {
            process.outputStream.bufferedWriter(StandardCharsets.UTF_8).use { writer -> writer.write(requestJson) }
            finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS)
            timedOut = !finished
            if (timedOut) {
                drainFailures += "chrootctl-bridge-stream timed out after ${timeoutSeconds}s"
                terminateTree(process, drainFailures)
            }
        } catch (interrupted: InterruptedException) {
            drainFailures += "chrootctl-bridge-stream wait interrupted"
            terminateTree(process, drainFailures)
            Thread.currentThread().interrupt()
            throw interrupted
        } finally {
            if (!finished && process.isAlive) terminateTree(process, drainFailures)
            stdoutReader.join(READER_JOIN_TIMEOUT_MS)
            stderrReader.join(READER_JOIN_TIMEOUT_MS)
            runCatching { output.flush() }
        }
        return BridgeStreamResult(
            exitCode = if (finished) process.exitValue() else -1,
            timedOut = timedOut,
            errorOutput = bridgeErrorOutput(stderr, drainFailures),
            truncated = stderr.truncated,
        )
    }

    private fun start(arguments: List<String>): Process {
        val command = runtime.argv + arguments
        return ProcessBuilder(command)
            .apply {
                environment().clear()
                environment().putAll(rootBridgeEnvironment())
            }
            .start()
    }

    private fun terminateTree(process: Process, failures: MutableList<String>) {
        runCatching { terminateProcessTree(process) }
            .onFailure { error -> failures += "process-tree termination failed: ${error.message ?: error.javaClass.simpleName}" }
    }

    private fun terminateProcessTree(process: Process) {
        val rootPid = runCatching { process.pid().toInt() }.getOrDefault(-1)
        if (rootPid <= 0) {
            process.destroyForcibly()
            return
        }
        val known = linkedSetOf<Int>()
        fun refresh() {
            if (procPidExists(rootPid)) known += collectProcessTree(rootPid)
        }
        fun signalKnown(signal: Int) {
            known.toList().asReversed().forEach { pid ->
                if (procPidExists(pid)) runCatching { Os.kill(pid, signal) }
            }
        }

        refresh()
        // Stop the bridge itself first so it cannot intentionally launch more work,
        // then signal every descendant captured before that boundary. Keep the PID
        // set after the parent exits so re-parented descendants are still killable.
        runCatching { Os.kill(rootPid, OsConstants.SIGTERM) }
        signalKnown(OsConstants.SIGTERM)
        val termDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(TERMINATE_GRACE_SECONDS)
        while (System.nanoTime() < termDeadline) {
            refresh()
            if (known.none(::procPidExists)) return
            Thread.sleep(TERMINATE_POLL_MS)
        }

        refresh()
        signalKnown(OsConstants.SIGKILL)
        runCatching { process.destroyForcibly() }
        val killDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(TERMINATE_GRACE_SECONDS)
        while (System.nanoTime() < killDeadline && known.any(::procPidExists)) {
            Thread.sleep(TERMINATE_POLL_MS)
        }
    }


    private fun collectProcessTree(rootPid: Int): List<Int> {
        val seen = linkedSetOf<Int>()
        fun visit(pid: Int) {
            if (pid <= 0 || !seen.add(pid)) return
            readChildPids(pid).forEach(::visit)
        }
        visit(rootPid)
        return seen.toList()
    }

    private fun readChildPids(pid: Int): List<Int> = runCatching {
        File("/proc/$pid/task/$pid/children").readText()
            .trim()
            .split(Regex("\\s+"))
            .filter(String::isNotBlank)
            .mapNotNull(String::toIntOrNull)
    }.getOrDefault(emptyList())

    private fun procPidExists(pid: Int): Boolean = File("/proc/$pid").exists()

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

    private fun drain(input: InputStream, output: OutputStream, name: String, failures: MutableList<String>): Thread = Thread({
        try {
            input.use { source -> source.copyTo(output, DEFAULT_BUFFER_SIZE) }
        } catch (error: Throwable) {
            failures += drainFailureMessage(name, error)
        }
    }, name).apply {
        isDaemon = true
        uncaughtExceptionHandler = Thread.UncaughtExceptionHandler { thread, error -> failures += drainFailureMessage(thread.name, error) }
        start()
    }

    private fun drainStreaming(input: InputStream, output: OutputStream, name: String, failures: MutableList<String>): Thread = Thread({
        input.use { source ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            var target: OutputStream = output
            while (true) {
                val count = try { source.read(buffer) } catch (error: Throwable) {
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
        uncaughtExceptionHandler = Thread.UncaughtExceptionHandler { thread, error -> failures += drainFailureMessage(thread.name, error) }
        start()
    }

    private fun drainFailureMessage(name: String, error: Throwable): String =
        "$name closed without crashing the root service: ${error.message ?: error.javaClass.simpleName}"

    private class BoundedOutputStream(private val limit: Int) : OutputStream() {
        private val buffer = ByteArrayOutputStream(minOf(limit, 64 * 1024))
        var truncated: Boolean = false
            private set
        override fun write(value: Int) { if (buffer.size() < limit) buffer.write(value) else truncated = true }
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
        const val TERMINATE_POLL_MS = 50L
        const val STREAM_TIMEOUT_SECONDS = 6 * 60 * 60L
    }
}
