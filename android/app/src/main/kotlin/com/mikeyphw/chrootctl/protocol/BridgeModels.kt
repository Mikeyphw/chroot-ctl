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
    fun toJson(): String = JSONObject()
        .put("ok", ok)
        .put("uid", uid)
        .put("gid", gid)
        .put("pid", pid)
        .put("backend", backend)
        .put("executable", executable ?: JSONObject.NULL)
        .put("message", message)
        .toString()

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

data class BridgeOperationCapability(
    val name: String,
    val mode: String,
    val description: String,
    val destructive: Boolean,
    val lockScope: String,
)

data class BridgeCapabilities(
    val protocolVersion: Int,
    val backendVersion: String,
    val operations: List<String>,
    val operationCapabilities: List<BridgeOperationCapability>,
    val arbitraryShell: Boolean,
) {
    fun toJson(): String = JSONObject()
        .put("protocolVersion", protocolVersion)
        .put("backendVersion", backendVersion)
        .put(
            "operations",
            JSONArray(operationCapabilities.map { capability ->
                JSONObject()
                    .put("name", capability.name)
                    .put("mode", capability.mode)
                    .put("description", capability.description)
                    .put("destructive", capability.destructive)
                    .put("lockScope", capability.lockScope)
            }),
        )
        .put("arbitraryShell", arbitraryShell)
        .toString()

    companion object {
        fun fromEnvelope(raw: String): BridgeCapabilities = fromData(BridgeEnvelope.fromJson(raw).requireData())

        fun fromData(data: JSONObject): BridgeCapabilities {
            val operationsJson = data.optJSONArray("operations") ?: JSONArray()
            val capabilities = buildList {
                for (index in 0 until operationsJson.length()) {
                    val item = operationsJson.getJSONObject(index)
                    add(
                        BridgeOperationCapability(
                            name = item.optString("name", "unknown"),
                            mode = item.optString("mode", "query"),
                            description = item.optString("description", ""),
                            destructive = item.optBoolean("destructive", false),
                            lockScope = item.optString("lockScope", "none"),
                        ),
                    )
                }
            }
            return BridgeCapabilities(
                protocolVersion = data.optInt("protocolVersion", -1),
                backendVersion = data.optString("backendVersion", "unknown"),
                operations = capabilities.map { capability -> capability.name },
                operationCapabilities = capabilities,
                arbitraryShell = data.optBoolean("arbitraryShell", true),
            )
        }
    }
}

data class BridgeEnvelope(
    val protocolVersion: Int,
    val requestId: String,
    val ok: Boolean,
    val data: JSONObject?,
    val dataArray: JSONArray?,
    val errorCode: String?,
    val errorMessage: String?,
    val warnings: List<String>,
    val nextSteps: List<String>,
) {
    fun requireData(): JSONObject {
        check(ok) { errorMessage ?: errorCode ?: "Bridge request failed" }
        return data ?: JSONObject()
    }

    fun requireArray(): JSONArray {
        check(ok) { errorMessage ?: errorCode ?: "Bridge request failed" }
        return dataArray ?: JSONArray()
    }

    companion object {
        fun fromJson(raw: String): BridgeEnvelope {
            val json = JSONObject(raw)
            val error = json.optJSONObject("error")
            val rawData = json.opt("data")
            return BridgeEnvelope(
                protocolVersion = json.optInt("protocolVersion", -1),
                requestId = json.optString("requestId", "unknown"),
                ok = json.optBoolean("ok"),
                data = rawData as? JSONObject,
                dataArray = rawData as? JSONArray,
                errorCode = error?.optString("code")?.takeIf(String::isNotBlank),
                errorMessage = error?.optString("message")?.takeIf(String::isNotBlank),
                warnings = json.optJSONArray("warnings").toStringList(),
                nextSteps = json.optJSONArray("nextSteps").toStringList(),
            )
        }
    }
}

fun JSONArray?.toStringList(): List<String> {
    if (this == null) return emptyList()
    return buildList {
        for (index in 0 until length()) {
            add(optString(index))
        }
    }
}
