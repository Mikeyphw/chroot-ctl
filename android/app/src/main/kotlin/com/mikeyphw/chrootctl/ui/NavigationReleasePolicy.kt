package com.mikeyphw.chrootctl.ui

enum class DeepLinkDecision {
    Ignore,
    WaitForSnapshot,
    Open,
}

object NavigationReleasePolicy {
    const val maxBackStackDepth: Int = 32

    fun sanitizeDestinationStack(stack: List<String>): List<String> {
        val sanitized = stack.mapNotNull { name ->
            AppDestination.entries.firstOrNull { it.name == name }?.name
        }.fold(emptyList<String>()) { acc, name ->
            if (acc.lastOrNull() == name) acc else acc + name
        }.takeLast(maxBackStackDepth)
        return sanitized.ifEmpty { listOf(AppDestination.Home.name) }
    }

    fun pushDestinationStack(stack: List<String>, destination: AppDestination): List<String> {
        val sanitized = sanitizeDestinationStack(stack)
        if (sanitized.lastOrNull() == destination.name) return sanitized
        return (sanitized + destination.name).takeLast(maxBackStackDepth)
    }

    fun popDestinationStack(stack: List<String>): List<String> {
        val sanitized = sanitizeDestinationStack(stack)
        return if (sanitized.size <= 1) sanitized else sanitized.dropLast(1)
    }

    fun deepLinkDecision(operationId: String?, availableOperationIds: Set<String>): DeepLinkDecision {
        val wanted = operationId?.trim().orEmpty()
        if (wanted.isBlank()) return DeepLinkDecision.Ignore
        return if (wanted in availableOperationIds) DeepLinkDecision.Open else DeepLinkDecision.WaitForSnapshot
    }
}
