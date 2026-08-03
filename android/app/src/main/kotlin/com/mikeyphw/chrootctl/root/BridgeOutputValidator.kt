package com.mikeyphw.chrootctl.root

import org.json.JSONObject

internal sealed interface BridgeOutputValidation {
    data class Accepted(val json: String) : BridgeOutputValidation
    data class Rejected(val code: String, val message: String) : BridgeOutputValidation
}

internal fun validateBridgeProcessResult(
    runtime: BridgeRuntime,
    result: BridgeProcessResult,
): BridgeOutputValidation {
    if (result.timedOut) {
        return BridgeOutputValidation.Rejected(
            code = "BRIDGE_TIMEOUT",
            message = "Bridge runtime ${runtime.executable} timed out",
        )
    }
    val output = result.output.trim()
    if (output.isBlank()) {
        val detail = bridgeOutputExcerpt(result.errorOutput)
        return BridgeOutputValidation.Rejected(
            code = "EMPTY_BRIDGE_RESPONSE",
            message = buildString {
                append("Bridge runtime ${runtime.executable} exited with code ${result.exitCode} without JSON output")
                if (detail.isNotBlank()) append(": $detail")
            },
        )
    }
    val envelope = runCatching { JSONObject(output) }.getOrNull()
        ?: return BridgeOutputValidation.Rejected(
            code = "INVALID_BRIDGE_RESPONSE",
            message = "Bridge runtime ${runtime.executable} returned non-JSON output: ${bridgeOutputExcerpt(output)}",
        )
    if (envelope.optInt("protocolVersion", -1) != BRIDGE_PROTOCOL_VERSION) {
        return BridgeOutputValidation.Rejected(
            code = "UNSUPPORTED_BRIDGE_PROTOCOL",
            message = "Bridge runtime ${runtime.executable} does not support protocol $BRIDGE_PROTOCOL_VERSION",
        )
    }
    if (!envelope.has("ok")) {
        return BridgeOutputValidation.Rejected(
            code = "INVALID_BRIDGE_RESPONSE",
            message = "Bridge runtime ${runtime.executable} returned an envelope without an ok field",
        )
    }
    return BridgeOutputValidation.Accepted(output)
}

internal fun bridgeOutputExcerpt(raw: String): String = raw
    .lineSequence()
    .map(String::trim)
    .firstOrNull(String::isNotBlank)
    .orEmpty()
    .replace(Regex("\\s+"), " ")
    .take(MAX_BRIDGE_ERROR_EXCERPT)

private const val BRIDGE_PROTOCOL_VERSION = 1
private const val MAX_BRIDGE_ERROR_EXCERPT = 240
