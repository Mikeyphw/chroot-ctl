package com.mikeyphw.chrootctl.root

import android.content.Intent
import android.os.IBinder
import android.os.ParcelFileDescriptor
import android.os.Process
import android.os.StatFs
import android.system.Os
import com.topjohnwu.superuser.ipc.RootService
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class ChrootRootService : RootService() {
    private val executor = ThreadPoolExecutor(
        2,
        MAX_WORKERS,
        30L,
        TimeUnit.SECONDS,
        ArrayBlockingQueue(MAX_QUEUED_WORK),
        ThreadPoolExecutor.AbortPolicy(),
    )
    private data class TransferHandle(
        val cancelled: AtomicBoolean,
        val descriptor: ParcelFileDescriptor,
    )

    private val activeRequests = ConcurrentHashMap<String, String>()
    private val activeTransfers = ConcurrentHashMap<String, TransferHandle>()

    private val binder = object : IChrootRootService.Stub() {
        override fun serviceInfo(): String {
            val runtime = RuntimeResolver.resolve()
            val uid = Process.myUid()
            return JSONObject()
                .put("ok", uid == 0 && runtime != null)
                .put("uid", uid)
                .put("gid", runCatching { Os.getgid() }.getOrDefault(-1))
                .put("pid", Process.myPid())
                .put("backend", runtime?.backend ?: "unavailable")
                .put("executable", runtime?.executable ?: JSONObject.NULL)
                .put("binaryResolution", RuntimeResolver.diagnosticJson())
                .put("arbitraryShell", false)
                .put(
                    "message",
                    when {
                        uid != 0 -> "Root service is running as UID $uid instead of UID 0"
                        runtime == null -> RuntimeResolver.diagnostic()
                        else -> "Root bridge is ready"
                    },
                )
                .toString()
        }

        override fun capabilities(): String = invokeBridge(listOf("capabilities"))

        override fun query(requestJson: String): String = requestGuard(requestJson) {
            invokeBridge(listOf("query", "--request-file", "-"), requestJson)
        }

        override fun preview(requestJson: String): String = requestGuard(requestJson) {
            invokeBridge(listOf("preview", "--request-file", "-"), requestJson)
        }

        override fun startOperation(requestJson: String, output: ParcelFileDescriptor): String {
            val request = validatedRequest(requestJson) ?: run {
                runCatching { output.close() }
                return failure(requestIdFrom(requestJson), "INVALID_REQUEST", "A valid bounded request with requestId is required")
            }
            val requestId = request.getString("requestId")
            if (activeRequests.putIfAbsent(requestId, "running") != null) {
                output.close()
                return failure(requestId, "REQUEST_ALREADY_ACTIVE", "Request $requestId is already active")
            }
            val runtime = RuntimeResolver.resolve()
            if (runtime == null) {
                activeRequests.remove(requestId)
                output.close()
                return failure(requestId, "RUNTIME_NOT_FOUND", RuntimeResolver.diagnostic())
            }
            val owned = runCatching { ParcelFileDescriptor.dup(output.fileDescriptor) }.getOrElse { error ->
                activeRequests.remove(requestId)
                output.close()
                return failure(requestId, "OUTPUT_DUPLICATION_FAILED", error.message ?: "Unable to duplicate output descriptor")
            }
            output.close()
            try {
                executor.execute {
                    try {
                        ParcelFileDescriptor.AutoCloseOutputStream(owned).use { stream ->
                            val result = BridgeProcess(runtime).stream(
                                listOf("run", "--request-file", "-", "--events", "ndjson"),
                                requestJson,
                                stream,
                            )
                            if (result.timedOut || result.exitCode != 0 || result.truncated) {
                                val event = JSONObject()
                                    .put("type", "bridge_process_failed")
                                    .put("operationId", "")
                                    .put("requestId", requestId)
                                    .put(
                                        "payload",
                                        JSONObject()
                                            .put("message", result.errorOutput.ifBlank { "Privileged bridge stream ended with exit ${result.exitCode}" })
                                            .put("exitCode", result.exitCode)
                                            .put("timedOut", result.timedOut)
                                            .put("truncated", result.truncated),
                                    )
                                runCatching {
                                    stream.write((event.toString() + "\n").toByteArray(Charsets.UTF_8))
                                    stream.flush()
                                }
                            }
                        }
                    } finally {
                        activeRequests.remove(requestId)
                    }
                }
            } catch (_: RejectedExecutionException) {
                activeRequests.remove(requestId)
                owned.close()
                return failure(requestId, "ROOT_SERVICE_BUSY", "The privileged worker queue is full; retry after current work completes")
            }
            return JSONObject().put("ok", true).put("requestId", requestId).put("state", "started").toString()
        }

        override fun operationState(operationId: String): String = invokeBridge(listOf("operation", operationId))
        override fun reconcileOperation(operationId: String): String = invokeBridge(listOf("reconcile", operationId))
        override fun cancelOperation(operationId: String): String = invokeBridge(listOf("cancel", operationId))

        override fun transferFromDescriptor(requestJson: String, input: ParcelFileDescriptor): String =
            startTransfer(requestJson, input, expectedOperation = "transfer.stage_import", direction = "import")

        override fun transferToDescriptor(requestJson: String, output: ParcelFileDescriptor): String =
            startTransfer(requestJson, output, expectedOperation = "transfer.copy_to_document", direction = "export")

        override fun transferState(requestId: String): String {
            if (!validRequestId(requestId)) return failure(requestId, "INVALID_REQUEST_ID", "Invalid transfer request id")
            val state = readTransferState(requestId)
                ?: return failure(requestId, "TRANSFER_NOT_FOUND", "No transfer state exists for request $requestId")
            if (state.optString("state") in setOf("running", "cancelling") && !activeTransfers.containsKey(requestId)) {
                state.put("state", "interrupted")
                    .put("error", "Root service restarted before transfer completion; the operation was not replayed")
                persistTransferState(requestId, state)
            }
            return envelope(requestId, state)
        }

        override fun cancelTransfer(requestId: String): String {
            if (!validRequestId(requestId)) return failure(requestId, "INVALID_REQUEST_ID", "Invalid transfer request id")
            activeTransfers[requestId]?.let { handle ->
                handle.cancelled.set(true)
                runCatching { handle.descriptor.close() }
            }
            val state = readTransferState(requestId) ?: JSONObject().put("requestId", requestId)
            if (state.optString("state") == "running") {
                state.put("state", "cancelling").put("updatedAt", System.currentTimeMillis())
                persistTransferState(requestId, state)
            }
            return envelope(requestId, state)
        }
    }

    override fun onBind(intent: Intent): IBinder = binder

    override fun onDestroy() {
        activeTransfers.values.forEach { handle ->
            handle.cancelled.set(true)
            runCatching { handle.descriptor.close() }
        }
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun startTransfer(
        requestJson: String,
        descriptor: ParcelFileDescriptor,
        expectedOperation: String,
        direction: String,
    ): String {
        val request = validatedRequest(requestJson)
        if (request == null || request.optString("operation") != expectedOperation) {
            runCatching { descriptor.close() }
            return failure(requestIdFrom(requestJson), "INVALID_TRANSFER_REQUEST", "Expected operation $expectedOperation with protocolVersion 1")
        }
        val requestId = request.getString("requestId")
        validateTransferPayload(request, expectedOperation)?.let { message ->
            runCatching { descriptor.close() }
            return failure(requestId, "INVALID_TRANSFER_REQUEST", message)
        }
        val owned = runCatching { ParcelFileDescriptor.dup(descriptor.fileDescriptor) }.getOrElse { error ->
            descriptor.close()
            return failure(requestId, "DESCRIPTOR_DUPLICATION_FAILED", error.message ?: "Unable to duplicate transfer descriptor")
        }
        descriptor.close()
        if (readTransferState(requestId) != null) {
            owned.close()
            return failure(requestId, "TRANSFER_REQUEST_REUSED", "Transfer request id $requestId already exists; create a new request id for each transfer")
        }
        val cancel = AtomicBoolean(false)
        val handle = TransferHandle(cancel, owned)
        if (activeTransfers.putIfAbsent(requestId, handle) != null) {
            owned.close()
            return failure(requestId, "TRANSFER_ALREADY_ACTIVE", "Transfer $requestId is already active")
        }
        val state = JSONObject()
            .put("requestId", requestId)
            .put("operation", expectedOperation)
            .put("direction", direction)
            .put("state", "running")
            .put("bytes", 0L)
            .put("startedAt", System.currentTimeMillis())
            .put("updatedAt", System.currentTimeMillis())
        persistTransferState(requestId, state)
        try {
            executor.execute {
                try {
                    val result = if (direction == "import") stageImport(request, owned, cancel, state) else copyExport(request, owned, cancel, state)
                    state.put("state", "succeeded").put("result", result).put("completedAt", System.currentTimeMillis())
                } catch (error: TransferCancelledException) {
                    state.put("state", "cancelled").put("error", "Transfer cancelled")
                } catch (error: Throwable) {
                    if (cancel.get() || Thread.currentThread().isInterrupted) {
                        state.put("state", "cancelled").put("error", "Transfer cancelled")
                    } else {
                        state.put("state", "failed").put("error", error.message ?: error.javaClass.simpleName)
                    }
                } finally {
                    state.put("updatedAt", System.currentTimeMillis())
                    runCatching { owned.close() }
                    persistTransferState(requestId, state)
                    activeTransfers.remove(requestId, handle)
                }
            }
        } catch (_: RejectedExecutionException) {
            activeTransfers.remove(requestId, handle)
            owned.close()
            state.put("state", "failed").put("error", "The privileged worker queue is full")
            persistTransferState(requestId, state)
            return failure(requestId, "ROOT_SERVICE_BUSY", "The privileged worker queue is full; retry after current work completes")
        }
        return envelope(requestId, JSONObject(state.toString()).put("state", "started"))
    }

    private fun stageImport(request: JSONObject, input: ParcelFileDescriptor, cancel: AtomicBoolean, state: JSONObject): JSONObject {
        val payload = request.optJSONObject("payload") ?: JSONObject()
        val filename = safeFileName(payload.optString("filename", "import.tar.zst"))
        val directory = transferDirectory()
        val stagingId = UUID.randomUUID().toString().replace("-", "")
        val target = directory.resolve("$stagingId-$filename")
        val partial = directory.resolve(".$stagingId-$filename.partial")
        val available = StatFs(directory.path).availableBytes
        val maxBytes = minOf(MAX_TRANSFER_BYTES, (available - MIN_FREE_BYTES).coerceAtLeast(0L))
        check(maxBytes > 0) { "Insufficient free space for transfer staging" }
        try {
            ParcelFileDescriptor.AutoCloseInputStream(input).use { source ->
                FileOutputStream(partial).use { destination ->
                    val bytes = copyBounded(source, destination, maxBytes, cancel, state)
                    destination.fd.sync()
                    state.put("bytes", bytes)
                }
            }
            if (cancel.get()) throw TransferCancelledException()
            check(partial.renameTo(target)) { "Unable to atomically publish staged import" }
            Os.chmod(target.path, 0x180) // 0600
            val checksum = sha256(target)
            val checksumPath = publishChecksumSidecar(target, checksum)
            syncDirectory(directory)
            return JSONObject()
                .put("stagingId", stagingId)
                .put("path", target.path)
                .put("archive", target.path)
                .put("filename", target.name)
                .put("bytes", target.length())
                .put("checksum", checksum)
                .put("checksumPath", checksumPath.path)
                .put("checksum_path", checksumPath.path)
        } finally {
            partial.delete()
        }
    }

    private fun publishChecksumSidecar(archive: File, checksum: String): File {
        val sidecar = File(archive.parentFile, archive.name + ".sha256")
        val partial = File(archive.parentFile, ".${archive.name}.sha256.partial-${System.nanoTime()}")
        try {
            FileOutputStream(partial).use { out ->
                out.write((checksum + "  " + archive.name + "\n").toByteArray(Charsets.UTF_8))
                out.fd.sync()
            }
            check(partial.renameTo(sidecar)) { "Unable to publish checksum sidecar" }
            Os.chmod(sidecar.path, 0x180) // 0600
            return sidecar
        } finally {
            partial.delete()
        }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(256 * 1024)
        FileInputStream(file).use { input ->
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                if (count > 0) digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun copyExport(request: JSONObject, output: ParcelFileDescriptor, cancel: AtomicBoolean, state: JSONObject): JSONObject {
        val payload = request.optJSONObject("payload") ?: JSONObject()
        val path = payload.optString("path", payload.optString("archive", ""))
        val root = transferDirectory().canonicalFile
        val resolved = File(path).canonicalFile
        check(resolved.isFile && resolved.toPath().startsWith(root.toPath())) { "Only managed transfer artifacts can be copied to a document" }
        val bytes = FileInputStream(resolved).use { input ->
            ParcelFileDescriptor.AutoCloseOutputStream(output).use { destination ->
                copyBounded(input, destination, MAX_TRANSFER_BYTES, cancel, state)
            }
        }
        return JSONObject().put("path", resolved.path).put("bytes", bytes)
    }

    private fun copyBounded(
        input: java.io.InputStream,
        output: java.io.OutputStream,
        maxBytes: Long,
        cancel: AtomicBoolean,
        state: JSONObject,
    ): Long {
        val buffer = ByteArray(256 * 1024)
        var total = 0L
        var nextCheckpoint = TRANSFER_CHECKPOINT_BYTES
        var lastPersistAt = System.currentTimeMillis()
        while (true) {
            if (cancel.get() || Thread.currentThread().isInterrupted) throw TransferCancelledException()
            val count = input.read(buffer)
            if (count < 0) break
            if (count == 0) continue
            total += count
            check(total <= maxBytes) { "Transfer exceeds the maximum allowed size" }
            output.write(buffer, 0, count)
            val now = System.currentTimeMillis()
            if (total >= nextCheckpoint || now - lastPersistAt >= TRANSFER_PROGRESS_HEARTBEAT_MS) {
                state.put("bytes", total).put("updatedAt", now)
                persistTransferState(state.getString("requestId"), state)
                nextCheckpoint = total + TRANSFER_CHECKPOINT_BYTES
                lastPersistAt = now
            }
        }
        output.flush()
        return total
    }

    private fun invokeBridge(arguments: List<String>, requestJson: String? = null): String {
        val runtime = RuntimeResolver.resolve() ?: return failure(requestIdFrom(requestJson), "RUNTIME_NOT_FOUND", RuntimeResolver.diagnostic())
        val expectedRequestId = requestJson?.let(::requestIdFrom)?.takeIf { it != "unknown" }
        return runCatching { BridgeProcess(runtime).invoke(arguments, requestJson) }
            .fold(
                onSuccess = { result ->
                    when (val validation = validateBridgeProcessResult(runtime, result, expectedRequestId)) {
                        is BridgeOutputValidation.Accepted -> validation.json
                        is BridgeOutputValidation.Rejected -> {
                            RuntimeResolver.invalidate(runtime)
                            failure(expectedRequestId ?: "unknown", validation.code, validation.message)
                        }
                    }
                },
                onFailure = { error ->
                    RuntimeResolver.invalidate(runtime)
                    failure(expectedRequestId ?: "unknown", "BRIDGE_PROCESS_FAILED", error.message ?: error.javaClass.simpleName)
                },
            )
    }

    private inline fun requestGuard(requestJson: String, block: () -> String): String {
        val request = validatedRequest(requestJson) ?: return failure(requestIdFrom(requestJson), "INVALID_REQUEST", "Request is invalid or exceeds the Binder request budget")
        return block().also { request.optString("requestId") }
    }

    private fun validatedRequest(requestJson: String): JSONObject? {
        if (requestJson.toByteArray(Charsets.UTF_8).size > MAX_BINDER_REQUEST_BYTES) return null
        val request = runCatching { JSONObject(requestJson) }.getOrNull() ?: return null
        if (request.optInt("protocolVersion", -1) != 1) return null
        if (!validRequestId(request.optString("requestId"))) return null
        if (request.optString("operation").isBlank()) return null
        return request
    }

    private fun requestIdFrom(requestJson: String?): String = runCatching { JSONObject(requestJson.orEmpty()).optString("requestId") }
        .getOrDefault("").takeIf(::validRequestId) ?: "unknown"

    private fun validRequestId(value: String): Boolean = value.length in 1..128 && value.matches(Regex("^[A-Za-z0-9._:-]+$"))


    private fun transferDirectory(): File {
        val parent = File("/data/local/tmp")
        requireCanonicalDirectory(parent, requireRootOwner = false, mode = null)
        val directory = File(parent, "chrootctl-transfer")
        ensurePrivateRootDirectory(directory)
        val journal = File(directory, ".requests")
        ensurePrivateRootDirectory(journal)
        return directory
    }

    private fun ensurePrivateRootDirectory(directory: File) {
        if (!directory.exists()) {
            check(directory.mkdir()) { "Unable to create privileged directory ${directory.path}" }
        }
        requireCanonicalDirectory(directory, requireRootOwner = true, mode = 0x1c0)
    }

    private fun requireCanonicalDirectory(directory: File, requireRootOwner: Boolean, mode: Int?) {
        val stat = Os.lstat(directory.path)
        check((stat.st_mode and android.system.OsConstants.S_IFMT) == android.system.OsConstants.S_IFDIR) {
            "Privileged path is not a directory: ${directory.path}"
        }
        check(!java.nio.file.Files.isSymbolicLink(directory.toPath())) { "Privileged path must not be a symlink: ${directory.path}" }
        val canonical = directory.canonicalFile
        check(canonical == directory.absoluteFile) { "Privileged path must be canonical: ${directory.path}" }
        if (requireRootOwner) {
            check(stat.st_uid.toInt() == 0) { "Privileged path must be root-owned: ${directory.path}" }
            if (mode != null) {
                Os.chmod(directory.path, mode)
                val secured = Os.lstat(directory.path)
                check((secured.st_mode and 0x1ff) == mode) { "Privileged path permissions could not be secured: ${directory.path}" }
            }
        }
    }

    private fun validateTransferPayload(request: JSONObject, expectedOperation: String): String? {
        val allowedTopLevel = setOf("protocolVersion", "requestId", "operation", "payload")
        val topLevelKeys = request.keys().asSequence().toSet()
        val unknownTopLevel = topLevelKeys - allowedTopLevel
        if (unknownTopLevel.isNotEmpty()) return "Unknown transfer request fields: ${unknownTopLevel.sorted().joinToString()}"
        val payload = request.optJSONObject("payload") ?: return "Transfer payload must be an object"
        val allowedPayload = when (expectedOperation) {
            "transfer.stage_import" -> setOf("filename")
            "transfer.copy_to_document" -> setOf("path")
            else -> emptySet()
        }
        val unknownPayload = payload.keys().asSequence().toSet() - allowedPayload
        if (unknownPayload.isNotEmpty()) return "Unknown $expectedOperation payload fields: ${unknownPayload.sorted().joinToString()}"
        return when (expectedOperation) {
            "transfer.stage_import" -> if (payload.optString("filename").isBlank()) "Import filename is required" else null
            "transfer.copy_to_document" -> if (payload.optString("path").isBlank()) "Managed artifact path is required" else null
            else -> "Unsupported transfer operation"
        }
    }

    private fun transferJournal(): File = File(transferDirectory(), ".requests")
    private fun transferStateFile(requestId: String): File = File(transferJournal(), "$requestId.json")

    private fun persistTransferState(requestId: String, state: JSONObject) {
        if (!validRequestId(requestId)) return
        val journal = transferJournal()
        val final = transferStateFile(requestId)
        val temp = File(journal, ".$requestId.${System.nanoTime()}.tmp")
        FileOutputStream(temp).use { out ->
            out.write(state.toString().toByteArray(Charsets.UTF_8))
            out.fd.sync()
        }
        check(temp.renameTo(final)) { "Unable to publish transfer state" }
        Os.chmod(final.path, 0x180) // 0600
        syncDirectory(journal)
    }

    private fun readTransferState(requestId: String): JSONObject? = if (!validRequestId(requestId)) null else runCatching {
        val file = transferStateFile(requestId)
        if (!file.isFile) null else JSONObject(file.readText())
    }.getOrNull()

    private fun syncDirectory(directory: File) {
        runCatching {
            val fd = Os.open(directory.path, android.system.OsConstants.O_RDONLY or O_DIRECTORY_COMPAT, 0)
            try { Os.fsync(fd) } finally { Os.close(fd) }
        }
    }

    private fun safeFileName(raw: String): String = raw.ifBlank { "archive.tar.zst" }
        .substringAfterLast('/').substringAfterLast('\\').replace(Regex("[^A-Za-z0-9._-]"), "_").ifBlank { "archive.tar.zst" }

    private fun envelope(requestId: String, data: JSONObject): String = JSONObject()
        .put("protocolVersion", 1).put("requestId", requestId).put("ok", true).put("data", data)
        .put("error", JSONObject.NULL).put("warnings", JSONArray()).put("nextSteps", JSONArray()).toString()

    private fun failure(requestId: String, code: String, message: String): String = JSONObject()
        .put("protocolVersion", 1).put("requestId", requestId.ifBlank { "unknown" }).put("ok", false).put("data", JSONObject.NULL)
        .put("error", JSONObject().put("code", code).put("message", message).put("details", JSONObject()))
        .put("warnings", JSONArray()).put("nextSteps", JSONArray()).toString()

    private class TransferCancelledException : RuntimeException()

    private companion object {
        const val MAX_WORKERS = 4
        const val MAX_QUEUED_WORK = 32
        const val MAX_BINDER_REQUEST_BYTES = 256 * 1024
        const val MAX_TRANSFER_BYTES = 16L * 1024 * 1024 * 1024
        const val MIN_FREE_BYTES = 64L * 1024 * 1024
        const val TRANSFER_CHECKPOINT_BYTES = 1024L * 1024
        const val TRANSFER_PROGRESS_HEARTBEAT_MS = 30_000L
        const val O_DIRECTORY_COMPAT = 0x10000
        val TERMINAL_TRANSFER_STATES = setOf("succeeded", "failed", "cancelled", "interrupted")
    }
}
