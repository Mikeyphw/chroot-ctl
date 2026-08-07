package com.mikeyphw.chrootctl.protocol

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class BridgeModelsTest {
    @Test
    fun `non json bridge output reports a useful error`() {
        val error = assertThrows(IllegalStateException::class.java) {
            BridgeEnvelope.fromJson("usage: chrootctl [-h] command")
        }

        assertTrue(error.message.orEmpty().contains("non-JSON output"))
        assertTrue(error.message.orEmpty().contains("usage: chrootctl"))
    }

    @Test
    fun `wrong data shape is not silently converted to an empty object`() {
        val raw = JSONObject()
            .put("protocolVersion", 1)
            .put("requestId", "shape-test")
            .put("ok", true)
            .put("data", "unexpected")
            .put("error", JSONObject.NULL)
            .put("warnings", JSONArray())
            .put("nextSteps", JSONArray())
            .toString()

        val error = assertThrows(IllegalStateException::class.java) {
            BridgeEnvelope.fromJson(raw).requireData()
        }

        assertTrue(error.message.orEmpty().contains("was string"))
        assertTrue(error.message.orEmpty().contains("expected a JSON object"))
    }



    @Test
    fun `array detail payload can be wrapped as checks for workspace detail`() {
        val raw = JSONObject()
            .put("protocolVersion", 1)
            .put("requestId", "shape-test")
            .put("ok", true)
            .put("data", JSONArray().put(JSONObject().put("title", "status ok").put("severity", "info")))
            .put("error", JSONObject.NULL)
            .put("warnings", JSONArray())
            .put("nextSteps", JSONArray())
            .toString()

        val wrapped = BridgeEnvelope.fromJson(raw).requireDataOrWrappedArray("checks", "system.status")

        assertEquals("array", wrapped.getJSONObject("bridgeShapeAdapter").getString("originalDataType"))
        assertEquals("status ok", wrapped.getJSONArray("checks").getJSONObject(0).getString("title"))
    }

    @Test
    fun `array lists can be read from object wrappers`() {
        val raw = JSONObject()
            .put("protocolVersion", 1)
            .put("requestId", "list-test")
            .put("ok", true)
            .put("data", JSONObject().put("services", JSONArray().put(JSONObject().put("service", "ssh"))))
            .put("error", JSONObject.NULL)
            .put("warnings", JSONArray())
            .put("nextSteps", JSONArray())
            .toString()

        val services = BridgeEnvelope.fromJson(raw).requireArrayFromData("services", "items")

        assertEquals("ssh", services.getJSONObject(0).getString("service"))
    }

    @Test
    fun `capabilities accept legacy string and structured operations`() {
        val capabilities = BridgeCapabilities.fromData(
            JSONObject()
                .put("protocolVersion", 1)
                .put("backendVersion", "test")
                .put("arbitraryShell", false)
                .put(
                    "operations",
                    JSONArray()
                        .put("system.dashboard")
                        .put(
                            JSONObject()
                                .put("name", "chroots.list")
                                .put("mode", "query")
                                .put("description", "List chroots")
                                .put("destructive", false)
                                .put("lockScope", "none"),
                        ),
                ),
        )

        assertEquals(listOf("system.dashboard", "chroots.list"), capabilities.operations)
        assertEquals("Legacy bridge capability", capabilities.operationCapabilities.first().description)
        assertFalse(capabilities.arbitraryShell)
    }
}
