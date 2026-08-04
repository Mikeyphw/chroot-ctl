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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class RootServiceClient(private val context: Context) {
    private data class BoundService(
        val service: IChrootRootService,
        val binder: IBinder,
        val connection: ServiceConnection,
        val deathRecipient: IBinder.DeathRecipient,
    )

    private class BinderHealthCheckException(message: String) : IllegalStateException(message)

    private val bindMutex = Mutex()
    private val callMutex = Mutex()
    private val stateLock = Any()
    private val mainHandler = Handler(Looper.getMainLooper())

    @Volatile private var boundService: BoundService? = null
    @Volatile private var activeConnection: ServiceConnection? = null
    @Volatile private var lastDisconnectReason: String = "The privileged service has not connected yet"

    suspend fun serviceInfo(): String = call("Service status", BinderReplayPolicy.SAFE_READ_ONLY) { it.serviceInfo() }
    suspend fun capabilities(): String = call("Capabilities", BinderReplayPolicy.SAFE_READ_ONLY) { it.capabilities() }
    suspend fun query(requestJson: String): String = call("Query", BinderReplayPolicy.SAFE_READ_ONLY) { it.query(requestJson) }
    suspend fun preview(requestJson: String): String = call("Preview", BinderReplayPolicy.SAFE_READ_ONLY) { it.preview(requestJson) }
    suspend fun operationState(operationId: String): String = call("Operation status", BinderReplayPolicy.SAFE_READ_ONLY) { it.operationState(operationId) }
    suspend fun cancelOperation(operationId: String): String = call("Cancel operation", BinderReplayPolicy.NEVER) { it.cancelOperation(operationId) }
    suspend fun transferFromDescriptor(requestJson: String, input: ParcelFileDescriptor): String =
        call("Import transfer", BinderReplayPolicy.NEVER, TRANSFER_TIMEOUT_MS) { it.transferFromDescriptor(requestJson, input) }
    suspend fun transferToDescriptor(requestJson: String, output: ParcelFileDescriptor): String =
        call("Export transfer", BinderReplayPolicy.NEVER, TRANSFER_TIMEOUT_MS) { it.transferToDescriptor(requestJson, output) }

    suspend fun streamOperation(requestJson: String, onEvent: suspend (String) -> Unit): String {
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
        withContext(Dispatchers.IO) {
            ParcelFileDescriptor.AutoCloseInputStream(readSide).bufferedReader().use { reader ->
                while (true) {
                    val line = reader.readLine() ?: break
                    if (line.isNotBlank()) onEvent(line)
                }
            }
        }
        return started
    }

    fun close() {
        val connection = clearConnection("The Android client closed the privileged service connection")
        connection?.let(::postUnbind)
    }

    private suspend fun call(
        label: String,
        replayPolicy: BinderReplayPolicy,
        timeoutMs: Long = CALL_TIMEOUT_MS,
        block: (IChrootRootService) -> String,
    ): String = try {
        withTimeout(timeoutMs) {
            callMutex.withLock {
                executeWithBinderRecovery(
                    label = label,
                    replayPolicy = replayPolicy,
                    attempt = {
                        val service = service()
                        requireHealthyBinder(service.asBinder(), label)
                        withContext(Dispatchers.IO) { block(service) }
                    },
                    recover = { error ->
                        disconnectCurrent(transportReason(label, error))
                    },
                    isTransportFailure = ::isBinderTransportFailure,
                    describeFailure = ::describeTransportFailure,
                )
            }
        }
    } catch (error: TimeoutCancellationException) {
        disconnectCurrent("$label timed out after ${timeoutMs}ms")
        throw IllegalStateException(
            "$label timed out. The privileged service connection was reset; retry the action.",
            error,
        )
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
        const val CALL_TIMEOUT_MS = 30_000L
        const val START_TIMEOUT_MS = 10_000L
        const val TRANSFER_TIMEOUT_MS = 120_000L
    }
}
