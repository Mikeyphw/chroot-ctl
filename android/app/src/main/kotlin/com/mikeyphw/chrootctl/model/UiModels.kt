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
    val releaseReadiness: ReleaseReadinessSummary,
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

data class ReleaseReadinessSummary(
    val title: String,
    val body: String,
    val rows: List<ReadinessRow>,
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
    val resultJson: String? = null,
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
    val username: String = "",
    val arch: String = "arm64",
    val preset: String = "minimal-server",
    val profile: String = "minimal",
    val desktop: String = "none",
    val release: String = "",
    val version: String = "",
    val mirror: String = "auto",
    val resume: Boolean = false,
    val repair: Boolean = false,
    val overwriteExisting: Boolean = false,
)

data class InstallFormSummary(
    val distros: List<String> = emptyList(),
    val architectures: List<String> = emptyList(),
    val presets: List<String> = emptyList(),
    val profiles: List<String> = emptyList(),
    val desktops: List<String> = emptyList(),
    val mirrors: List<String> = emptyList(),
    val defaultName: String = "ubuntu",
    val defaultUsername: String = "",
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
    val previewId: String = "",
    val payloadHash: String = "",
    val resourceRevision: String = "",
    val actionOperation: String = "",
    val expiresAt: Double = 0.0,
)

fun PreviewSummary?.approvesOperation(operation: String): Boolean =
    this?.ok == true &&
        actionOperation == operation &&
        previewId.isNotBlank() &&
        payloadHash.isNotBlank() &&
        resourceRevision.isNotBlank()

data class SnapshotSummary(
    val name: String,
    val chrootName: String,
    val kind: String,
    val path: String,
    val createdAt: String,
    val note: String,
    val sizeBytes: Long,
    val metadata: Map<String, String> = emptyMap(),
)

data class SnapshotPane(
    val targetName: String? = null,
    val snapshots: List<SnapshotSummary> = emptyList(),
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
    val preview: PreviewSummary? = null,
    val previewAction: String? = null,
    val previewSnapshot: String? = null,
)

data class StorageSummary(
    val name: String,
    val rootfsPath: String,
    val rootfsExists: Boolean,
    val rootfsBytes: Long,
    val cachePath: String,
    val cacheExists: Boolean,
    val cacheBytes: Long,
    val freeBytes: Long,
    val usedBytes: Long,
    val totalBytes: Long,
    val mountState: String,
    val mountedCount: Int,
    val mountCount: Int,
    val snapshotDirectory: String,
)

data class StoragePane(
    val targetName: String? = null,
    val summary: StorageSummary? = null,
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
)

data class ChrootLogEntrySummary(
    val line: String,
    val level: String,
)

data class LogsPane(
    val targetName: String? = null,
    val logFile: String = "",
    val level: String = "",
    val entries: List<ChrootLogEntrySummary> = emptyList(),
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
)

data class UserSummary(
    val username: String,
    val uid: String,
    val gid: String,
    val home: String,
    val shell: String,
    val sudo: Boolean,
    val sudoRule: Boolean = false,
    val sudoGroup: Boolean = false,
    val protectedAccount: Boolean = false,
    val system: Boolean = false,
    val login: Boolean = true,
    val mutable: Boolean = true,
    val policyReasons: List<String> = emptyList(),
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

data class CatalogEntrySummary(
    val kind: String,
    val name: String,
    val description: String,
    val distros: List<String>,
    val categories: List<String>,
    val risks: List<String> = emptyList(),
    val rollback: String = "manual",
    val riskLevel: String = "low",
    val source: String = "builtin",
    val state: String = "available",
    val stateReason: String = "ready",
    val scriptSha256: String = "",
    val destructive: Boolean = false,
    val requiresConfirmation: Boolean = false,
    val installed: Boolean = false,
    val failed: Boolean = false,
    val selected: Boolean = false,
)

data class CatalogPane(
    val targetName: String? = null,
    val kind: String = "tool",
    val query: String = "",
    val category: String = "",
    val entries: List<CatalogEntrySummary> = emptyList(),
    val categories: List<String> = emptyList(),
    val preview: PreviewSummary? = null,
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
)

data class PackageInventorySummary(
    val name: String,
    val count: Int,
    val packages: List<String>,
    val truncated: Boolean,
    val limit: Int = 0,
)

data class PackageCompareSummary(
    val left: String,
    val right: String,
    val leftCount: Int,
    val rightCount: Int,
    val commonCount: Int,
    val onlyLeft: List<String>,
    val onlyRight: List<String>,
)

data class PackagePane(
    val leftName: String = "",
    val rightName: String = "",
    val inventory: PackageInventorySummary? = null,
    val comparison: PackageCompareSummary? = null,
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
)

data class TransferArtifactSummary(
    val artifactId: String,
    val name: String,
    val path: String,
    val kind: String,
    val sizeBytes: Long,
    val modifiedAt: String,
    val expiresAt: String,
)

data class TransferPane(
    val importArchive: String = "",
    val importTargetName: String = "",
    val importPassword: String = "",
    val exportTargetName: String = "",
    val exportArchive: String = "",
    val conflict: String = "rename",
    val artifacts: List<TransferArtifactSummary> = emptyList(),
    val importInspection: PreviewSummary? = null,
    val exportPreview: PreviewSummary? = null,
    val artifactCleanupPreview: PreviewSummary? = null,
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
)


data class SystemRowSummary(
    val label: String,
    val value: String,
    val state: String,
)

data class RepairItemSummary(
    val itemId: String,
    val name: String,
    val kind: String,
    val severity: String,
    val action: String,
    val summary: String,
    val impact: String,
)

data class SystemSupportPane(
    val runtimeRows: List<SystemRowSummary> = emptyList(),
    val moduleRows: List<SystemRowSummary> = emptyList(),
    val supportPreview: PreviewSummary? = null,
    val moduleBuildPreview: PreviewSummary? = null,
    val repairPreview: PreviewSummary? = null,
    val repairItems: List<RepairItemSummary> = emptyList(),
    val selectedRepairItemIds: Set<String> = emptySet(),
    val cleanupPreview: PreviewSummary? = null,
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
)

data class DebugProbeSummary(
    val group: String,
    val code: String,
    val status: String,
    val detail: String,
    val next: String,
)

data class DebugTimelineSummary(
    val eventType: String,
    val target: String,
    val result: String,
    val message: String,
)

data class DebugPane(
    val selectedGroup: String = "all",
    val probes: List<DebugProbeSummary> = emptyList(),
    val timeline: List<DebugTimelineSummary> = emptyList(),
    val smokePlan: PreviewSummary? = null,
    val smokeReport: PreviewSummary? = null,
    val smokeLastResult: PreviewSummary? = null,
    val refreshing: Boolean = false,
    val errorMessage: String? = null,
)
