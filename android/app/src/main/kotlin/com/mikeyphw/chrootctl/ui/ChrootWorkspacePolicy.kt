package com.mikeyphw.chrootctl.ui

import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.OperationSummary
import com.mikeyphw.chrootctl.model.ServiceUnitSummary
import com.mikeyphw.chrootctl.model.SnapshotSummary
import com.mikeyphw.chrootctl.model.UserSummary

enum class ChrootWorkspaceTab {
    Overview,
    Services,
    Users,
    Snapshots,
    Storage,
    Logs,
    Advanced,
}


enum class WorkspacePaneState {
    Loading,
    Empty,
    Ready,
    Failure,
}

fun workspacePaneState(
    refreshing: Boolean,
    errorMessage: String?,
    hasContent: Boolean,
): WorkspacePaneState = when {
    errorMessage != null && !hasContent -> WorkspacePaneState.Failure
    refreshing && !hasContent -> WorkspacePaneState.Loading
    !hasContent -> WorkspacePaneState.Empty
    else -> WorkspacePaneState.Ready
}

fun workspaceTabRequiredOperation(tab: ChrootWorkspaceTab): String? = when (tab) {
    ChrootWorkspaceTab.Overview, ChrootWorkspaceTab.Advanced -> null
    ChrootWorkspaceTab.Services -> "services.list"
    ChrootWorkspaceTab.Users -> "users.list"
    ChrootWorkspaceTab.Snapshots -> "snapshots.list"
    ChrootWorkspaceTab.Storage -> "storage.status"
    ChrootWorkspaceTab.Logs -> "logs.list"
}

fun workspaceTabSupported(tab: ChrootWorkspaceTab, availableOperations: Set<String>?): Boolean {
    val required = workspaceTabRequiredOperation(tab) ?: return true
    return availableOperations?.contains(required) == true
}

fun effectiveWorkspaceTab(selectedTab: ChrootWorkspaceTab, availableOperations: Set<String>?): ChrootWorkspaceTab =
    if (workspaceTabSupported(selectedTab, availableOperations)) selectedTab else ChrootWorkspaceTab.Overview

fun shouldPersistWorkspaceFallback(
    selectedTab: ChrootWorkspaceTab,
    effectiveTab: ChrootWorkspaceTab,
    capabilitiesKnown: Boolean,
): Boolean = capabilitiesKnown && selectedTab != effectiveTab

fun workspaceSelectionNeedsRebind(
    restoredWorkspaceName: String?,
    selectedWorkspaceName: String?,
    workspaceAvailable: Boolean,
): Boolean = workspaceAvailable &&
    !restoredWorkspaceName.isNullOrBlank() &&
    restoredWorkspaceName != selectedWorkspaceName

fun restoreWorkspaceNameOrNull(restoredWorkspaceName: String?, availableNames: Set<String>): String? {
    val restored = restoredWorkspaceName?.takeIf { it.isNotBlank() } ?: return null
    if (availableNames.isEmpty()) return restored
    return restored.takeIf { it in availableNames }
}

fun restoredWorkspaceUnavailable(restoredWorkspaceName: String?, availableNames: Set<String>): Boolean =
    availableNames.isNotEmpty() && !restoredWorkspaceName.isNullOrBlank() && restoredWorkspaceName !in availableNames

fun supportedChrootWorkspaceTabs(availableOperations: Set<String>?): List<ChrootWorkspaceTab> =
    chrootWorkspaceTabs().filter { workspaceTabSupported(it, availableOperations) }

object WorkspaceRestorationPolicy {
    val saveableStateKeys: Set<String> = setOf(
        "launcher-query",
        "launcher-filter",
        "workspace-name",
        "workspace-tab",
        "services-filter",
        "users-filter",
        "logs-filter",
        "logs-live-tail",
        "advanced-disclosure",
    )

    val transientMutationStateKeys: Set<String> = setOf(
        "snapshot-review",
        "snapshot-create-name",
        "snapshot-restore-confirmation",
        "user-review",
        "service-review",
        "remove-confirmation",
    )

    fun maySave(key: String): Boolean = key in saveableStateKeys && key !in transientMutationStateKeys
}


enum class ServiceWorkspaceFilter {
    All,
    Running,
    Enabled,
    Stale,
    Failed,
}

fun serviceWorkspaceFilters(): List<ServiceWorkspaceFilter> = ServiceWorkspaceFilter.entries

