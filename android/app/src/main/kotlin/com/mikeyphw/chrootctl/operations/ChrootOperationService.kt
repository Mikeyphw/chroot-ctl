package com.mikeyphw.chrootctl.operations

import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.core.content.edit
import com.mikeyphw.chrootctl.ChrootCtlApplication
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.UUID

class ChrootOperationService : Service() {
    private lateinit var notifications: OperationNotificationController
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var activeJob: Job? = null
    private var activeOperationId: String? = null
    private var cancelRequested: Boolean = false

    private val state by lazy { getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE) }

    override fun onCreate() {
        super.onCreate()
        notifications = OperationNotificationController(this)
        notifications.ensureChannel()
        activeOperationId = state.getString(KEY_OPERATION_ID, null)
        cancelRequested = state.getBoolean(KEY_CANCEL_REQUESTED, false)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CANCEL -> cancelActive(intent.getStringExtra(EXTRA_OPERATION_ID))
            ACTION_REFRESH -> startSystemRefresh()
            ACTION_BRIDGE_OPERATION -> startBridgeOperation(
                intent.getStringExtra(EXTRA_OPERATION).orEmpty(),
                JSONObject(intent.getStringExtra(EXTRA_PAYLOAD).orEmpty().ifBlank { "{}" }),
            )
            else -> resumePersistedOperation(startId)
        }
        return START_REDELIVER_INTENT
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun startSystemRefresh() {
        startBridgeOperation("system.refresh", JSONObject().put("title", "Native state refresh"))
    }

    private fun startBridgeOperation(operation: String, payload: JSONObject) {
        if (activeJob?.isActive == true) {
            rejectSecondOperation(operation, "Another foreground operation is already running; open Activity to review or cancel it before starting a new request.")
            return
        }
        if (operation.isBlank()) {
            stopSelf()
            return
        }
        val persistedOperation = state.getString(KEY_OPERATION, null)
        val persistedId = state.getString(KEY_OPERATION_ID, null)
        val persistedRequestId = state.getString(KEY_REQUEST_ID, null)
        if (!persistedOperation.isNullOrBlank() &&
            (!persistedId.isNullOrBlank() || !persistedRequestId.isNullOrBlank())
        ) {
            // Never overwrite recoverable persisted work with a second request. The
            // original operation must reconcile to terminal state first, and the
            // dropped request is surfaced explicitly instead of disappearing.
            activeOperationId = persistedId
            rejectSecondOperation(operation, "A persisted foreground operation is waiting for reconciliation; this new request was not admitted.")
            resumePersistedOperation(null)
            return
        }

        val requestId = UUID.randomUUID().toString()
        state.edit {
            putString(KEY_OPERATION, operation)
            putString(KEY_REQUEST_ID, requestId)
            remove(KEY_OPERATION_ID)
            putBoolean(KEY_CANCEL_REQUESTED, false)
            putInt(KEY_RECOVERY_ATTEMPTS, 0)
        }
        activeOperationId = null
        cancelRequested = false
        notifications.startForeground(this, notifications.build(operation.replace('.', ' '), "Queued"))
        activeJob = scope.launch {
            var terminalConfirmed = false
            var recoveryError: Throwable? = null
            try {
                val repository = (application as ChrootCtlApplication).container.bridgeRepository
                var terminalSeen = false
                repository.startBridgeOperation(operation, payload, requestId) { event ->
                    activeOperationId = event.optString("operationId").takeIf(String::isNotBlank) ?: activeOperationId
                    activeOperationId?.let { operationId -> state.edit { putString(KEY_OPERATION_ID, operationId) } }
                    val type = event.optString("type")
                    terminalSeen = terminalSeen || isTerminal(type)
                    notifications.update(event, activeOperationId)
                    if (cancelRequested) activeOperationId?.let { id -> repository.cancelOperation(id) }
                }.onFailure { error ->
                    recoveryError = error
                    notifications.update(
                        JSONObject().put("type", "bridge_stream_interrupted")
                            .put("operationId", activeOperationId ?: "")
                            .put("payload", JSONObject().put("message", error.message ?: error.javaClass.simpleName)),
                        activeOperationId,
                    )
                }
                if (terminalSeen) {
                    terminalConfirmed = true
                } else {
                    val operationId = activeOperationId ?: discoverOperationId(requestId, repository)
                    if (!operationId.isNullOrBlank()) {
                        activeOperationId = operationId
                        state.edit { putString(KEY_OPERATION_ID, operationId) }
                        reconcileUntilTerminal(operationId, repository)
                        terminalConfirmed = true
                    }
                }
            } catch (error: Throwable) {
                recoveryError = error
                notifications.update(
                    JSONObject().put("type", "bridge_stream_interrupted")
                        .put("operationId", activeOperationId ?: "")
                        .put("payload", JSONObject().put("message", error.message ?: error.javaClass.simpleName)),
                    activeOperationId,
                )
            } finally {
                if (terminalConfirmed) finishOperation() else preserveForRecovery(recoveryError)
            }
        }
    }

    private fun resumePersistedOperation(startId: Int?) {
        if (activeJob?.isActive == true) return
        val persistedOperationId = state.getString(KEY_OPERATION_ID, null)
        val requestId = state.getString(KEY_REQUEST_ID, null)
        val operation = state.getString(KEY_OPERATION, null)
        if (operation.isNullOrBlank() || (persistedOperationId.isNullOrBlank() && requestId.isNullOrBlank())) {
            if (startId != null) stopSelf(startId) else stopSelf()
            return
        }
        activeOperationId = persistedOperationId
        notifications.startForeground(this, notifications.build(operation.replace('.', ' '), "Reconnecting…", persistedOperationId))
        activeJob = scope.launch {
            var terminalConfirmed = false
            var recoveryError: Throwable? = null
            try {
                val repository = (application as ChrootCtlApplication).container.bridgeRepository
                val operationId = persistedOperationId ?: discoverOperationId(requestId.orEmpty(), repository)
                if (operationId.isNullOrBlank()) {
                    recoveryError = IllegalStateException("Could not reconcile the persisted operation request with the backend journal.")
                    notifications.update(
                        JSONObject().put("type", "bridge_stream_interrupted")
                            .put("operationId", "")
                            .put("payload", JSONObject().put("message", recoveryError?.message)),
                        null,
                    )
                } else {
                    activeOperationId = operationId
                    state.edit { putString(KEY_OPERATION_ID, operationId) }
                    reconcileUntilTerminal(operationId, repository)
                    terminalConfirmed = true
                }
            } catch (error: Throwable) {
                recoveryError = error
            } finally {
                if (terminalConfirmed) finishOperation() else preserveForRecovery(recoveryError)
            }
        }
    }

    private suspend fun discoverOperationId(
        requestId: String,
        repository: com.mikeyphw.chrootctl.repository.BridgeRepository,
    ): String? {
        if (requestId.isBlank()) return null
        repeat(REQUEST_DISCOVERY_ATTEMPTS) {
            repository.findOperationIdByRequestId(requestId).getOrNull()?.let { return it }
            delay(RECONCILE_INTERVAL_MS)
        }
        return null
    }

    private suspend fun reconcileUntilTerminal(operationId: String, repository: com.mikeyphw.chrootctl.repository.BridgeRepository) {
        // This path is entered only after the live stream ended or the Android service
        // resumed persisted work. Reconciliation is bounded so a dead/missing backend
        // cannot keep the foreground service alive forever.
        repeat(MAX_RECONCILE_ATTEMPTS) {
            repository.reconcileOperation(operationId).getOrThrow()
            repository.refreshOperationDetail(operationId).getOrThrow()
            val current = repository.operation(operationId).first()
            if (current != null) {
                notifications.update(
                    JSONObject()
                        .put("type", eventTypeForState(current.state))
                        .put("operationId", operationId)
                        .put("payload", JSONObject().put("message", current.errorMessage ?: current.progressText).put("percent", current.progressPercent)),
                    operationId,
                )
                if (cancelRequested && !isTerminalState(current.state)) repository.cancelOperation(operationId).getOrThrow()
                if (isTerminalState(current.state)) return
            }
            delay(RECONCILE_INTERVAL_MS)
        }
        throw IllegalStateException("Operation $operationId did not reconcile to a terminal backend state within the bounded recovery window.")
    }

    private fun preserveForRecovery(error: Throwable?) {
        activeJob = null
        val operationId = activeOperationId
        val attempts = state.getInt(KEY_RECOVERY_ATTEMPTS, 0) + 1
        state.edit { putInt(KEY_RECOVERY_ATTEMPTS, attempts) }
        notifications.update(
            JSONObject().put("type", "bridge_stream_interrupted")
                .put("operationId", operationId ?: "")
                .put(
                    "payload",
                    JSONObject()
                        .put("message", error?.message ?: "Operation state preserved for reconciliation.")
                        .put("attempt", attempts)
                        .put("maxAttempts", MAX_SERVICE_RECOVERY_ATTEMPTS),
                ),
            operationId,
        )
        if (attempts < MAX_SERVICE_RECOVERY_ATTEMPTS) {
            scope.launch {
                delay(RECONCILE_INTERVAL_MS)
                if (activeJob?.isActive != true) resumePersistedOperation(null)
            }
        } else {
            stopSelf()
        }
    }

    private fun rejectSecondOperation(operation: String, message: String) {
        notifications.update(
            JSONObject()
                .put("type", "operation_blocked")
                .put("operationId", activeOperationId ?: "")
                .put("payload", JSONObject().put("operation", operation).put("message", message)),
            activeOperationId,
        )
    }

    @android.annotation.TargetApi(35)
    override fun onTimeout(startId: Int, fgsType: Int) {
        preserveForRecovery(IllegalStateException("Foreground data-sync timeout reached; operation state was preserved for Activity reconciliation."))
        super.onTimeout(startId, fgsType)
    }

    private fun finishOperation() {
        state.edit { clear() }
        cancelRequested = false
        activeOperationId = null
        activeJob = null
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_DETACH)
        stopSelf()
    }

    private fun cancelActive(requestedOperationId: String?) {
        val operationId = requestedOperationId?.takeIf(String::isNotBlank) ?: activeOperationId
        cancelRequested = true
        state.edit { putBoolean(KEY_CANCEL_REQUESTED, true) }
        if (operationId.isNullOrBlank()) {
            notifications.update(
                JSONObject()
                    .put("type", "operation_progress")
                    .put("payload", JSONObject().put("message", "Cancellation requested; waiting for the operation id.")),
                null,
            )
            if (activeJob?.isActive != true) resumePersistedOperation(null)
            return
        }
        activeOperationId = operationId
        state.edit { putString(KEY_OPERATION_ID, operationId) }
        if (activeJob?.isActive == true) {
            scope.launch {
                val repository = (application as ChrootCtlApplication).container.bridgeRepository
                repository.cancelOperation(operationId)
            }
        } else {
            // Cancellation can be the only work after a process/service restart.
            // Keep the foreground service alive until the durable backend journal
            // reaches a terminal state instead of firing cancel and stopping blind.
            activeJob = scope.launch {
                var terminalConfirmed = false
                var recoveryError: Throwable? = null
                try {
                    val repository = (application as ChrootCtlApplication).container.bridgeRepository
                    repository.cancelOperation(operationId)
                    reconcileUntilTerminal(operationId, repository)
                    terminalConfirmed = true
                } catch (error: Throwable) {
                    recoveryError = error
                } finally {
                    if (terminalConfirmed) finishOperation() else preserveForRecovery(recoveryError)
                }
            }
        }
    }

    private fun eventTypeForState(state: String): String = when (state) {
        "succeeded" -> "operation_succeeded"
        "failed" -> "operation_failed"
        "cancelled" -> "operation_cancelled"
        "blocked" -> "operation_blocked"
        "interrupted" -> "operation_interrupted"
        else -> "operation_progress"
    }

    private fun isTerminal(type: String): Boolean = type in setOf(
        "operation_succeeded",
        "operation_failed",
        "operation_cancelled",
        "operation_blocked",
        "operation_interrupted",
    )

    private fun isTerminalState(state: String): Boolean = state in setOf("succeeded", "failed", "cancelled", "blocked", "interrupted")

    companion object {
        private const val ACTION_REFRESH = "com.mikeyphw.chrootctl.action.REFRESH_OPERATION"
        private const val ACTION_CANCEL = "com.mikeyphw.chrootctl.action.CANCEL_OPERATION"
        private const val ACTION_BRIDGE_OPERATION = "com.mikeyphw.chrootctl.action.BRIDGE_OPERATION"
        private const val EXTRA_OPERATION_ID = "operation_id"
        private const val EXTRA_OPERATION = "operation"
        private const val EXTRA_PAYLOAD = "payload"
        private const val PREFS_NAME = "chrootctl_active_operation"
        private const val KEY_OPERATION_ID = "operation_id"
        private const val KEY_REQUEST_ID = "request_id"
        private const val KEY_OPERATION = "operation"
        private const val KEY_CANCEL_REQUESTED = "cancel_requested"
        private const val KEY_RECOVERY_ATTEMPTS = "recovery_attempts"
        private const val RECONCILE_INTERVAL_MS = 2_000L
        private const val REQUEST_DISCOVERY_ATTEMPTS = 30
        private const val MAX_RECONCILE_ATTEMPTS = 60
        private const val MAX_SERVICE_RECOVERY_ATTEMPTS = 3

        fun startRefresh(context: Context) {
            val intent = Intent(context, ChrootOperationService::class.java).setAction(ACTION_REFRESH)
            ContextCompat.startForegroundService(context, intent)
        }

        fun startBridgeOperation(context: Context, operation: String, payloadJson: String) {
            val intent = Intent(context, ChrootOperationService::class.java)
                .setAction(ACTION_BRIDGE_OPERATION)
                .putExtra(EXTRA_OPERATION, operation)
                .putExtra(EXTRA_PAYLOAD, payloadJson)
            ContextCompat.startForegroundService(context, intent)
        }

        fun cancelIntent(context: Context, operationId: String?): Intent = Intent(context, ChrootOperationService::class.java)
            .setAction(ACTION_CANCEL)
            .putExtra(EXTRA_OPERATION_ID, operationId)
    }
}
