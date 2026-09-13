package com.mikeyphw.chrootctl.ui

import com.mikeyphw.chrootctl.model.OperationSummary
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ActivityRecoveryPolicyChr18Test {
    @Test
    fun `retry buttons are gated by backend metadata not state alone`() {
        val failedWithoutReplay = op(state = "failed", retryable = false, actions = listOf("refresh"))
        assertFalse(failedWithoutReplay.canRetryOperation())

        val replayable = op(state = "failed", retryable = true, actions = listOf("refresh", "retry"))
        assertTrue(replayable.canRetryOperation())
    }

    @Test
    fun `cancelling and missing backend operations are not cancellable`() {
        assertFalse(op(state = "cancelling").canCancelOperation())
        assertFalse(op(state = "running", missing = true).canCancelOperation())
    }

    private fun op(
        state: String,
        retryable: Boolean = false,
        actions: List<String> = emptyList(),
        missing: Boolean = false,
    ) = OperationSummary(
        operationId = "op-1",
        kind = "system.refresh",
        title = "Refresh",
        state = state,
        targetName = null,
        phase = null,
        progressPercent = null,
        progressText = state,
        errorCode = null,
        errorMessage = null,
        createdAt = 1L,
        stale = false,
        retryable = retryable,
        recoveryActions = actions,
        missingInBackend = missing,
    )
}
