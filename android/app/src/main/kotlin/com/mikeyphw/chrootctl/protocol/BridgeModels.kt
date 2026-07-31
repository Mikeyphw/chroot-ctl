package com.mikeyphw.chrootctl.protocol

import org.json.JSONArray
import org.json.JSONObject

data class RootBridgeInfo(
    val ok: Boolean,
    val uid: Int,
    val gid: Int,
    val pid: Int,
    val backend: String,
    val executable: String?,
    val message: String,
) {
    companion object {
        fun fromJson(raw: String): RootBridgeInfo {
            val json = JSONObject(raw)
            return RootBridgeInfo(
                ok = json.optBoolean("ok"),
                uid = json.optInt("uid", -1),
                gid = json.optInt("gid", -1),
                pid = json.optInt("pid", -1),
                backend = json.optString("backend", "unavailable"),
                executable = json.optString("executable").takeIf(String::isNotBlank),
                message = json.optString("message", "Root bridge did not provide a status message"),
            )
        }
    }
}

data class BridgeCapabilities(
    val protocolVersion: Int,
    val backendVersion: String,
    val operations: List<String>,
    val arbitraryShell: Boolean,
) {
    companion object {
        fun fromEnvelope(raw: String): BridgeCapabilities {
            val envelope = JSONObject(raw)
            check(envelope.optBoolean("ok")) {
                envelope.optJSONObject("error")?.optString("message") ?: "Capability query failed"
            }
            val data = envelope.getJSONObject("data")
            val operationsJson = data.optJSONArray("operations") ?: JSONArray()
            val operations = buildList {
                for (index in 0 until operationsJson.length()) {
                    add(operationsJson.getJSONObject(index).getString("name"))
                }
            }
            return BridgeCapabilities(
                protocolVersion = data.optInt("protocolVersion", -1),
                backendVersion = data.optString("backendVersion", "unknown"),
                operations = operations,
                arbitraryShell = data.optBoolean("arbitraryShell", true),
            )
        }
    }
}
