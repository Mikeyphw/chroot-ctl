package com.mikeyphw.chrootctl.root

import org.json.JSONObject

internal sealed interface BridgeOutputValidation {
    data class Accepted(val json: String) : BridgeOutputValidation
    data class Rejected(val code: String, val message: String) : BridgeOutputValidation
}

internal fun validateBridgeProcessResult(
    runtime: BridgeRuntime,
    result: BridgeProcessResult,
    expectedRequestId: String? = null,
): BridgeOutputValidation {
    if (result.timedOut) {
        return BridgeOutputValidation.Rejected("BRIDGE_TIMEOUT", "Bridge runtime ${runtime.executable} timed out")
    }
    if (result.truncated) {
        return BridgeOutputValidation.Rejected(
            "BRIDGE_RESPONSE_TRUNCATED",
            "Bridge runtime ${runtime.executable} exceeded the bounded transport capture; retry with a streaming/bounded query",
        )
    }
    val output = extractBridgeJsonEnvelope(result.output)
    if (output.isBlank()) {
        val stdoutDetail = bridgeOutputExcerpt(result.output)
        if (stdoutDetail.isNotBlank()) {
            return BridgeOutputValidation.Rejected(
                "INVALID_BRIDGE_RESPONSE",
                "Bridge runtime ${runtime.executable} returned non-JSON output: $stdoutDetail",
            )
        }
        val detail = bridgeOutputExcerpt(result.errorOutput)
        return BridgeOutputValidation.Rejected(
            "EMPTY_BRIDGE_RESPONSE",
            buildString {
                append("Bridge runtime ${runtime.executable} exited with code ${result.exitCode} without JSON output")
                if (detail.isNotBlank()) append(": $detail")
            },
        )
    }
    val envelope = runCatching { JSONObject(output) }.getOrNull()
        ?: return BridgeOutputValidation.Rejected("INVALID_BRIDGE_RESPONSE", "Bridge runtime ${runtime.executable} returned non-JSON output: ${bridgeOutputExcerpt(output)}")
    if (envelope.optInt("protocolVersion", -1) != BRIDGE_PROTOCOL_VERSION) {
        return BridgeOutputValidation.Rejected("UNSUPPORTED_BRIDGE_PROTOCOL", "Bridge runtime ${runtime.executable} does not support protocol $BRIDGE_PROTOCOL_VERSION")
    }
    if (!envelope.has("ok")) {
        return BridgeOutputValidation.Rejected("INVALID_BRIDGE_RESPONSE", "Bridge runtime ${runtime.executable} returned an envelope without an ok field")
    }
    if (!expectedRequestId.isNullOrBlank() && envelope.optString("requestId") != expectedRequestId) {
        return BridgeOutputValidation.Rejected(
            "BRIDGE_REQUEST_ID_MISMATCH",
            "Bridge response requestId ${envelope.optString("requestId")} did not match $expectedRequestId",
        )
    }
    return BridgeOutputValidation.Accepted(output)
}

internal fun bridgeOutputExcerpt(raw: String): String = raw.lineSequence().map(String::trim)
    .firstOrNull(String::isNotBlank).orEmpty().replace(Regex("\\s+"), " ").take(MAX_BRIDGE_ERROR_EXCERPT)

private const val BRIDGE_PROTOCOL_VERSION = 1
private const val MAX_BRIDGE_ERROR_EXCERPT = 240

private fun extractBridgeJsonEnvelope(raw: String): String {
    val trimmed = raw.trim()
    if (trimmed.startsWith("{") && trimmed.endsWith("}")) return trimmed
    return raw.lineSequence().map(String::trim).firstOrNull { it.startsWith("{") && it.endsWith("}") }.orEmpty()
}
