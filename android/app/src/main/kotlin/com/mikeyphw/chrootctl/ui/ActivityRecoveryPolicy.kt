package com.mikeyphw.chrootctl.ui

import com.mikeyphw.chrootctl.model.OperationSummary

private val activeStates = setOf("queued", "running", "cancelling")
private val recoverableStates = setOf("failed", "blocked", "cancelled", "interrupted")
private val completedStates = setOf("succeeded", "completed")

enum class OperationActivityFilter(val label: String) {
    All("All"),
    Running("Running"),
    Failed("Needs recovery"),
    Completed("Completed"),
}

fun OperationSummary.isActiveOperation(): Boolean = state.lowercase() in activeStates && !missingInBackend

fun OperationSummary.isRecoverableFailure(): Boolean = state.lowercase() in recoverableStates || missingInBackend

fun OperationSummary.isCompletedOperation(): Boolean = state.lowercase() in completedStates

fun OperationSummary.canCancelOperation(): Boolean = isActiveOperation() && state.lowercase() != "cancelling"

fun OperationSummary.canRetryOperation(): Boolean = retryable && recoveryActions.contains("retry")

fun OperationSummary.canRetryWithFixes(): Boolean = retryWithFixes && recoveryActions.contains("retry_with_fixes")

fun OperationSummary.canOpenSnapshotRecovery(): Boolean =
    !missingInBackend && recoveryActions.contains("snapshot_recovery") && targetName?.let { operationNeedsSnapshotRecovery(this, it) } == true

fun OperationActivityFilter.matches(operation: OperationSummary): Boolean = when (this) {
    OperationActivityFilter.All -> true
    OperationActivityFilter.Running -> operation.isActiveOperation()
    OperationActivityFilter.Failed -> operation.isRecoverableFailure()
    OperationActivityFilter.Completed -> operation.isCompletedOperation()
}

fun visibleOperations(operations: List<OperationSummary>, filter: OperationActivityFilter): List<OperationSummary> =
    operations.filter(filter::matches)
