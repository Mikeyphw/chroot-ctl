package com.mikeyphw.chrootctl.repository

import org.json.JSONArray
import org.json.JSONObject

internal object OperationRecoveryContract {
    private val activeStates = setOf("queued", "running", "cancelling")
    private val terminalStates = setOf("succeeded", "failed", "cancelled", "blocked", "interrupted")
    private val recoverableStates = setOf("failed", "blocked", "cancelled", "interrupted")
    private val previewBoundOperations = setOf(
        "install.run",
        "chroots.remove.execute",
        "chroots.upgrade",
        "snapshots.create",
        "snapshots.restore",
        "snapshots.export",
        "users.add",
        "users.remove",
        "users.set_password",
        "users.set_shell",
        "users.set_sudo",
        "users.sync_uid_gid",
        "services.action",
        "catalog.apply",
        "transfer.import",
        "transfer.export",
        "artifacts.cleanup",
        "support.bundle",
        "system.module_build",
        "repair.apply",
        "cleanup.temp",
        "smoke.run",
    )

    fun isActive(state: String): Boolean = state.lowercase() in activeStates
    fun isTerminal(state: String): Boolean = state.lowercase() in terminalStates

    fun stateForEvent(type: String, fallback: String?): String = when (type) {
        "operation_queued" -> "queued"
        "operation_started", "operation_progress" -> "running"
        "operation_cancelling" -> "cancelling"
        "operation_cancelled" -> "cancelled"
        "operation_succeeded" -> "succeeded"
        "operation_failed" -> "failed"
        "operation_blocked" -> "blocked"
        "operation_interrupted", "bridge_stream_interrupted" -> "interrupted"
        else -> fallback ?: "running"
    }

    fun finishedAtFor(state: String, now: Long, previous: Long?): Long? = if (isTerminal(state)) previous ?: now else previous

    fun requestFromRecord(data: JSONObject): JSONObject? = data.optJSONObject("request")
    fun retryFromRecord(data: JSONObject): JSONObject? = data.optJSONObject("retry") ?: data.optJSONObject("request")

    fun recoveryActions(
        state: String,
        kind: String,
        request: JSONObject?,
        retry: JSONObject?,
        missingInBackend: Boolean,
    ): List<String> {
        val normalized = state.lowercase()
        if (normalized !in recoverableStates) return emptyList()
        if (missingInBackend) return listOf("refresh")
        val replayable = replayableRequest(kind, retry ?: request)
        return buildList {
            add("refresh")
            if (replayable) add("retry")
            if (kind == "install.run" && replayable) add("retry_with_fixes")
            if (kind.startsWith("snapshots.") || kind == "chroots.remove.execute") add("snapshot_recovery")
        }.distinct()
    }

    fun replayableRequest(kind: String, request: JSONObject?): Boolean {
        if (request == null) return false
        val op = request.optString("operation").ifBlank { kind }
        if (op.isBlank() || op == "operations.retry") return false
        if (op in previewBoundOperations) return false
        if (containsRedacted(request)) return false
        return true
    }

    fun retryable(kind: String, request: JSONObject?, retry: JSONObject?, state: String, missingInBackend: Boolean): Boolean =
        !missingInBackend && state.lowercase() in recoverableStates && replayableRequest(kind, retry ?: request)

    fun retryWithFixes(kind: String, request: JSONObject?, retry: JSONObject?, state: String, missingInBackend: Boolean): Boolean =
        kind == "install.run" && retryable(kind, request, retry, state, missingInBackend)

    fun containsRedacted(value: Any?): Boolean = when (value) {
        null, JSONObject.NULL -> false
        is JSONObject -> value.keys().asSequence().any { containsRedacted(value.opt(it)) }
        is JSONArray -> (0 until value.length()).any { containsRedacted(value.opt(it)) }
        is String -> {
            val normalized = value.trim().lowercase()
            normalized == "<redacted>" || normalized == "[redacted]" || normalized == "redacted" ||
                normalized.contains("<redacted>") || normalized.contains("[redacted]")
        }
        else -> false
    }

    fun stableEventKey(operationId: String, type: String, timestamp: String, payloadJson: String): String =
        "$operationId\u001f$type\u001f$timestamp\u001f$payloadJson"
}
