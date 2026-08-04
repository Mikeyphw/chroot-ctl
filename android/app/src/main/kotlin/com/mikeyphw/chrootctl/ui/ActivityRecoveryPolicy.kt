package com.mikeyphw.chrootctl.ui

import com.mikeyphw.chrootctl.model.OperationSummary

enum class OperationActivityFilter(val label: String) {
    All("All"),
    Running("Running"),
    Failed("Failed"),
    Completed("Completed"),
}

fun OperationSummary.isActiveOperation(): Boolean = state.lowercase() in setOf("queued", "running", "cancelling")

fun OperationSummary.isRecoverableFailure(): Boolean = state.lowercase() in setOf("failed", "blocked", "cancelled", "interrupted")

fun OperationSummary.isCompletedOperation(): Boolean = state.lowercase() in setOf("succeeded", "completed")

fun OperationSummary.canCancelOperation(): Boolean = isActiveOperation()

fun OperationSummary.canRetryOperation(): Boolean = isRecoverableFailure()

fun OperationSummary.canRetryWithFixes(): Boolean = canRetryOperation() && kind == "install.run"

fun OperationSummary.canOpenSnapshotRecovery(): Boolean = isRecoverableFailure() && !targetName.isNullOrBlank()

fun OperationActivityFilter.matches(operation: OperationSummary): Boolean = when (this) {
    OperationActivityFilter.All -> true
    OperationActivityFilter.Running -> operation.isActiveOperation()
    OperationActivityFilter.Failed -> operation.isRecoverableFailure()
    OperationActivityFilter.Completed -> operation.isCompletedOperation()
}

fun visibleOperations(operations: List<OperationSummary>, filter: OperationActivityFilter): List<OperationSummary> =
    operations.filter(filter::matches)
