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
    val responseKind: String = "object",
    val responseFields: List<String> = emptyList(),
    val capabilityTags: List<String> = emptyList(),
    val requiresPreview: Boolean = false,
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
                    .put("responseKind", capability.responseKind)
                    .put("responseFields", JSONArray(capability.responseFields))
                    .put("capabilityTags", JSONArray(capability.capabilityTags))
                    .put("requiresPreview", capability.requiresPreview)
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
                    when (val item = operationsJson.opt(index)) {
                        is JSONObject -> add(
                            BridgeOperationCapability(
                                name = item.optString("name", "unknown"),
                                mode = item.optString("mode", "query"),
                                description = item.optString("description", ""),
                                destructive = item.optBoolean("destructive", false),
                                lockScope = item.optString("lockScope", "none"),
                                responseKind = item.optString("responseKind", "object"),
                                responseFields = item.optJSONArray("responseFields").toStringList(),
                                capabilityTags = item.optJSONArray("capabilityTags").toStringList(),
                                requiresPreview = item.optBoolean("requiresPreview", false),
                            ),
                        )
                        is String -> add(
                            BridgeOperationCapability(
                                name = item,
                                mode = "query",
                                description = "Legacy bridge capability",
                                destructive = false,
                                lockScope = "none",
                                responseKind = "object",
                                responseFields = emptyList(),
                                capabilityTags = listOf("legacy"),
                                requiresPreview = false,
                            ),
                        )
                    }
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
    val dataType: String?,
    val errorCode: String?,
    val errorMessage: String?,
    val errorDetails: JSONObject?,
    val warnings: List<String>,
    val nextSteps: List<String>,
) {
    fun requireData(): JSONObject {
        check(ok) { errorMessage ?: errorCode ?: "Bridge request failed" }
        return data ?: error("Bridge response data was ${dataType ?: "missing"}; expected a JSON object")
    }

    fun requireArray(): JSONArray {
        check(ok) { errorMessage ?: errorCode ?: "Bridge request failed" }
        return dataArray ?: error("Bridge response data was ${dataType ?: "missing"}; expected a JSON array")
    }

    fun requireDataOrWrappedArray(arrayKey: String, sourceLabel: String): JSONObject {
        check(ok) { errorMessage ?: errorCode ?: "Bridge request failed" }
        data?.let { return it }
        dataArray?.let { array ->
            return JSONObject()
                .put(arrayKey, array)
                .put("bridgeShapeAdapter", JSONObject()
                    .put("source", sourceLabel)
                    .put("originalDataType", "array"))
        }
        return error("Bridge response data was ${dataType ?: "missing"}; expected a JSON object")
    }

    fun requireArrayFromData(vararg objectKeys: String): JSONArray {
        check(ok) { errorMessage ?: errorCode ?: "Bridge request failed" }
        dataArray?.let { return it }
        data?.let { obj ->
            for (key in objectKeys) {
                obj.optJSONArray(key)?.let { return it }
            }
        }
        return error("Bridge response data was ${dataType ?: "missing"}; expected a JSON array")
    }

    companion object {
        fun fromJson(raw: String): BridgeEnvelope {
            val json = runCatching { JSONObject(raw.trim()) }.getOrElse { error ->
                throw IllegalStateException(
                    "Bridge returned non-JSON output: ${bridgeJsonExcerpt(raw)}",
                    error,
                )
            }
            val error = json.optJSONObject("error")
            val rawData = json.opt("data")
            return BridgeEnvelope(
                protocolVersion = json.optInt("protocolVersion", -1),
                requestId = json.optString("requestId", "unknown"),
                ok = json.optBoolean("ok"),
                data = rawData as? JSONObject,
                dataArray = rawData as? JSONArray,
                dataType = rawData.bridgeJsonType(),
                errorCode = error?.optString("code")?.takeIf(String::isNotBlank),
                errorMessage = error?.optString("message")?.takeIf(String::isNotBlank),
                errorDetails = error?.optJSONObject("details"),
                warnings = json.optJSONArray("warnings").toStringList(),
                nextSteps = json.optJSONArray("nextSteps").toStringList(),
            )
        }
    }
}

private fun Any?.bridgeJsonType(): String? = when (this) {
    null, JSONObject.NULL -> null
    is JSONObject -> "object"
    is JSONArray -> "array"
    is String -> "string"
    is Number -> "number"
    is Boolean -> "boolean"
    else -> javaClass.simpleName
}

private fun bridgeJsonExcerpt(raw: String): String = raw
    .lineSequence()
    .map(String::trim)
    .firstOrNull(String::isNotBlank)
    .orEmpty()
    .replace(Regex("\\s+"), " ")
    .take(240)

fun JSONArray?.toStringList(): List<String> {
    if (this == null) return emptyList()
    return buildList {
        for (index in 0 until length()) {
            add(optString(index))
        }
    }
}
