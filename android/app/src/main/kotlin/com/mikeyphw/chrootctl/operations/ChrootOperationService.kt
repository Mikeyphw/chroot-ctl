package com.mikeyphw.chrootctl.operations

import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.mikeyphw.chrootctl.ChrootCtlApplication
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.json.JSONObject

class ChrootOperationService : Service() {
    private lateinit var notifications: OperationNotificationController
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var activeJob: Job? = null
    private var activeOperationId: String? = null

    override fun onCreate() {
        super.onCreate()
        notifications = OperationNotificationController(this)
        notifications.ensureChannel()
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
            else -> stopSelf(startId)
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun startSystemRefresh() {
        startBridgeOperation("system.refresh", JSONObject().put("title", "Native state refresh"))
    }

    private fun startBridgeOperation(operation: String, payload: JSONObject) {
        if (activeJob?.isActive == true) return
        if (operation.isBlank()) {
            stopSelf()
            return
        }
        notifications.startForeground(this, notifications.build(operation.replace('.', ' '), "Queued"))
        activeJob = scope.launch {
            val repository = (application as ChrootCtlApplication).container.bridgeRepository
            repository.startBridgeOperation(operation, payload) { event ->
                activeOperationId = event.optString("operationId").takeIf(String::isNotBlank) ?: activeOperationId
                notifications.update(event, activeOperationId)
            }.onFailure { error ->
                notifications.update(
                    JSONObject()
                        .put("type", "operation_failed")
                        .put("operationId", activeOperationId ?: "")
                        .put("payload", JSONObject().put("message", error.message ?: error.javaClass.simpleName)),
                    activeOperationId,
                )
            }
            ServiceCompat.stopForeground(this@ChrootOperationService, ServiceCompat.STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun cancelActive(requestedOperationId: String?) {
        val operationId = requestedOperationId ?: activeOperationId
        if (operationId.isNullOrBlank()) {
            stopSelf()
            return
        }
        scope.launch {
            val repository = (application as ChrootCtlApplication).container.bridgeRepository
            repository.cancelOperation(operationId)
        }
    }

    companion object {
        private const val ACTION_REFRESH = "com.mikeyphw.chrootctl.action.REFRESH_OPERATION"
        private const val ACTION_CANCEL = "com.mikeyphw.chrootctl.action.CANCEL_OPERATION"
        private const val ACTION_BRIDGE_OPERATION = "com.mikeyphw.chrootctl.action.BRIDGE_OPERATION"
        private const val EXTRA_OPERATION_ID = "operation_id"
        private const val EXTRA_OPERATION = "operation"
        private const val EXTRA_PAYLOAD = "payload"

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
