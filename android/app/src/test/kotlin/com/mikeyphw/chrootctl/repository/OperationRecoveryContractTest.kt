package com.mikeyphw.chrootctl.repository

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OperationRecoveryContractTest {
    @Test
    fun `interrupted stream event is terminal to Room mapping`() {
        assertEquals("interrupted", OperationRecoveryContract.stateForEvent("operation_interrupted", "running"))
        assertEquals("interrupted", OperationRecoveryContract.stateForEvent("bridge_stream_interrupted", "running"))
        assertTrue(OperationRecoveryContract.isTerminal("interrupted"))
    }

    @Test
    fun `retry eligibility requires stored replayable unredacted request`() {
        val replayable = JSONObject()
            .put("operation", "system.refresh")
            .put("payload", JSONObject().put("title", "Refresh"))
        assertTrue(OperationRecoveryContract.retryable("system.refresh", replayable, null, "failed", false))

        val redacted = JSONObject()
            .put("operation", "system.refresh")
            .put("payload", JSONObject().put("token", "<redacted>"))
        assertFalse(OperationRecoveryContract.retryable("system.refresh", redacted, null, "failed", false))
        assertFalse(OperationRecoveryContract.retryable("system.refresh", replayable, null, "running", false))
        assertFalse(OperationRecoveryContract.retryable("system.refresh", replayable, null, "failed", true))
    }

    @Test
    fun `preview-bound install retry needs new preview but repair metadata is explicit`() {
        val install = JSONObject()
            .put("operation", "install.run")
            .put("payload", JSONObject().put("name", "demo"))
        val actions = OperationRecoveryContract.recoveryActions("failed", "install.run", install, install, false)
        assertEquals(listOf("refresh"), actions)
        assertFalse(OperationRecoveryContract.retryWithFixes("install.run", install, install, "failed", false))
    }
}
