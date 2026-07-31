package com.mikeyphw.chrootctl.protocol

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class BridgeRequestTest {
    @Test
    fun requestUsesVersionedAllowlistedShape() {
        val json = JSONObject(BridgeRequest("system.dashboard", requestId = "test-request").toJson())
        assertEquals(1, json.getInt("protocolVersion"))
        assertEquals("system.dashboard", json.getString("operation"))
        assertFalse(json.has("command"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun operationCannotContainShellText() {
        BridgeRequest("system.dashboard; rm -rf /")
    }
}
