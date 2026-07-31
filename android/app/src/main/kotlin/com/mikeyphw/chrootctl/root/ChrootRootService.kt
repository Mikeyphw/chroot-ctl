package com.mikeyphw.chrootctl.root

import android.content.Intent
import android.os.IBinder
import android.os.ParcelFileDescriptor
import android.os.Process
import android.system.Os
import com.topjohnwu.superuser.ipc.RootService
import org.json.JSONObject
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
                        runtime == null -> "The chrootctl bridge runtime was not found"
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
                return failure("RUNTIME_NOT_FOUND", "The chrootctl bridge runtime was not found")
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

        override fun cancelOperation(operationId: String): String = invokeBridge(listOf("cancel", operationId))
    }

    override fun onBind(intent: Intent): IBinder = binder

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun invokeBridge(arguments: List<String>, requestJson: String? = null): String {
        val runtime = RuntimeResolver.resolve() ?: return failure("RUNTIME_NOT_FOUND", "The chrootctl bridge runtime was not found")
        return runCatching { BridgeProcess(runtime).invoke(arguments, requestJson).let { result ->
            if (result.output.isNotBlank()) result.output.trim()
            else failure("EMPTY_BRIDGE_RESPONSE", "Bridge exited with code ${result.exitCode} without output")
        } }.getOrElse { error -> failure("BRIDGE_PROCESS_FAILED", error.message ?: error.javaClass.simpleName) }
    }

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
