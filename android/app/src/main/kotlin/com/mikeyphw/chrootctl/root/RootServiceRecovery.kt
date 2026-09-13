package com.mikeyphw.chrootctl.root

internal enum class BinderReplayPolicy {
    SAFE_READ_ONLY,
    NEVER,
}

internal class RootServiceTransportException(
    message: String,
    cause: Throwable? = null,
) : IllegalStateException(message, cause)

internal suspend fun <T> executeWithBinderRecovery(
    label: String,
    replayPolicy: BinderReplayPolicy,
    attempt: suspend () -> T,
    recover: suspend (Throwable) -> Unit,
    isTransportFailure: (Throwable) -> Boolean,
    describeFailure: (Throwable) -> String = { error -> error.message ?: error.javaClass.simpleName },
): T {
    val firstFailure = try {
        return attempt()
    } catch (error: Throwable) {
        if (!isTransportFailure(error)) throw error
        error
    }

    recover(firstFailure)

    if (replayPolicy == BinderReplayPolicy.NEVER) {
        throw RootServiceTransportException(
            "$label was interrupted because the privileged service disconnected. " +
                "The request was not retried because replay could duplicate a state-changing operation. " +
                "${describeFailure(firstFailure)}",
            firstFailure,
        )
    }

    return try {
        attempt()
    } catch (secondFailure: Throwable) {
        if (isTransportFailure(secondFailure)) recover(secondFailure)
        throw RootServiceTransportException(
            "$label could not be completed after reconnecting to the privileged service. " +
                describeFailure(secondFailure),
            secondFailure,
        ).also { it.addSuppressed(firstFailure) }
    }
}
