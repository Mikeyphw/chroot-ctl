package com.mikeyphw.chrootctl.protocol

import org.json.JSONObject
import java.util.UUID

const val BRIDGE_PROTOCOL_VERSION = 1

data class BridgeRequest(
    val operation: String,
    val payload: JSONObject = JSONObject(),
    val requestId: String = UUID.randomUUID().toString(),
) {
    init {
        require(operation.matches(Regex("^[a-z][a-z0-9_.-]{1,80}$"))) { "Invalid bridge operation" }
        require(requestId.length in 1..128) { "Invalid request identifier" }
    }

    fun toJson(): String = JSONObject()
        .put("protocolVersion", BRIDGE_PROTOCOL_VERSION)
        .put("requestId", requestId)
        .put("operation", operation)
        .put("payload", payload)
        .toString()
}
