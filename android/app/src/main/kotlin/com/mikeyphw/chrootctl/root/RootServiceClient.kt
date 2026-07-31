package com.mikeyphw.chrootctl.root

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.IBinder
import android.os.ParcelFileDescriptor
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
    private val bindMutex = Mutex()
    private val callMutex = Mutex()

    @Volatile private var remote: IChrootRootService? = null
    @Volatile private var activeConnection: ServiceConnection? = null

    suspend fun serviceInfo(): String = call { it.serviceInfo() }
    suspend fun capabilities(): String = call { it.capabilities() }
    suspend fun query(requestJson: String): String = call { it.query(requestJson) }
    suspend fun preview(requestJson: String): String = call { it.preview(requestJson) }
    suspend fun operationState(operationId: String): String = call { it.operationState(operationId) }
    suspend fun cancelOperation(operationId: String): String = call { it.cancelOperation(operationId) }

    suspend fun streamOperation(requestJson: String, onEvent: suspend (String) -> Unit): String {
        val pipe = ParcelFileDescriptor.createPipe()
        val readSide = pipe[0]
        val writeSide = pipe[1]
        val started = call(START_TIMEOUT_MS) { service -> service.startOperation(requestJson, writeSide) }
        runCatching { writeSide.close() }
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
        activeConnection?.let { connection -> runCatching { RootService.unbind(connection) } }
        activeConnection = null
        remote = null
    }

    private suspend fun call(
        timeoutMs: Long = CALL_TIMEOUT_MS,
        block: (IChrootRootService) -> String,
    ): String = try {
        withTimeout(timeoutMs) {
            callMutex.withLock {
                withContext(Dispatchers.IO) { block(service()) }
            }
        }
    } catch (error: TimeoutCancellationException) {
        remote = null
        throw IllegalStateException("Root service call timed out", error)
    }

    private suspend fun service(): IChrootRootService = remote ?: bindMutex.withLock {
        remote ?: bindService().also { remote = it }
    }

    private suspend fun bindService(): IChrootRootService = withTimeout(BIND_TIMEOUT_MS) {
        withContext(Dispatchers.Main.immediate) {
            suspendCancellableCoroutine { continuation ->
                val intent = Intent(context, ChrootRootService::class.java)
                lateinit var connection: ServiceConnection
                connection = object : ServiceConnection {
                    override fun onServiceConnected(name: ComponentName, binder: IBinder) {
                        val service = IChrootRootService.Stub.asInterface(binder)
                        remote = service
                        activeConnection = this
                        if (continuation.isActive) continuation.resume(service)
                    }

                    override fun onServiceDisconnected(name: ComponentName) {
                        if (activeConnection === this) activeConnection = null
                        remote = null
                    }

                    override fun onBindingDied(name: ComponentName) = onServiceDisconnected(name)

                    override fun onNullBinding(name: ComponentName) {
                        onServiceDisconnected(name)
                        if (continuation.isActive) {
                            continuation.resumeWithException(IllegalStateException("Root service returned no binder"))
                        }
                    }
                }
                continuation.invokeOnCancellation { runCatching { RootService.unbind(connection) } }
                runCatching { RootService.bind(intent, connection) }
                    .onFailure { error ->
                        if (continuation.isActive) continuation.resumeWithException(error)
                    }
            }
        }
    }

    private companion object {
        const val BIND_TIMEOUT_MS = 15_000L
        const val CALL_TIMEOUT_MS = 30_000L
        const val START_TIMEOUT_MS = 10_000L
    }
}
