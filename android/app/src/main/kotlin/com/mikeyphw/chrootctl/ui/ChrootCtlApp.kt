package com.mikeyphw.chrootctl.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.Loadable
import com.mikeyphw.chrootctl.ui.activity.ActivityScreen
import com.mikeyphw.chrootctl.ui.chroots.ChrootsScreen
import com.mikeyphw.chrootctl.ui.components.AdaptiveNavigationShell
import com.mikeyphw.chrootctl.ui.components.PageHeader
import com.mikeyphw.chrootctl.ui.components.StatusTone
import com.mikeyphw.chrootctl.ui.home.HomeScreen
import com.mikeyphw.chrootctl.ui.install.InstallScreen
import com.mikeyphw.chrootctl.ui.tools.ToolsScreen

@Composable
fun ChrootCtlApp(
    viewModel: MainViewModel,
    onStartRefreshOperation: () -> Unit,
    onStartBridgeOperation: (String, String) -> Unit,
    onPickImportArchive: () -> Unit,
    onCreateExportDocument: () -> Unit,
    onRequestNotificationPermission: () -> Unit,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var destinationName by rememberSaveable { mutableStateOf(AppDestination.Home.name) }
    val destination = AppDestination.entries.firstOrNull { it.name == destinationName } ?: AppDestination.Home
    fun navigate(item: AppDestination) {
        destinationName = item.name
    }

    ChrootCtlTheme {
        AdaptiveNavigationShell(
            destination = destination,
            onDestinationSelected = ::navigate,
        ) { shellModifier ->
            AppContent(
                destination = destination,
                state = uiState,
                refresh = viewModel::refresh,
                startRefreshOperation = onStartRefreshOperation,
                openChroots = { navigate(AppDestination.Chroots) },
                openInstall = { navigate(AppDestination.Install) },
                openActivity = { navigate(AppDestination.Activity) },
                requestNotificationPermission = onRequestNotificationPermission,
                selectChroot = viewModel::selectChroot,
                refreshSelectedChroot = viewModel::refreshSelectedChroot,
                selectOperation = viewModel::selectOperation,
                refreshSelectedOperation = viewModel::refreshSelectedOperation,
                updateInstallDraft = viewModel::updateInstallDraft,
                refreshInstallForm = viewModel::refreshInstallForm,
                previewInstall = viewModel::previewInstall,
                startInstall = { onStartBridgeOperation("install.run", viewModel.installPayloadJson()) },
                previewLifecycle = viewModel::previewLifecycle,
                startLifecycle = { name, operation -> onStartBridgeOperation(operation, viewModel.lifecyclePayloadJson(name, operation.substringAfterLast('.'))) },
                executeRemove = { name, confirmation -> onStartBridgeOperation("chroots.remove.execute", viewModel.removePayloadJson(name, confirmation)) },
                refreshSnapshots = viewModel::refreshSnapshots,
                previewSnapshotCreate = viewModel::previewSnapshotCreate,
                startSnapshotCreate = { name -> onStartBridgeOperation("snapshots.create", viewModel.snapshotCreatePayloadJson(name)) },
                previewSnapshotAction = viewModel::previewSnapshotAction,
                startSnapshotRestore = { name, snapshot, confirmation -> onStartBridgeOperation("snapshots.restore", viewModel.snapshotRestorePayloadJson(name, snapshot, confirmation)) },
                startSnapshotExport = { name, snapshot -> onStartBridgeOperation("snapshots.export", viewModel.snapshotExportPayloadJson(name, snapshot)) },
                refreshUsers = viewModel::refreshUsers,
                previewUserPayload = viewModel::previewUserAction,
                startUserOperation = onStartBridgeOperation,
                refreshServices = viewModel::refreshServices,
                refreshServiceDetail = viewModel::refreshServiceDetail,
                previewServicePayload = viewModel::previewServiceAction,
                startServiceOperation = onStartBridgeOperation,
                refreshCatalog = viewModel::refreshCatalog,
                setCatalogTarget = viewModel::setCatalogTarget,
                setCatalogQuery = viewModel::setCatalogQuery,
                setCatalogCategory = viewModel::setCatalogCategory,
                toggleCatalogEntry = viewModel::toggleCatalogEntry,
                previewCatalogApply = viewModel::previewCatalogApply,
                startCatalogApply = { onStartBridgeOperation("catalog.apply", viewModel.catalogApplyPayloadJson()) },
                refreshPackageInventory = viewModel::refreshPackageInventory,
                updatePackageCompare = viewModel::updatePackageCompare,
                comparePackages = viewModel::comparePackages,
                updateTransferImportArchive = viewModel::updateTransferImportArchive,
                updateTransferImportTarget = viewModel::updateTransferImportTarget,
                updateTransferExportTarget = viewModel::updateTransferExportTarget,
                updateTransferExportArchive = viewModel::updateTransferExportArchive,
                inspectTransferImport = viewModel::inspectTransferImport,
                previewTransferExport = viewModel::previewTransferExport,
                refreshTransferArtifacts = viewModel::refreshTransferArtifacts,
                startTransferImport = { onStartBridgeOperation("transfer.import", viewModel.transferImportPayloadJson()) },
                startTransferExport = { onStartBridgeOperation("transfer.export", viewModel.transferExportPayloadJson()) },
                cleanupAllArtifacts = { onStartBridgeOperation("artifacts.cleanup", viewModel.artifactCleanupPayloadJson(deleteAll = true)) },
                pickImportArchive = onPickImportArchive,
                createExportDocument = onCreateExportDocument,
                refreshSystemSupport = viewModel::refreshSystemSupport,
                previewSupportBundle = viewModel::previewSupportBundle,
                startSupportBundle = { onStartBridgeOperation("support.bundle", viewModel.supportBundlePayloadJson()) },
                previewModuleBuild = viewModel::previewModuleBuild,
                startModuleBuild = { onStartBridgeOperation("system.module_build", viewModel.moduleBuildPayloadJson()) },
                previewRepair = viewModel::previewRepair,
                startRepair = { onStartBridgeOperation("repair.apply", viewModel.repairApplyPayloadJson()) },
                previewTempCleanup = viewModel::previewTempCleanup,
                startTempCleanup = { onStartBridgeOperation("cleanup.temp", viewModel.cleanupTempPayloadJson()) },
                refreshDebugWorkbench = viewModel::refreshDebugWorkbench,
                startDebugExport = { onStartBridgeOperation("debug.export", viewModel.debugExportPayloadJson()) },
                previewSmokePlan = viewModel::previewSmokePlan,
                startSmokeRun = { onStartBridgeOperation("smoke.run", viewModel.smokeRunPayloadJson()) },
                refreshSmokeReport = viewModel::refreshSmokeReport,
                refreshSmokeLastResult = viewModel::refreshSmokeLastResult,
                persistSmokeResult = { onStartBridgeOperation("smoke.result.persist", viewModel.smokeResultPersistPayloadJson()) },
                exportSmokeEvidence = { onStartBridgeOperation("smoke.result.export", viewModel.smokeResultExportPayloadJson()) },
                createSmokeFailureBundle = { onStartBridgeOperation("smoke.failure.bundle", viewModel.smokeFailureBundlePayloadJson()) },
                modifier = shellModifier,
            )
        }
    }
}

