package com.mikeyphw.chrootctl.ui

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TransferImportLegacyUxTest {
    @Test
    fun `successful matching legacy import resets explicit opt in`() {
        val request = """{"archive":"/tmp/legacy.tar.zst","allowLegacyMetadata":true}"""
        assertTrue(legacyImportCompletionMatches("transfer.import", "succeeded", request, "/tmp/legacy.tar.zst", 2_000L, 1_000L))
    }

    @Test
    fun `failed or unrelated imports do not reset legacy opt in`() {
        val request = """{"archive":"/tmp/legacy.tar.zst","allowLegacyMetadata":true}"""
        assertFalse(legacyImportCompletionMatches("transfer.import", "failed", request, "/tmp/legacy.tar.zst", 2_000L, 1_000L))
        assertFalse(legacyImportCompletionMatches("transfer.import", "succeeded", request, "/tmp/other.tar.zst", 2_000L, 1_000L))
        assertFalse(legacyImportCompletionMatches("transfer.export", "succeeded", request, "/tmp/legacy.tar.zst", 2_000L, 1_000L))
    }

    @Test
    fun `historical matching import cannot reset a newly dispatched opt in`() {
        val request = """{"archive":"/tmp/legacy.tar.zst","allowLegacyMetadata":true}"""
        assertFalse(legacyImportCompletionMatches("transfer.import", "succeeded", request, "/tmp/legacy.tar.zst", 900L, 1_000L))
    }

    @Test
    fun `normal import never triggers legacy reset`() {
        val request = """{"archive":"/tmp/current.tar.zst","allowLegacyMetadata":false}"""
        assertFalse(legacyImportCompletionMatches("transfer.import", "succeeded", request, "/tmp/current.tar.zst", 2_000L, 1_000L))
    }
}