fun selectedServiceWorkspaceFilter(name: String): ServiceWorkspaceFilter = ServiceWorkspaceFilter.entries
    .firstOrNull { it.name == name }
    ?: ServiceWorkspaceFilter.All

fun serviceIsRunning(service: ServiceUnitSummary): Boolean {
    val normalized = service.status.trim().lowercase()
    return normalized in setOf("running", "active", "started", "ok")
}

fun serviceNeedsAttention(service: ServiceUnitSummary): Boolean {
    val status = service.status.trim().lowercase()
    val description = service.description.trim().lowercase()
    val attentionTokens = listOf("failed", "failure", "error", "stale", "degraded", "warning", "unhealthy", "missing")
    return attentionTokens.any { token -> token in status || token in description }
}

fun serviceMatchesWorkspaceFilter(service: ServiceUnitSummary, filter: ServiceWorkspaceFilter): Boolean = when (filter) {
    ServiceWorkspaceFilter.All -> true
    ServiceWorkspaceFilter.Running -> serviceIsRunning(service)
    ServiceWorkspaceFilter.Enabled -> service.enabled
    ServiceWorkspaceFilter.Stale -> serviceNeedsAttention(service)
    ServiceWorkspaceFilter.Failed -> {
        val status = service.status.trim().lowercase()
        val description = service.description.trim().lowercase()
        listOf("failed", "failure", "error").any { token -> token in status || token in description }
    }
}


enum class UserWorkspaceFilter {
    Managed,
    LoginUsers,
    SystemUsers,
}

enum class UserWorkspaceAction {
    Add,
    SyncUidGid,
    SetShell,
    ToggleSudo,
    SetPassword,
    Remove,
}

private const val SYSTEM_USER_UID_THRESHOLD = 1000

private val knownSystemUsernames = setOf(
    "bin",
    "daemon",
    "games",
    "gnats",
    "irc",
    "list",
    "lp",
    "mail",
    "man",
    "messagebus",
    "news",
    "nobody",
    "polkitd",
    "proxy",
    "sshd",
    "sync",
    "sys",
    "syslog",
    "systemd-network",
    "systemd-timesync",
    "tcpdump",
    "uucp",
    "uuidd",
    "www-data",
    "_apt",
)

fun userWorkspaceFilters(): List<UserWorkspaceFilter> = UserWorkspaceFilter.entries

fun selectedUserWorkspaceFilter(name: String): UserWorkspaceFilter = UserWorkspaceFilter.entries
    .firstOrNull { it.name == name }
    ?: UserWorkspaceFilter.Managed

fun userHasLoginShell(user: UserSummary): Boolean {
    val shell = user.shell.trim().lowercase()
    if (shell.isBlank()) return true
    return shell !in setOf("nologin", "false", "/usr/sbin/nologin", "/sbin/nologin", "/bin/false") &&
        !shell.endsWith("/nologin") &&
        !shell.endsWith("/false")
}

fun userIsKnownSystemAccount(user: UserSummary): Boolean = user.username.trim().lowercase() in knownSystemUsernames

fun userIsSystem(user: UserSummary): Boolean {
    if (user.system || user.protectedAccount) return true
    if (userIsKnownSystemAccount(user)) return true
    if (!userHasLoginShell(user)) return true
    val uid = user.uid.toIntOrNull()
    return uid != null && uid < SYSTEM_USER_UID_THRESHOLD
}

fun userIsManaged(user: UserSummary): Boolean = user.mutable && !userIsSystem(user)

fun userMatchesWorkspaceFilter(user: UserSummary, filter: UserWorkspaceFilter): Boolean = when (filter) {
    UserWorkspaceFilter.Managed -> userIsManaged(user)
    UserWorkspaceFilter.LoginUsers -> userHasLoginShell(user) && !userIsKnownSystemAccount(user)
    UserWorkspaceFilter.SystemUsers -> userIsSystem(user)
}

fun userWorkspaceActions(user: UserSummary?): List<UserWorkspaceAction> = when {
    user == null -> listOf(UserWorkspaceAction.Add)
    !user.mutable || user.protectedAccount || userIsSystem(user) -> emptyList()
    else -> listOf(
        UserWorkspaceAction.SetShell,
        UserWorkspaceAction.ToggleSudo,
        UserWorkspaceAction.SyncUidGid,
        UserWorkspaceAction.SetPassword,
        UserWorkspaceAction.Remove,
    )
}

