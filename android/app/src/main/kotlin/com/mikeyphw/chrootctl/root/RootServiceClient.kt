package com.mikeyphw.chrootctl.root

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.DeadObjectException
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.os.RemoteException
import com.topjohnwu.superuser.ipc.RootService
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class RootServiceClient(private val context: Context) : BridgeTransport {
    private data class BoundService(
        val service: IChrootRootService,
        val binder: IBinder,
        val connection: ServiceConnection,
        val deathRecipient: IBinder.DeathRecipient,
    )

    private class BinderHealthCheckException(message: String) : IllegalStateException(message)

    private val bindMutex = Mutex()
    private val stateLock = Any()
    private val mainHandler = Handler(Looper.getMainLooper())

    @Volatile private var boundService: BoundService? = null
    @Volatile private var activeConnection: ServiceConnection? = null
    @Volatile private var lastDisconnectReason: String = "The privileged service has not connected yet"

    override suspend fun serviceInfo(): String = call("Service status", BinderReplayPolicy.SAFE_READ_ONLY) { it.serviceInfo() }
    override suspend fun capabilities(): String = call("Capabilities", BinderReplayPolicy.SAFE_READ_ONLY) { it.capabilities() }
    override suspend fun query(requestJson: String): String = checkedRequestCall("Query", requestJson, BinderReplayPolicy.SAFE_READ_ONLY) { it.query(requestJson) }
    override suspend fun preview(requestJson: String): String = checkedRequestCall("Preview", requestJson, BinderReplayPolicy.SAFE_READ_ONLY) { it.preview(requestJson) }
    override suspend fun operationState(operationId: String): String = call("Operation status", BinderReplayPolicy.SAFE_READ_ONLY) { it.operationState(operationId) }
    override suspend fun reconcileOperation(operationId: String): String = call("Reconcile operation", BinderReplayPolicy.NEVER) { it.reconcileOperation(operationId) }
    override suspend fun cancelOperation(operationId: String): String = call("Cancel operation", BinderReplayPolicy.NEVER) { it.cancelOperation(operationId) }
    override suspend fun transferFromDescriptor(requestJson: String, input: ParcelFileDescriptor): String =
        transferCall("Import transfer", requestJson) { it.transferFromDescriptor(requestJson, input) }
    override suspend fun transferToDescriptor(requestJson: String, output: ParcelFileDescriptor): String =
        transferCall("Export transfer", requestJson) { it.transferToDescriptor(requestJson, output) }
    override suspend fun transferState(requestId: String): String {
        val response = call("Transfer status", BinderReplayPolicy.SAFE_READ_ONLY) { it.transferState(requestId) }
        requireResponseRequestId("Transfer status", response, requestId)
        return response
    }
    override suspend fun cancelTransfer(requestId: String): String {
        val response = call("Cancel transfer", BinderReplayPolicy.NEVER) { it.cancelTransfer(requestId) }
        requireResponseRequestId("Cancel transfer", response, requestId)
        return response
    }

    override suspend fun streamOperation(requestJson: String, onEvent: suspend (String) -> Unit): String {
        requireRequestBudget("Start operation", requestJson)
        val pipe = ParcelFileDescriptor.createPipe()
        val readSide = pipe[0]
        val writeSide = pipe[1]
        val started = try {
            call("Start operation", BinderReplayPolicy.NEVER, START_TIMEOUT_MS) { service ->
                service.startOperation(requestJson, writeSide)
            }
        } finally {
            runCatching { writeSide.close() }
        }
        val startJson = JSONObject(started)
        if (!startJson.optBoolean("ok")) {
            readSide.close()
            return started
        }
        var operationId: String? = null
        var terminalEventSeen = false
        withContext(Dispatchers.IO) {
            val closeOnCancel = coroutineContext[Job]?.invokeOnCompletion { runCatching { readSide.close() } }
            try {
                ParcelFileDescriptor.AutoCloseInputStream(readSide).bufferedReader().use { reader ->
                    while (true) {
                        val line = reader.readLine() ?: break
                        if (line.isBlank()) continue
                        runCatching { JSONObject(line) }.getOrNull()?.let { event ->
                            operationId = event.optString("operationId").takeIf(String::isNotBlank) ?: operationId
                            terminalEventSeen = terminalEventSeen || isTerminalEvent(event.optString("type"))
                        }
                        onEvent(line)
                    }
                }
            } finally {
                closeOnCancel?.dispose()
                runCatching { readSide.close() }
            }
        }
        if (!terminalEventSeen) {
            val knownOperationId = operationId
            if (knownOperationId.isNullOrBlank()) {
                onEvent(
                    JSONObject()
                        .put("type", "bridge_stream_interrupted")
                        .put("operationId", "")
                        .put("payload", JSONObject().put("message", "Operation stream ended before an operation id or terminal event was received."))
                        .toString(),
                )
            } else {
                val stateEnvelope = runCatching { operationState(knownOperationId) }.getOrNull()
                val reconciled = stateEnvelope?.let(::terminalEventFromOperationState)
                if (reconciled != null) {
                    onEvent(reconciled.toString())
                } else {
                    onEvent(
                        JSONObject()
                            .put("type", "bridge_stream_interrupted")
                            .put("operationId", knownOperationId)
                            .put("payload", JSONObject().put("message", "Operation stream ended before a terminal event; refresh Activity to reconcile state."))
                            .toString(),
                    )
                }
            }
        }
        return started
    }

    private fun terminalEventFromOperationState(envelopeJson: String): JSONObject? {
        val envelope = runCatching { JSONObject(envelopeJson) }.getOrNull() ?: return null
        if (!envelope.optBoolean("ok")) return null
        val data = envelope.optJSONObject("data") ?: return null
        val state = data.optString("state")
        val type = when (state) {
            "succeeded" -> "operation_succeeded"
            "failed" -> "operation_failed"
            "cancelled" -> "operation_cancelled"
            "blocked" -> "operation_blocked"
            "interrupted" -> "operation_interrupted"
            else -> return null
        }
        return JSONObject()
            .put("schemaVersion", data.optInt("schemaVersion", 1))
            .put("type", type)
            .put("operationId", data.optString("operationId"))
            .put("sequence", data.optInt("eventSequence", 0))
            .put("reconciled", true)
            .put(
                "payload",
                JSONObject()
                    .put("state", state)
                    .put("message", data.optString("error").ifBlank { data.optString("progressText", state) })
                    .put("result", data.opt("resultPayload")),
            )
    }

    private fun isTerminalEvent(type: String): Boolean = type in setOf(
        "operation_succeeded",
        "operation_failed",
        "operation_cancelled",
        "operation_blocked",
        "operation_interrupted",
    )

    override fun close() {
        val connection = clearConnection("The Android client closed the privileged service connection")
        connection?.let(::postUnbind)
    }

    private suspend fun call(
        label: String,
        replayPolicy: BinderReplayPolicy,
        timeoutMs: Long = CALL_TIMEOUT_MS,
        block: (IChrootRootService) -> String,
    ): String {
        var usedBinder: IBinder? = null
        return try {
            withTimeout(timeoutMs) {
                executeWithBinderRecovery(
                    label = label,
                    replayPolicy = replayPolicy,
                    attempt = {
                        val service = service()
                        val binder = service.asBinder()
                        requireHealthyBinder(binder, label)
                        usedBinder = binder
                        withContext(Dispatchers.IO) { block(service) }
                    },
                    recover = { error ->
                        disconnectIfCurrent(usedBinder, transportReason(label, error))
                    },
                    isTransportFailure = ::isBinderTransportFailure,
                    describeFailure = ::describeTransportFailure,
                )
            }
        } catch (error: TimeoutCancellationException) {
            // A coroutine timeout cannot abort an in-flight synchronous Binder call.
            // Do not tear down the process-wide connection here: unrelated calls may
            // be healthy and the late transaction may still complete server-side.
            throw IllegalStateException(
                "$label timed out. The Binder transaction may still be settling; reconcile state before retrying a mutation.",
                error,
            )
        }
    }

    private suspend fun checkedRequestCall(
        label: String,
        requestJson: String,
        replayPolicy: BinderReplayPolicy,
        block: (IChrootRootService) -> String,
    ): String {
        requireRequestBudget(label, requestJson)
        val expectedRequestId = JSONObject(requestJson).optString("requestId")
        require(expectedRequestId.isNotBlank()) { "$label requires requestId" }
        val response = call(label, replayPolicy, block = block)
        requireResponseRequestId(label, response, expectedRequestId)
        return response
    }


    private fun requireResponseRequestId(label: String, responseJson: String, expectedRequestId: String) {
        val envelope = runCatching { JSONObject(responseJson) }.getOrElse {
            throw IllegalStateException("$label returned invalid JSON before request-id correlation", it)
        }
        val actual = envelope.optString("requestId")
        check(actual == expectedRequestId) {
            "$label response requestId $actual did not match $expectedRequestId"
        }
    }

    private fun requireRequestBudget(label: String, requestJson: String) {
        require(requestJson.toByteArray(Charsets.UTF_8).size <= MAX_BINDER_REQUEST_BYTES) {
            "$label request exceeds the Android Binder-safe request ceiling of $MAX_BINDER_REQUEST_BYTES bytes"
        }
    }

    private suspend fun transferCall(
        label: String,
        requestJson: String,
        block: (IChrootRootService) -> String,
    ): String {
        requireRequestBudget(label, requestJson)
        val requestId = JSONObject(requestJson).optString("requestId")
        require(requestId.isNotBlank()) { "$label requires requestId" }
        val started = try {
            call(label, BinderReplayPolicy.NEVER, START_TIMEOUT_MS, block)
        } catch (error: RootServiceTransportException) {
            return reconcileTransferAfterLoss(label, requestId, error)
        } catch (error: IllegalStateException) {
            return reconcileTransferAfterLoss(label, requestId, error)
        }
        requireResponseRequestId(label, started, requestId)
        val startEnvelope = JSONObject(started)
        if (!startEnvelope.optBoolean("ok")) return started
        return try {
            awaitTransfer(label, requestId)
        } catch (error: CancellationException) {
            runCatching { cancelTransfer(requestId) }
            throw error
        }
    }

    private suspend fun awaitTransfer(label: String, requestId: String): String {
        var lastBytes = -1L
        var lastServerUpdate = -1L
        var lastProgressAt = System.currentTimeMillis()
        while (true) {
            val stateJson = transferState(requestId)
            val envelope = JSONObject(stateJson)
            if (!envelope.optBoolean("ok")) return stateJson
            val state = envelope.optJSONObject("data") ?: return stateJson
            val bytes = state.optLong("bytes", 0L)
            val serverUpdate = state.optLong("updatedAt", 0L)
            if (bytes != lastBytes || serverUpdate != lastServerUpdate) {
                lastBytes = bytes
                lastServerUpdate = serverUpdate
                lastProgressAt = System.currentTimeMillis()
            } else if (System.currentTimeMillis() - lastProgressAt > TRANSFER_STALL_TIMEOUT_MS) {
                runCatching { cancelTransfer(requestId) }
                throw RootServiceTransportException("$label made no transfer progress for ${TRANSFER_STALL_TIMEOUT_MS / 1000}s; cancellation was requested")
            }
            when (state.optString("state")) {
                "succeeded" -> {
                    val result = state.optJSONObject("result") ?: JSONObject()
                    return JSONObject()
                        .put("protocolVersion", 1)
                        .put("requestId", requestId)
                        .put("ok", true)
                        .put("data", result)
                        .put("error", JSONObject.NULL)
                        .put("warnings", org.json.JSONArray())
                        .put("nextSteps", org.json.JSONArray())
                        .toString()
                }
                "failed", "cancelled", "interrupted" -> {
                    return JSONObject()
                        .put("protocolVersion", 1)
                        .put("requestId", requestId)
                        .put("ok", false)
                        .put("data", JSONObject.NULL)
                        .put(
                            "error",
                            JSONObject()
                                .put("code", "TRANSFER_${state.optString("state").uppercase()}")
                                .put("message", state.optString("error").ifBlank { "$label ${state.optString("state")}" })
                                .put("details", JSONObject().put("bytes", state.optLong("bytes", 0L))),
                        )
                        .put("warnings", org.json.JSONArray())
                        .put("nextSteps", org.json.JSONArray())
                        .toString()
                }
            }
            delay(TRANSFER_RECONCILE_DELAY_MS)
        }
    }

    private suspend fun reconcileTransferAfterLoss(label: String, requestId: String, cause: Throwable): String {
        if (requestId.isBlank()) throw cause
        repeat(TRANSFER_RECONCILE_ATTEMPTS) { attempt ->
            val state = runCatching { transferState(requestId) }.getOrNull()
            if (state != null) {
                val envelope = runCatching { JSONObject(state) }.getOrNull()
                val transfer = envelope?.optJSONObject("data")
                when (transfer?.optString("state")) {
                    "succeeded", "failed", "cancelled", "interrupted" -> return awaitTransfer(label, requestId)
                    "running", "cancelling", "started" -> return awaitTransfer(label, requestId)
                }
            }
            if (attempt + 1 < TRANSFER_RECONCILE_ATTEMPTS) delay(TRANSFER_RECONCILE_DELAY_MS)
        }
        throw RootServiceTransportException(
            "$label lost its Binder response. Request $requestId was not replayed and could not yet be reconciled; refresh transfer state before retrying.",
            cause,
        )
    }

    private fun disconnectIfCurrent(binder: IBinder?, reason: String) {
        if (binder == null) return
        val isCurrent = synchronized(stateLock) { boundService?.binder === binder }
        if (!isCurrent) return
        clearConnection(reason)?.let(::postUnbind)
    }

    private suspend fun service(): IChrootRootService {
        healthyServiceOrNull()?.let { return it }
        return bindMutex.withLock {
            healthyServiceOrNull()?.let { return@withLock it }
            disconnectCurrent("Rebinding after an unavailable or stale privileged service connection")
            bindService()
        }
    }

    private fun healthyServiceOrNull(): IChrootRootService? {
        val state = boundService ?: return null
        return if (binderIsHealthy(state.binder)) state.service else null
    }

    private fun requireHealthyBinder(binder: IBinder, label: String) {
        if (!binderIsHealthy(binder)) {
            throw BinderHealthCheckException(
                "$label could not start because the privileged service Binder failed its health probe. " +
                    lastDisconnectReason,
            )
        }
    }

    private fun binderIsHealthy(binder: IBinder): Boolean = runCatching {
        binder.isBinderAlive && binder.pingBinder()
    }.getOrDefault(false)

    private suspend fun bindService(): IChrootRootService = withTimeout(BIND_TIMEOUT_MS) {
        withContext(Dispatchers.Main.immediate) {
            suspendCancellableCoroutine { continuation ->
                val intent = Intent(context, ChrootRootService::class.java)
                lateinit var connection: ServiceConnection

                fun failBinding(reason: String, error: Throwable) {
                    val shouldUnbind = synchronized(stateLock) {
                        if (activeConnection !== connection) {
                            false
                        } else {
                            boundService = null
                            activeConnection = null
                            lastDisconnectReason = reason
                            true
                        }
                    }
                    if (shouldUnbind) postUnbind(connection)
                    if (continuation.isActive) continuation.resumeWithException(error)
                }

                connection = object : ServiceConnection {
                    override fun onServiceConnected(name: ComponentName, binder: IBinder) {
                        val service = IChrootRootService.Stub.asInterface(binder)
                        val deathRecipient = IBinder.DeathRecipient {
                            invalidateFromCallback(
                                connection = this,
                                binder = binder,
                                reason = "The privileged service process died",
                            )
                        }

                        try {
                            binder.linkToDeath(deathRecipient, 0)
                            if (!binderIsHealthy(binder)) {
                                throw DeadObjectException()
                            }
                        } catch (error: RemoteException) {
                            failBinding(
                                "The privileged service died while the Binder connection was being established",
                                IllegalStateException("The privileged service Binder died during connection", error),
                            )
                            return
                        }

                        val accepted = synchronized(stateLock) {
                            if (activeConnection !== this) {
                                false
                            } else {
                                boundService = BoundService(service, binder, this, deathRecipient)
                                lastDisconnectReason = "Privileged service connected"
                                true
                            }
                        }
                        if (!accepted) {
                            runCatching { binder.unlinkToDeath(deathRecipient, 0) }
                            postUnbind(this)
                            return
                        }
                        if (continuation.isActive) {
                            continuation.resume(service)
                        } else {
                            invalidateFromCallback(
                                connection = this,
                                binder = binder,
                                reason = "The privileged service connection completed after its caller was cancelled",
                            )
                        }
                    }

                    override fun onServiceDisconnected(name: ComponentName) {
                        val reason = "The privileged service process disconnected or crashed"
                        invalidateFromCallback(connection = this, binder = null, reason = reason)
                        if (continuation.isActive) {
                            continuation.resumeWithException(IllegalStateException(reason))
                        }
                    }

                    override fun onBindingDied(name: ComponentName) {
                        val reason = "The privileged service binding died and must be recreated"
                        invalidateFromCallback(connection = this, binder = null, reason = reason)
                        if (continuation.isActive) {
                            continuation.resumeWithException(IllegalStateException(reason))
                        }
                    }

                    override fun onNullBinding(name: ComponentName) {
                        failBinding(
                            "The privileged service rejected the Binder connection",
                            IllegalStateException("The privileged service returned no Binder"),
                        )
                    }
                }

                synchronized(stateLock) {
                    activeConnection = connection
                    boundService = null
                    lastDisconnectReason = "Connecting to the privileged service"
                }
                continuation.invokeOnCancellation {
                    invalidateFromCallback(
                        connection = connection,
                        binder = null,
                        reason = "The privileged service connection attempt was cancelled",
                    )
                }
                runCatching { RootService.bind(intent, connection) }
                    .onFailure { error ->
                        failBinding(
                            "The privileged service could not be launched or bound",
                            IllegalStateException("Unable to bind the privileged service", error),
                        )
                    }
            }
        }
    }

    private suspend fun disconnectCurrent(reason: String) {
        val state: BoundService?
        val connection: ServiceConnection?
        synchronized(stateLock) {
            state = boundService
            connection = activeConnection
            boundService = null
            activeConnection = null
            lastDisconnectReason = reason
        }
        state?.let { runCatching { it.binder.unlinkToDeath(it.deathRecipient, 0) } }
        if (connection != null) {
            withContext(Dispatchers.Main.immediate) {
                runCatching { RootService.unbind(connection) }
            }
        }
    }

    private fun clearConnection(reason: String): ServiceConnection? {
        val state: BoundService?
        val connection: ServiceConnection?
        synchronized(stateLock) {
            state = boundService
            connection = activeConnection
            boundService = null
            activeConnection = null
            lastDisconnectReason = reason
        }
        state?.let { runCatching { it.binder.unlinkToDeath(it.deathRecipient, 0) } }
        return connection
    }

    private fun invalidateFromCallback(
        connection: ServiceConnection,
        binder: IBinder?,
        reason: String,
    ) {
        val state: BoundService?
        val shouldUnbind = synchronized(stateLock) {
            val currentState = boundService
            val matchesConnection = activeConnection === connection
            val matchesBinder = binder == null || currentState?.binder === binder
            if (!matchesConnection || !matchesBinder) {
                state = null
                false
            } else {
                state = currentState
                boundService = null
                activeConnection = null
                lastDisconnectReason = reason
                true
            }
        }
        state?.let { runCatching { it.binder.unlinkToDeath(it.deathRecipient, 0) } }
        if (shouldUnbind) postUnbind(connection)
    }

    private fun postUnbind(connection: ServiceConnection) {
        mainHandler.post { runCatching { RootService.unbind(connection) } }
    }

    private fun isBinderTransportFailure(error: Throwable): Boolean = generateSequence(error) { it.cause }
        .any { cause ->
            cause is DeadObjectException ||
                cause is RemoteException ||
                cause is BinderHealthCheckException
        }

    private fun transportReason(label: String, error: Throwable): String =
        "$label lost the privileged service connection: ${describeTransportFailure(error)}"

    private fun describeTransportFailure(error: Throwable): String {
        val transport = generateSequence(error) { it.cause }
            .firstOrNull { it is DeadObjectException || it is RemoteException || it is BinderHealthCheckException }
            ?: error
        val detail = transport.message?.takeIf { it.isNotBlank() }
        return when (transport) {
            is DeadObjectException -> "the root-service process died during Binder IPC"
            is RemoteException -> detail ?: "Binder IPC failed because the root-service process disconnected"
            else -> detail ?: transport.javaClass.simpleName
        }
    }

    private companion object {
        const val BIND_TIMEOUT_MS = 15_000L
        const val CALL_TIMEOUT_MS = 60_000L
        const val START_TIMEOUT_MS = 20_000L
        const val MAX_BINDER_REQUEST_BYTES = 256 * 1024
        const val TRANSFER_STALL_TIMEOUT_MS = 5 * 60_000L
        const val TRANSFER_RECONCILE_ATTEMPTS = 3
        const val TRANSFER_RECONCILE_DELAY_MS = 250L
    }
}
