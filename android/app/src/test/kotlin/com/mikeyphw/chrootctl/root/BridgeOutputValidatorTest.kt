package com.mikeyphw.chrootctl.root

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BridgeOutputValidatorTest {
    private val runtime = BridgeRuntime(listOf("/test/chrootctl", "app"), "test", "/test/chrootctl")

    @Test
    fun `valid protocol envelope is accepted even when bridge reports a command failure`() {
        val result = BridgeProcessResult(
            exitCode = 2,
            output = """{"protocolVersion":1,"requestId":"test","ok":false,"data":null,"error":{"code":"FAILED","message":"failed"},"warnings":[],"nextSteps":[]}""",
        )

        val validation = validateBridgeProcessResult(runtime, result)

        assertTrue(validation is BridgeOutputValidation.Accepted)
    }

    @Test
    fun `usage output is rejected before it reaches protocol parsing`() {
        val result = BridgeProcessResult(
            exitCode = 2,
            output = "usage: chrootctl [-h] command\n",
        )

        val validation = validateBridgeProcessResult(runtime, result) as BridgeOutputValidation.Rejected

        assertEquals("INVALID_BRIDGE_RESPONSE", validation.code)
        assertTrue(validation.message.contains("usage: chrootctl"))
    }

    @Test
    fun `stderr is surfaced when stdout is empty`() {
        val result = BridgeProcessResult(
            exitCode = 2,
            output = "",
            errorOutput = "error: argument command: invalid choice: 'app'",
        )

        val validation = validateBridgeProcessResult(runtime, result) as BridgeOutputValidation.Rejected

        assertEquals("EMPTY_BRIDGE_RESPONSE", validation.code)
        assertTrue(validation.message.contains("invalid choice"))
    }

    @Test
    fun `resolver skips incompatible candidates`() {
        val stale = BridgeRuntime(listOf("stale"), "test", "stale")
        val current = BridgeRuntime(listOf("current"), "test", "current")

        val selected = selectCompatibleRuntime(listOf(stale, current)) { it == current }

        assertEquals(current, selected)
    }
    @Test
    fun `truncated bridge output is a transport failure`() {
        val result = BridgeProcessResult(
            exitCode = 0,
            output = """{"protocolVersion":1,"requestId":"test","ok":true,"data":{},"error":null,"warnings":[],"nextSteps":[]}""",
            truncated = true,
        )

        val validation = validateBridgeProcessResult(runtime, result, "test") as BridgeOutputValidation.Rejected

        assertEquals("BRIDGE_RESPONSE_TRUNCATED", validation.code)
    }

    @Test
    fun `request id mismatch is rejected`() {
        val result = BridgeProcessResult(
            exitCode = 0,
            output = """{"protocolVersion":1,"requestId":"other","ok":true,"data":{},"error":null,"warnings":[],"nextSteps":[]}""",
        )

        val validation = validateBridgeProcessResult(runtime, result, "expected") as BridgeOutputValidation.Rejected

        assertEquals("BRIDGE_REQUEST_ID_MISMATCH", validation.code)
    }

}