enum class SnapshotWorkspaceAction {
    Create,
    Restore,
    Export,
}

enum class LogWorkspaceFilter {
    All,
    Warning,
    Error,
}

fun selectedLogWorkspaceFilter(name: String): LogWorkspaceFilter = LogWorkspaceFilter.entries
    .firstOrNull { it.name == name }
    ?: LogWorkspaceFilter.All

fun logWorkspaceBridgeLevel(filter: LogWorkspaceFilter): String? = when (filter) {
    LogWorkspaceFilter.All -> null
    LogWorkspaceFilter.Warning -> "WARNING"
    LogWorkspaceFilter.Error -> "ERROR"
}

private val snapshotRecoverableOperationKinds = setOf("chroots.upgrade", "install.run", "transfer.import")

fun operationNeedsSnapshotRecovery(operation: OperationSummary, chrootName: String): Boolean =
    operation.targetName == chrootName &&
        !operation.stale &&
        operation.kind in snapshotRecoverableOperationKinds &&
        operation.state.trim().lowercase() in setOf("failed", "interrupted")

fun matchingRecoverySnapshot(operation: OperationSummary, snapshots: List<SnapshotSummary>): SnapshotSummary? =
    snapshots.firstOrNull { snapshot ->
        snapshot.metadata["protected_operation_id"] == operation.operationId &&
            snapshot.metadata["protected_operation_kind"] == operation.kind
    }

fun defaultSnapshotName(nowMillis: Long = System.currentTimeMillis(), nonce: String = java.util.UUID.randomUUID().toString().take(8)): String =
    "snapshot-$nowMillis-$nonce"

fun snapshotPreviewMatches(
    action: SnapshotWorkspaceAction,
    snapshotName: String,
    previewAction: String?,
    previewSnapshot: String?,
): Boolean = snapshotName.isNotBlank() &&
    previewAction?.trim()?.lowercase() == action.name.lowercase() &&
    previewSnapshot == snapshotName

fun formatStorageBytes(bytes: Long): String {
    val safe = bytes.coerceAtLeast(0L)
    val kib = 1024L
    val mib = kib * 1024L
    val gib = mib * 1024L
    return when {
        safe >= gib -> "${safe / gib} GiB"
        safe >= mib -> "${safe / mib} MiB"
        safe >= kib -> "${safe / kib} KiB"
        else -> "$safe B"
    }
}

fun chrootWorkspaceTabs(): List<ChrootWorkspaceTab> = ChrootWorkspaceTab.entries

fun chrootWorkspaceTabId(tab: ChrootWorkspaceTab): String = when (tab) {
    ChrootWorkspaceTab.Overview -> "overview"
    ChrootWorkspaceTab.Services -> "services"
    ChrootWorkspaceTab.Users -> "users"
    ChrootWorkspaceTab.Snapshots -> "snapshots"
    ChrootWorkspaceTab.Storage -> "storage"
    ChrootWorkspaceTab.Logs -> "logs"
    ChrootWorkspaceTab.Advanced -> "advanced"
}

fun selectedChrootWorkspaceTab(name: String): ChrootWorkspaceTab = ChrootWorkspaceTab.entries
    .firstOrNull { it.name == name }
    ?: ChrootWorkspaceTab.Overview

fun chrootWorkspaceSummary(chroot: ChrootSummary): String = listOfNotNull(
    chroot.distribution,
    chroot.release,
    chroot.architecture,
    chroot.path,
).joinToString(" · ").ifBlank { chroot.status.ifBlank { "Status not reported" } }

fun bridgeShapePrimaryMessage(rawMessage: String): String {
    val message = rawMessage.lowercase()
    return when {
        "bridge response data was array" in message && "expected a json object" in message ->
            "The backend returned a list where this workspace expected detail data. The cached chroot data is safe."
        "bridge response data was object" in message && "expected a json array" in message ->
            "The backend returned detail data where this workspace expected a list. Retry after refresh."
        "bridge response data was" in message ->
            "The backend response shape was not supported by this workspace."
        else -> rawMessage
    }
}

fun isBridgeShapeError(rawMessage: String): Boolean {
    val message = rawMessage.lowercase()
    return "bridge response data was" in message && "expected a json" in message
}

fun chrootListIsWorkspaceLauncherOnly(): Boolean = true
