package com.mikeyphw.chrootctl.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UiFoundationPolicyTest {
    @Test
    fun `compact width uses bottom navigation`() {
        assertEquals(PrimaryNavigationType.BottomBar, primaryNavigationType(719f))
    }

    @Test
    fun `expanded width uses navigation rail`() {
        assertEquals(PrimaryNavigationType.Rail, primaryNavigationType(720f))
        assertEquals(PrimaryNavigationType.Rail, primaryNavigationType(1180f))
    }

    @Test
    fun `binder death is classified as a reconnectable service interruption`() {
        assertEquals(
            BackendIssueKind.ServiceDisconnected,
            classifyBackendIssue("android.os.DeadObjectException: binder has died"),
        )
    }

    @Test
    fun `invalid bridge payload is classified without exposing it as the primary message`() {
        assertEquals(
            BackendIssueKind.InvalidResponse,
            classifyBackendIssue("Root verifier output could not be parsed: invalid JSON"),
        )
    }

    @Test
    fun `running state helpers tolerate backend vocabulary and casing`() {
        assertTrue(isRunningChrootStatus("ACTIVE"))
        assertTrue(isRunningOperationState("cancelling"))
        assertFalse(isRunningChrootStatus("stopped"))
        assertFalse(isRunningOperationState("failed"))
    }
}