@Composable
private fun AppContent(
    destination: AppDestination,
    state: MainUiState,
    refresh: () -> Unit,
    startRefreshOperation: () -> Unit,
    openChroots: () -> Unit,
    openInstall: () -> Unit,
    openActivity: () -> Unit,
    requestNotificationPermission: () -> Unit,
    selectChroot: (String) -> Unit,
    refreshSelectedChroot: () -> Unit,
    selectOperation: (String) -> Unit,
    refreshSelectedOperation: () -> Unit,
    updateInstallDraft: (com.mikeyphw.chrootctl.model.InstallDraft) -> Unit,
    refreshInstallForm: () -> Unit,
    previewInstall: () -> Unit,
    startInstall: () -> Unit,
    previewLifecycle: (String, String) -> Unit,
    startLifecycle: (String, String) -> Unit,
    executeRemove: (String, String) -> Unit,
    refreshSnapshots: (String) -> Unit,
    previewSnapshotCreate: (String) -> Unit,
    startSnapshotCreate: (String) -> Unit,
    previewSnapshotAction: (String, String, String) -> Unit,
    startSnapshotRestore: (String, String, String) -> Unit,
    startSnapshotExport: (String, String) -> Unit,
    refreshUsers: (String) -> Unit,
    previewUserPayload: (String) -> Unit,
    startUserOperation: (String, String) -> Unit,
    refreshServices: (String) -> Unit,
    refreshServiceDetail: (String, String) -> Unit,
    previewServicePayload: (String) -> Unit,
    startServiceOperation: (String, String) -> Unit,
    refreshCatalog: (String) -> Unit,
    setCatalogTarget: (String) -> Unit,
    setCatalogQuery: (String) -> Unit,
    setCatalogCategory: (String) -> Unit,
    toggleCatalogEntry: (String) -> Unit,
    previewCatalogApply: () -> Unit,
    startCatalogApply: () -> Unit,
    refreshPackageInventory: (String) -> Unit,
    updatePackageCompare: (String, String) -> Unit,
    comparePackages: () -> Unit,
    updateTransferImportArchive: (String) -> Unit,
    updateTransferImportTarget: (String) -> Unit,
    updateTransferExportTarget: (String) -> Unit,
    updateTransferExportArchive: (String) -> Unit,
    inspectTransferImport: () -> Unit,
    previewTransferExport: () -> Unit,
    refreshTransferArtifacts: () -> Unit,
    startTransferImport: () -> Unit,
    startTransferExport: () -> Unit,
    cleanupAllArtifacts: () -> Unit,
    pickImportArchive: () -> Unit,
    createExportDocument: () -> Unit,
    refreshSystemSupport: () -> Unit,
    previewSupportBundle: () -> Unit,
    startSupportBundle: () -> Unit,
    previewModuleBuild: () -> Unit,
    startModuleBuild: () -> Unit,
    previewRepair: () -> Unit,
    startRepair: () -> Unit,
    previewTempCleanup: () -> Unit,
    startTempCleanup: () -> Unit,
    refreshDebugWorkbench: (String) -> Unit,
    startDebugExport: () -> Unit,
    previewSmokePlan: () -> Unit,
    startSmokeRun: () -> Unit,
    refreshSmokeReport: () -> Unit,
    refreshSmokeLastResult: () -> Unit,
    persistSmokeResult: () -> Unit,
    exportSmokeEvidence: () -> Unit,
    createSmokeFailureBundle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .widthIn(max = ChrootLayout.MaximumContentWidth)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = ChrootSpacing.lg, vertical = ChrootSpacing.lg),
            verticalArrangement = Arrangement.spacedBy(ChrootSpacing.md),
        ) {
            val homeReady = state.home is Loadable.Ready<*>
            val headerStatus = if (destination == AppDestination.Home) {
                when (state.refreshState) {
                    is RefreshState.Refreshing -> stringResource(R.string.status_refreshing)
                    is RefreshState.Failed -> stringResource(R.string.status_cached_or_offline)
                    else -> if (homeReady) stringResource(R.string.status_backend_ready) else stringResource(R.string.status_checking)
                }
            } else {
                null
            }
            val headerTone = when {
                state.refreshState is RefreshState.Failed -> StatusTone.Warning
                state.refreshState is RefreshState.Refreshing -> StatusTone.Accent
                homeReady -> StatusTone.Success
                else -> StatusTone.Neutral
            }
            PageHeader(
                title = stringResource(destination.labelRes),
                subtitle = stringResource(destination.subtitleRes),
                statusLabel = headerStatus,
                statusTone = headerTone,
            )
            when (destination) {
                AppDestination.Home -> HomeScreen(
                    state = state.home,
                    chroots = state.chroots,
                    operations = state.operations,
                    refreshState = state.refreshState,
                    onRefresh = refresh,
                    onStartRefreshOperation = startRefreshOperation,
                    onOpenChroots = openChroots,
                    onOpenInstall = openInstall,
                    onOpenActivity = openActivity,
                    onRequestNotificationPermission = requestNotificationPermission,
                )
                AppDestination.Chroots -> ChrootsScreen(
                    chroots = state.chroots,
                    selectedName = state.selectedChrootName,
                    detail = state.chrootDetail,
                    lifecyclePreview = state.lifecyclePreview,
                    snapshotPane = state.snapshotPane,
                    usersPane = state.usersPane,
                    servicesPane = state.servicesPane,
                    onSelect = selectChroot,
                    onRefreshDetail = refreshSelectedChroot,
                    onPreviewLifecycle = previewLifecycle,
                    onStartLifecycle = startLifecycle,
                    onExecuteRemove = executeRemove,
                    onRefreshSnapshots = refreshSnapshots,
                    onPreviewSnapshotCreate = previewSnapshotCreate,
                    onStartSnapshotCreate = startSnapshotCreate,
                    onPreviewSnapshotAction = previewSnapshotAction,
                    onStartSnapshotRestore = startSnapshotRestore,
                    onStartSnapshotExport = startSnapshotExport,
                    onRefreshUsers = refreshUsers,
                    onPreviewUserPayload = previewUserPayload,
                    onStartUserOperation = startUserOperation,
                    onRefreshServices = refreshServices,
                    onRefreshServiceDetail = refreshServiceDetail,
                    onPreviewServicePayload = previewServicePayload,
                    onStartServiceOperation = startServiceOperation,
                )
                AppDestination.Install -> InstallScreen(
                    draft = state.installDraft,
                    form = state.installForm,
                    preview = state.installPreview,
                    onDraftChange = updateInstallDraft,
                    onRefreshForm = refreshInstallForm,
                    onPreview = previewInstall,
                    onStartInstall = startInstall,
                )
                AppDestination.Activity -> ActivityScreen(
                    operations = state.operations,
                    selectedOperationId = state.selectedOperationId,
                    detail = state.operationDetail,
                    onSelect = selectOperation,
                    onRefreshDetail = refreshSelectedOperation,
                )
                AppDestination.Tools -> ToolsScreen(
                    groups = state.toolGroups,
                    chroots = state.chroots,
                    catalogPane = state.catalogPane,
                    packagePane = state.packagePane,
                    transferPane = state.transferPane,
                    systemSupportPane = state.systemSupportPane,
                    debugPane = state.debugPane,
                    onOpenInstall = openInstall,
                    onRefreshCatalog = refreshCatalog,
                    onSetCatalogTarget = setCatalogTarget,
                    onSetCatalogQuery = setCatalogQuery,
                    onSetCatalogCategory = setCatalogCategory,
                    onToggleCatalogEntry = toggleCatalogEntry,
                    onPreviewCatalogApply = previewCatalogApply,
                    onStartCatalogApply = startCatalogApply,
                    onRefreshPackageInventory = refreshPackageInventory,
                    onUpdatePackageCompare = updatePackageCompare,
                    onComparePackages = comparePackages,
                    onUpdateTransferImportArchive = updateTransferImportArchive,
                    onUpdateTransferImportTarget = updateTransferImportTarget,
                    onUpdateTransferExportTarget = updateTransferExportTarget,
                    onUpdateTransferExportArchive = updateTransferExportArchive,
                    onInspectTransferImport = inspectTransferImport,
                    onPreviewTransferExport = previewTransferExport,
                    onRefreshTransferArtifacts = refreshTransferArtifacts,
                    onStartTransferImport = startTransferImport,
                    onStartTransferExport = startTransferExport,
                    onCleanupAllArtifacts = cleanupAllArtifacts,
                    onPickImportArchive = pickImportArchive,
                    onCreateExportDocument = createExportDocument,
                    onRefreshSystemSupport = refreshSystemSupport,
                    onPreviewSupportBundle = previewSupportBundle,
                    onStartSupportBundle = startSupportBundle,
                    onPreviewModuleBuild = previewModuleBuild,
                    onStartModuleBuild = startModuleBuild,
                    onPreviewRepair = previewRepair,
                    onStartRepair = startRepair,
                    onPreviewTempCleanup = previewTempCleanup,
                    onStartTempCleanup = startTempCleanup,
                    onRefreshDebugWorkbench = refreshDebugWorkbench,
                    onStartDebugExport = startDebugExport,
                    onPreviewSmokePlan = previewSmokePlan,
                    onStartSmokeRun = startSmokeRun,
                    onRefreshSmokeReport = refreshSmokeReport,
                    onRefreshSmokeLastResult = refreshSmokeLastResult,
                    onPersistSmokeResult = persistSmokeResult,
                    onExportSmokeEvidence = exportSmokeEvidence,
                    onCreateSmokeFailureBundle = createSmokeFailureBundle,
                )
            }
        }
    }
}
