package com.mikeyphw.chrootctl.root

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class RootServiceRecoveryTest {
    private class RecoverableFailure(message: String) : IllegalStateException(message)

    @Test
    fun `read only call reconnects and retries exactly once`() = runBlocking {
        var attempts = 0
        var recoveries = 0

        val result = executeWithBinderRecovery(
            label = "Capabilities",
            replayPolicy = BinderReplayPolicy.SAFE_READ_ONLY,
            attempt = {
                attempts += 1
                if (attempts == 1) throw RecoverableFailure("binder died")
                "ready"
            },
            recover = { recoveries += 1 },
            isTransportFailure = { it is RecoverableFailure },
        )

        assertEquals("ready", result)
        assertEquals(2, attempts)
        assertEquals(1, recoveries)
    }

    @Test
    fun `state changing call invalidates transport but is never replayed`() = runBlocking {
        var attempts = 0
        var recoveries = 0

        try {
            executeWithBinderRecovery<String>(
                label = "Start operation",
                replayPolicy = BinderReplayPolicy.NEVER,
                attempt = {
                    attempts += 1
                    throw RecoverableFailure("binder died")
                },
                recover = { recoveries += 1 },
                isTransportFailure = { it is RecoverableFailure },
            )
            fail("Expected RootServiceTransportException")
        } catch (error: RootServiceTransportException) {
            assertTrue(error.message.orEmpty().contains("not retried"))
            assertTrue(error.message.orEmpty().contains("state-changing"))
        }

        assertEquals(1, attempts)
        assertEquals(1, recoveries)
    }

    @Test
    fun `second transport failure is reported after one reconnect`() = runBlocking {
        var attempts = 0
        var recoveries = 0

        try {
            executeWithBinderRecovery<String>(
                label = "Query",
                replayPolicy = BinderReplayPolicy.SAFE_READ_ONLY,
                attempt = {
                    attempts += 1
                    throw RecoverableFailure("binder failure $attempts")
                },
                recover = { recoveries += 1 },
                isTransportFailure = { it is RecoverableFailure },
            )
            fail("Expected RootServiceTransportException")
        } catch (error: RootServiceTransportException) {
            assertTrue(error.message.orEmpty().contains("after reconnecting"))
            assertEquals(1, error.suppressed.size)
        }

        assertEquals(2, attempts)
        assertEquals(2, recoveries)
    }

    @Test
    fun `non transport failures are neither recovered nor replayed`() = runBlocking {
        var attempts = 0
        var recoveries = 0

        try {
            executeWithBinderRecovery<String>(
                label = "Query",
                replayPolicy = BinderReplayPolicy.SAFE_READ_ONLY,
                attempt = {
                    attempts += 1
                    throw IllegalArgumentException("bad request")
                },
                recover = { recoveries += 1 },
                isTransportFailure = { it is RecoverableFailure },
            )
            fail("Expected IllegalArgumentException")
        } catch (error: IllegalArgumentException) {
            assertEquals("bad request", error.message)
        }

        assertEquals(1, attempts)
        assertEquals(0, recoveries)
    }
}
