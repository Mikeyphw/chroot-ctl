package com.mikeyphw.chrootctl.ui

import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.InstallDraft

enum class ChrootListFilter {
    All,
    Running,
    Stopped,
    Attention,
}

data class InstallDraftValidation(
    val distroValid: Boolean,
    val nameValid: Boolean,
    val usernameValid: Boolean,
    val archValid: Boolean,
) {
    val valid: Boolean get() = distroValid && nameValid && usernameValid && archValid
}

fun selectedChrootListFilter(name: String): ChrootListFilter = ChrootListFilter.entries
    .firstOrNull { it.name == name }
    ?: ChrootListFilter.All

fun chrootMatchesFilter(chroot: ChrootSummary, filter: ChrootListFilter): Boolean = when (filter) {
    ChrootListFilter.All -> true
    ChrootListFilter.Running -> isRunningChrootStatus(chroot.status) || chroot.mountState?.let(::isRunningChrootStatus) == true
    ChrootListFilter.Stopped -> !isRunningChrootStatus(chroot.status) && chroot.mountState?.let(::isRunningChrootStatus) != true
    ChrootListFilter.Attention -> chroot.warningCount > 0 || chroot.health?.contains("warn", ignoreCase = true) == true || chroot.health?.contains("fail", ignoreCase = true) == true
}

fun chrootMatchesQuery(chroot: ChrootSummary, query: String): Boolean {
    val needle = query.trim().lowercase()
    if (needle.isEmpty()) return true
    return listOfNotNull(
        chroot.name,
        chroot.distribution,
        chroot.release,
        chroot.architecture,
        chroot.path,
        chroot.status,
        chroot.mountState,
        chroot.health,
    ).any { needle in it.lowercase() }
}

fun validateInstallDraft(draft: InstallDraft): InstallDraftValidation = InstallDraftValidation(
    distroValid = draft.distro.trim().isNotEmpty(),
    nameValid = draft.name.matches(CHROOT_NAME_PATTERN),
    usernameValid = draft.username.matches(USERNAME_PATTERN),
    archValid = draft.arch in setOf("arm64", "amd64") && !(draft.distro == "arch" && draft.arch != "arm64"),
)

private val CHROOT_NAME_PATTERN = Regex("[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
private val USERNAME_PATTERN = Regex("[a-z_][a-z0-9_-]{0,31}")
