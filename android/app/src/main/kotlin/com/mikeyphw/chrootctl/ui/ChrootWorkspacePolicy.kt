package com.mikeyphw.chrootctl.ui

import com.mikeyphw.chrootctl.model.ChrootSummary

enum class ChrootWorkspaceTab {
    Overview,
    Services,
    Users,
    Snapshots,
    Advanced,
}

fun chrootWorkspaceTabs(): List<ChrootWorkspaceTab> = ChrootWorkspaceTab.entries

fun chrootWorkspaceTabId(tab: ChrootWorkspaceTab): String = when (tab) {
    ChrootWorkspaceTab.Overview -> "overview"
    ChrootWorkspaceTab.Services -> "services"
    ChrootWorkspaceTab.Users -> "users"
    ChrootWorkspaceTab.Snapshots -> "snapshots"
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
