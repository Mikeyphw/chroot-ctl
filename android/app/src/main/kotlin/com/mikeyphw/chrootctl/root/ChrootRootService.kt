package com.mikeyphw.chrootctl.root

import android.content.Intent
import android.os.IBinder
import android.os.ParcelFileDescriptor
import android.os.Process
import android.system.Os
import com.topjohnwu.superuser.ipc.RootService
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

class ChrootRootService : RootService() {
    private val executor = Executors.newCachedThreadPool()
    private val activeRequests = ConcurrentHashMap<String, String>()

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

        override fun query(requestJson: String): String = invokeBridge(
            listOf("query", "--request-file", "-"),
            requestJson,
        )

        override fun preview(requestJson: String): String = invokeBridge(
            listOf("preview", "--request-file", "-"),
            requestJson,
        )

        override fun startOperation(requestJson: String, output: ParcelFileDescriptor): String {
            val requestId = runCatching { JSONObject(requestJson).optString("requestId") }.getOrDefault("")
            if (requestId.isBlank()) {
                output.close()
                return failure("INVALID_REQUEST", "A requestId is required")
            }
            if (activeRequests.putIfAbsent(requestId, "running") != null) {
                output.close()
                return failure("REQUEST_ALREADY_ACTIVE", "Request $requestId is already active")
            }
            val runtime = RuntimeResolver.resolve()
            if (runtime == null) {
                activeRequests.remove(requestId)
                output.close()
                return failure("RUNTIME_NOT_FOUND", RuntimeResolver.diagnostic())
            }
            val owned = runCatching { ParcelFileDescriptor.dup(output.fileDescriptor) }.getOrElse { error ->
                activeRequests.remove(requestId)
                output.close()
                return failure("OUTPUT_DUPLICATION_FAILED", error.message ?: "Unable to duplicate output descriptor")
            }
            output.close()
            executor.submit {
                runCatching {
                    BridgeProcess(runtime).stream(
                        listOf("run", "--request-file", "-", "--events", "ndjson"),
                        requestJson,
                        ParcelFileDescriptor.AutoCloseOutputStream(owned),
                    )
                }
                activeRequests.remove(requestId)
            }
            return JSONObject()
                .put("ok", true)
                .put("requestId", requestId)
                .put("state", "started")
                .toString()
        }

        override fun operationState(operationId: String): String = invokeBridge(listOf("operation", operationId))

        override fun reconcileOperation(operationId: String): String = invokeBridge(listOf("reconcile", operationId))

        override fun cancelOperation(operationId: String): String = invokeBridge(listOf("cancel", operationId))

        override fun transferFromDescriptor(requestJson: String, input: ParcelFileDescriptor): String = runCatching {
            val request = JSONObject(requestJson)
            val payload = request.optJSONObject("payload") ?: JSONObject()
            val filename = safeFileName(payload.optString("filename", "import.tar.zst"))
            val stagingId = UUID.randomUUID().toString().replace("-", "")
            val directory = transferDirectory()
            val target = directory.resolve("$stagingId-$filename")
            val partial = directory.resolve(".$stagingId-$filename.partial")
            try {
                ParcelFileDescriptor.AutoCloseInputStream(input).use { source ->
                    FileOutputStream(partial).use { destination ->
                        source.copyTo(destination)
                        destination.fd.sync()
                    }
                }
                check(partial.renameTo(target)) { "Unable to atomically publish staged import" }
            } finally {
                partial.delete()
            }
            envelope(
                request.optString("requestId", "unknown"),
                JSONObject()
                    .put("stagingId", stagingId)
                    .put("path", target.path)
                    .put("archive", target.path)
                    .put("filename", target.name),
            )
        }.getOrElse { error -> failure("TRANSFER_STAGE_FAILED", error.message ?: error.javaClass.simpleName) }

        override fun transferToDescriptor(requestJson: String, output: ParcelFileDescriptor): String = runCatching {
            val request = JSONObject(requestJson)
            val payload = request.optJSONObject("payload") ?: JSONObject()
            val path = payload.optString("path", payload.optString("archive", ""))
            val source = File(path)
            val root = transferDirectory().canonicalFile
            val resolved = source.canonicalFile
            val contained = resolved == root || resolved.toPath().startsWith(root.toPath())
            check(contained) { "Only managed transfer artifacts can be copied to a document" }
            FileInputStream(resolved).use { input ->
                ParcelFileDescriptor.AutoCloseOutputStream(output).use { destination -> input.copyTo(destination) }
            }
            envelope(request.optString("requestId", "unknown"), JSONObject().put("path", resolved.path).put("bytes", resolved.length()))
        }.getOrElse { error -> failure("TRANSFER_COPY_FAILED", error.message ?: error.javaClass.simpleName) }
    }

    override fun onBind(intent: Intent): IBinder = binder

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun invokeBridge(arguments: List<String>, requestJson: String? = null): String {
        val runtime = RuntimeResolver.resolve() ?: return failure("RUNTIME_NOT_FOUND", RuntimeResolver.diagnostic())
        return runCatching { BridgeProcess(runtime).invoke(arguments, requestJson) }
            .fold(
                onSuccess = { result ->
                    when (val validation = validateBridgeProcessResult(runtime, result)) {
                        is BridgeOutputValidation.Accepted -> validation.json
                        is BridgeOutputValidation.Rejected -> {
                            RuntimeResolver.invalidate(runtime)
                            failure(validation.code, validation.message)
                        }
                    }
                },
                onFailure = { error ->
                    RuntimeResolver.invalidate(runtime)
                    failure("BRIDGE_PROCESS_FAILED", error.message ?: error.javaClass.simpleName)
                },
            )
    }

    private fun transferDirectory(): File {
        val root = File(File(File.separator, "data"), "local/tmp")
        return File(root, "chrootctl-transfer").also { it.mkdirs() }
    }

    private fun safeFileName(raw: String): String = raw
        .ifBlank { "archive.tar.zst" }
        .substringAfterLast('/')
        .substringAfterLast('\\')
        .replace(Regex("[^A-Za-z0-9._-]"), "_")
        .ifBlank { "archive.tar.zst" }

    private fun envelope(requestId: String, data: JSONObject): String = JSONObject()
        .put("protocolVersion", 1)
        .put("requestId", requestId)
        .put("ok", true)
        .put("data", data)
        .put("error", JSONObject.NULL)
        .put("warnings", org.json.JSONArray())
        .put("nextSteps", org.json.JSONArray())
        .toString()

    private fun failure(code: String, message: String): String = JSONObject()
        .put("protocolVersion", 1)
        .put("requestId", "unknown")
        .put("ok", false)
        .put("data", JSONObject.NULL)
        .put("error", JSONObject().put("code", code).put("message", message).put("details", JSONObject()))
        .put("warnings", org.json.JSONArray())
        .put("nextSteps", org.json.JSONArray())
        .toString()
}
