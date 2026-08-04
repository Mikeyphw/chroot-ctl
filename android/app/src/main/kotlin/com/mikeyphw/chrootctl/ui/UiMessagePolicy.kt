package com.mikeyphw.chrootctl.ui

enum class BackendIssueKind {
    ServiceDisconnected,
    Timeout,
    InvalidResponse,
    PermissionDenied,
    RuntimeMissing,
    Unknown,
}

fun classifyBackendIssue(rawMessage: String): BackendIssueKind {
    val message = rawMessage.lowercase()
    return when {
        "deadobjectexception" in message ||
            "binder has died" in message ||
            "privileged service process died" in message ||
            "service disconnected" in message -> BackendIssueKind.ServiceDisconnected
        "timeout" in message || "timed out" in message -> BackendIssueKind.Timeout
        "json" in message ||
            "could not be parsed" in message ||
            "protocol" in message ||
            "invalid bridge response" in message -> BackendIssueKind.InvalidResponse
        "permission denied" in message ||
            "root access" in message ||
            "su request" in message -> BackendIssueKind.PermissionDenied
        "executable" in message ||
            "runtime was not found" in message ||
            "chrootctl was not found" in message -> BackendIssueKind.RuntimeMissing
        else -> BackendIssueKind.Unknown
    }
}

fun isRunningChrootStatus(status: String): Boolean {
    return status.trim().lowercase() in setOf("running", "started", "active", "mounted")
}

fun isRunningOperationState(state: String): Boolean {
    return state.trim().lowercase() in setOf("queued", "pending", "running", "starting", "cancelling")
}
