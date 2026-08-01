package com.mikeyphw.chrootctl.model

import com.mikeyphw.chrootctl.protocol.BridgeCapabilities
import com.mikeyphw.chrootctl.protocol.RootBridgeInfo

sealed interface Loadable<out T> {
    data object Loading : Loadable<Nothing>
    data class Ready<T>(val value: T) : Loadable<T>
    data class Blocked(val message: String, val cached: Boolean = false) : Loadable<Nothing>
}

data class HomeSnapshot(
    val bridgeInfo: RootBridgeInfo,
    val capabilities: BridgeCapabilities,
    val chrootCount: Int,
    val operationCount: Int,
    val warningCount: Int,
    val readinessRows: List<ReadinessRow>,
    val recommendedAction: RecommendedAction,
    val refreshedAt: Long,
    val stale: Boolean,
)

data class ReadinessRow(
    val label: String,
    val detail: String,
    val state: ReadinessState,
)

enum class ReadinessState { Ready, Warning, Blocked }

data class RecommendedAction(
    val title: String,
    val body: String,
    val actionLabel: String,
)

data class ChrootSummary(
    val name: String,
    val distribution: String?,
    val release: String?,
    val architecture: String?,
    val path: String?,
    val status: String,
    val mountState: String?,
    val health: String?,
    val warningCount: Int,
    val rawJson: String,
    val lastRefreshAt: Long,
    val stale: Boolean,
)

data class CheckSummary(
    val checkId: String,
    val title: String,
    val message: String,
    val severity: String,
)

data class ChrootDetail(
    val chroot: ChrootSummary?,
    val checks: List<CheckSummary>,
    val refreshing: Boolean,
    val errorMessage: String?,
)

data class OperationSummary(
    val operationId: String,
    val kind: String,
    val title: String,
    val state: String,
    val targetName: String?,
    val phase: String?,
    val progressPercent: Int?,
    val progressText: String,
    val errorCode: String?,
    val errorMessage: String?,
    val createdAt: Long,
    val stale: Boolean,
)

data class OperationEventSummary(
    val id: Long,
    val type: String,
    val timestamp: Long,
    val message: String,
    val payloadJson: String,
)

data class OperationDetail(
    val operation: OperationSummary?,
    val events: List<OperationEventSummary>,
    val refreshing: Boolean,
    val errorMessage: String?,
)

data class ToolCapabilityGroup(
    val title: String,
    val operations: List<String>,
)

data class InstallDraft(
    val distro: String = "ubuntu",
    val name: String = "ubuntu",
    val username: String = "mike",
    val preset: String = "minimal-server",
    val profile: String = "minimal",
    val desktop: String = "none",
    val release: String = "",
    val version: String = "",
    val mirror: String = "auto",
)

data class InstallFormSummary(
    val distros: List<String> = emptyList(),
    val presets: List<String> = emptyList(),
    val profiles: List<String> = emptyList(),
    val desktops: List<String> = emptyList(),
    val mirrors: List<String> = emptyList(),
    val defaultName: String = "ubuntu",
    val defaultUsername: String = "mike",
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
)

data class PreviewSummary(
    val title: String,
    val ok: Boolean,
    val body: String,
    val blocking: List<String>,
    val warnings: List<String>,
    val rawJson: String,
)

data class SnapshotSummary(
    val name: String,
    val chrootName: String,
    val kind: String,
    val path: String,
    val createdAt: String,
    val note: String,
    val sizeBytes: Long,
)

data class SnapshotPane(
    val targetName: String? = null,
    val snapshots: List<SnapshotSummary> = emptyList(),
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
    val preview: PreviewSummary? = null,
)

data class UserSummary(
    val username: String,
    val uid: String,
    val gid: String,
    val home: String,
    val shell: String,
    val sudo: Boolean,
)

data class UsersPane(
    val targetName: String? = null,
    val users: List<UserSummary> = emptyList(),
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
    val preview: PreviewSummary? = null,
)

data class ServiceUnitSummary(
    val service: String,
    val chrootName: String,
    val status: String,
    val enabled: Boolean,
    val boot: Boolean,
    val description: String,
    val journalText: String = "",
)

data class ServicesPane(
    val targetName: String? = null,
    val services: List<ServiceUnitSummary> = emptyList(),
    val selectedService: ServiceUnitSummary? = null,
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
    val preview: PreviewSummary? = null,
)
