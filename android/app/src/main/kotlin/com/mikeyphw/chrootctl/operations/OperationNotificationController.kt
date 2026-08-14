package com.mikeyphw.chrootctl.operations

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import com.mikeyphw.chrootctl.MainActivity
import com.mikeyphw.chrootctl.R
import org.json.JSONObject

class OperationNotificationController(private val context: Context) {
    fun ensureChannel() {
        val manager = context.getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL_ID,
            context.getString(R.string.operation_notification_channel),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = context.getString(R.string.operation_notification_channel_body)
        }
        manager.createNotificationChannel(channel)
    }

    fun startForeground(service: ChrootOperationService, notification: Notification) {
        val serviceType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        } else {
            0
        }
        ServiceCompat.startForeground(service, NOTIFICATION_ID, notification, serviceType)
    }

    @android.annotation.SuppressLint("MissingPermission")
    fun update(event: JSONObject, fallbackOperationId: String?) {
        val operationId = event.optString("operationId").takeIf(String::isNotBlank) ?: fallbackOperationId
        val payload = event.optJSONObject("payload") ?: JSONObject()
        val type = event.optString("type")
        val terminal = isTerminal(type)
        val title = when (type) {
            "operation_succeeded" -> context.getString(R.string.operation_notification_done_title)
            "operation_failed", "operation_blocked", "operation_interrupted", "bridge_stream_interrupted" -> context.getString(R.string.operation_notification_failed_title)
            "operation_cancelled" -> context.getString(R.string.operation_notification_cancelled_title)
            else -> context.getString(R.string.operation_notification_running_title)
        }
        val body = payload.optString("message").ifBlank { type.ifBlank { context.getString(R.string.operation_notification_body) } }
        val notification = build(
            title = title,
            body = body,
            operationId = operationId,
            percent = payload.optInt("percent", -1).takeIf { it >= 0 },
            terminal = terminal,
        )
        runCatching { NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, notification) }
    }

    fun build(
        title: String = context.getString(R.string.operation_notification_running_title),
        body: String = context.getString(R.string.operation_notification_body),
        operationId: String? = null,
        percent: Int? = null,
        terminal: Boolean = false,
    ): Notification {
        val openIntent = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra(EXTRA_OPEN_OPERATION_ID, operationId),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(openIntent)
            .setOngoing(!terminal)
            .setAutoCancel(terminal)
            .setOnlyAlertOnce(!terminal)
            .setPriority(NotificationCompat.PRIORITY_LOW)

        if (!terminal) {
            val cancelIntent = PendingIntent.getService(
                context,
                1,
                ChrootOperationService.cancelIntent(context, operationId),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            if (percent == null) builder.setProgress(0, 0, true) else builder.setProgress(100, percent, false)
            builder.addAction(0, context.getString(R.string.action_cancel_operation), cancelIntent)
        } else {
            builder.setProgress(0, 0, false)
        }
        return builder.build()
    }

    private fun isTerminal(type: String): Boolean = type in setOf(
        "operation_succeeded",
        "operation_failed",
        "operation_cancelled",
        "operation_blocked",
        "operation_interrupted",
        "bridge_stream_interrupted",
    )

    companion object {
        const val CHANNEL_ID = "chrootctl_operations"
        const val NOTIFICATION_ID = 4001
        const val EXTRA_OPEN_OPERATION_ID = "com.mikeyphw.chrootctl.extra.OPEN_OPERATION_ID"
    }
}
