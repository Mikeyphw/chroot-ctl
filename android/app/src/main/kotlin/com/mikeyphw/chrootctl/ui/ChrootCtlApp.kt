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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.Loadable
import com.mikeyphw.chrootctl.model.approvesOperation
import com.mikeyphw.chrootctl.ui.activity.ActivityScreen
import com.mikeyphw.chrootctl.ui.chroots.ChrootsScreen
import com.mikeyphw.chrootctl.ui.components.AdaptiveNavigationShell
import com.mikeyphw.chrootctl.ui.components.PageHeader
import com.mikeyphw.chrootctl.ui.components.StatusTone
import com.mikeyphw.chrootctl.ui.home.HomeScreen
import com.mikeyphw.chrootctl.ui.install.InstallScreen
import com.mikeyphw.chrootctl.ui.tools.ToolsScreen
import org.json.JSONObject

@Composable
fun ChrootCtlApp(
    viewModel: MainViewModel,
    onStartRefreshOperation: () -> Unit,
    onStartBridgeOperation: (String, String) -> Unit,
    onPickImportArchive: () -> Unit,
    onCreateExportDocument: () -> Unit,
    onRequestNotificationPermission: () -> Unit,
    notificationsEnabled: Boolean,
    openOperationId: String? = null,
    openOperationNonce: Long = 0L,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var destinationName by rememberSaveable { mutableStateOf(AppDestination.Home.name) }
    var lastHandledSnapshotOperationId by rememberSaveable { mutableStateOf("") }
    var requestedChrootWorkspaceTabName by rememberSaveable { mutableStateOf("") }
    var requestedChrootWorkspaceTabNonce by rememberSaveable { mutableStateOf(0L) }
    val destination = AppDestination.entries.firstOrNull { it.name == destinationName } ?: AppDestination.Home
    val destinationStateHolder = rememberSaveableStateHolder()
    fun navigate(item: AppDestination) {
        destinationName = item.name
    }


    LaunchedEffect(uiState.operations) {
        val completed = uiState.operations.firstOrNull { operation ->
            operation.kind.startsWith("snapshots.") && operation.state == "succeeded" && operation.operationId != lastHandledSnapshotOperationId
        }
        completed?.let { operation ->
            operation.targetName?.takeIf(String::isNotBlank)?.let(viewModel::refreshSnapshots)
            if (operation.kind == "snapshots.export") {
                val exported = operation.resultJson
                    ?.let { runCatching { JSONObject(it) }.getOrNull() }
                    ?.optString("exported_archive")
                    .orEmpty()
                if (exported.isNotBlank()) {
                    viewModel.adoptSnapshotExport(exported)
                    onCreateExportDocument()
                }
            }
            lastHandledSnapshotOperationId = operation.operationId
        }
    }

    LaunchedEffect(openOperationId, openOperationNonce) {
        openOperationId?.takeIf(String::isNotBlank)?.let { operationId ->
            viewModel.selectOperation(operationId)
            viewModel.refreshSelectedOperation()
            navigate(AppDestination.Activity)
        }
    }

    ChrootCtlTheme {
        AdaptiveNavigationShell(
            destination = destination,
            onDestinationSelected = ::navigate,
        ) { shellModifier ->
            destinationStateHolder.SaveableStateProvider(destination.name) {
            AppContent(
                destination = destination,
                state = uiState,
                refresh = viewModel::refresh,
                startRefreshOperation = onStartRefreshOperation,
                openChroots = { navigate(AppDestination.Chroots) },
                openInstall = { navigate(AppDestination.Install) },
                openActivity = { navigate(AppDestination.Activity) },
                requestNotificationPermission = onRequestNotificationPermission,
                notificationsEnabled = notificationsEnabled,
                selectChroot = viewModel::selectChroot,
                refreshSelectedChroot = viewModel::refreshSelectedChroot,
                selectOperation = viewModel::selectOperation,
                refreshSelectedOperation = viewModel::refreshSelectedOperation,
                cancelOperation = viewModel::cancelOperation,
                retryOperation = { operationId -> onStartBridgeOperation("operations.retry", viewModel.retryOperationPayloadJson(operationId)) },
                retryOperationWithFixes = { operationId -> onStartBridgeOperation("operations.retry", viewModel.retryOperationPayloadJson(operationId, repair = true)) },
                recoverLatestSnapshot = { operationId ->
                    uiState.operations.firstOrNull { it.operationId == operationId }?.targetName?.let { target ->
                        viewModel.selectChroot(target)
                        viewModel.refreshSnapshots(target)
                        requestedChrootWorkspaceTabName = ChrootWorkspaceTab.Snapshots.name
                        requestedChrootWorkspaceTabNonce += 1L
                        navigate(AppDestination.Chroots)
                    }
                },
                requestedChrootWorkspaceTab = ChrootWorkspaceTab.entries.firstOrNull { it.name == requestedChrootWorkspaceTabName },
                requestedChrootWorkspaceTabNonce = requestedChrootWorkspaceTabNonce,
                updateInstallDraft = viewModel::updateInstallDraft,
                refreshInstallForm = viewModel::refreshInstallForm,
                previewInstall = viewModel::previewInstall,
                startInstall = {
                    val payload = viewModel.installPayloadJson()
                    viewModel.clearInstallPreview()
                    onStartBridgeOperation("install.run", payload)
                },
                previewLifecycle = viewModel::previewLifecycle,
                startLifecycle = { name, operation ->
                    val payload = viewModel.lifecyclePayloadJson(name, operation.substringAfterLast('.'))
                    viewModel.clearLifecyclePreview()
                    onStartBridgeOperation(operation, payload)
                },
                executeRemove = { name, confirmation ->
                    val payload = viewModel.removePayloadJson(name, confirmation)
                    viewModel.clearLifecyclePreview()
                    onStartBridgeOperation("chroots.remove.execute", payload)
                },
                refreshSnapshots = viewModel::refreshSnapshots,
                refreshStorage = viewModel::refreshStorage,
                refreshLogs = viewModel::refreshLogs,
                previewSnapshotCreate = viewModel::previewSnapshotCreate,
                startSnapshotCreate = { name, snapshot ->
                    val payload = viewModel.snapshotCreatePayloadJson(name, snapshot)
                    viewModel.clearSnapshotPreview()
                    onStartBridgeOperation("snapshots.create", payload)
                },
                previewSnapshotAction = viewModel::previewSnapshotAction,
                startSnapshotRestore = { name, snapshot, confirmation ->
                    val payload = viewModel.snapshotRestorePayloadJson(name, snapshot, confirmation)
                    viewModel.clearSnapshotPreview()
                    onStartBridgeOperation("snapshots.restore", payload)
                },
                startSnapshotExport = { name, snapshot ->
                    val payload = viewModel.snapshotExportPayloadJson(name, snapshot)
                    viewModel.clearSnapshotPreview()
                    onStartBridgeOperation("snapshots.export", payload)
                },
                refreshUsers = viewModel::refreshUsers,
                previewUserPayload = viewModel::previewUserAction,
                clearUserPreview = viewModel::clearUserPreview,
                startUserOperation = { operation, payload ->
                    val boundPayload = viewModel.userOperationPayloadJson(operation, payload)
                    viewModel.clearUserPreview()
                    onStartBridgeOperation(operation, boundPayload)
                },
                refreshServices = viewModel::refreshServices,
                refreshServiceDetail = viewModel::refreshServiceDetail,
                previewServicePayload = viewModel::previewServiceAction,
                clearServicePreview = viewModel::clearServicePreview,
                startServiceOperation = { operation, payload ->
                    val boundPayload = viewModel.serviceOperationPayloadJson(operation, payload)
                    viewModel.clearServicePreview()
                    onStartBridgeOperation(operation, boundPayload)
                },
                refreshCatalog = viewModel::refreshCatalog,
                setCatalogTarget = viewModel::setCatalogTarget,
                setCatalogQuery = viewModel::setCatalogQuery,
                setCatalogCategory = viewModel::setCatalogCategory,
                toggleCatalogEntry = viewModel::toggleCatalogEntry,
                previewCatalogApply = viewModel::previewCatalogApply,
                startCatalogApply = {
                    val payload = viewModel.catalogApplyPayloadJson()
                    viewModel.clearCatalogPreview()
                    onStartBridgeOperation("catalog.apply", payload)
                },
                refreshPackageInventory = viewModel::refreshPackageInventory,
                updatePackageCompare = viewModel::updatePackageCompare,
                comparePackages = viewModel::comparePackages,
                updateTransferImportArchive = viewModel::updateTransferImportArchive,
                updateTransferImportTarget = viewModel::updateTransferImportTarget,
                updateTransferImportPassword = viewModel::updateTransferImportPassword,
                updateTransferExportTarget = viewModel::updateTransferExportTarget,
                updateTransferExportArchive = viewModel::updateTransferExportArchive,
                inspectTransferImport = viewModel::inspectTransferImport,
                previewTransferExport = viewModel::previewTransferExport,
                refreshTransferArtifacts = viewModel::refreshTransferArtifacts,
                startTransferImport = {
                    val payload = viewModel.transferImportPayloadJson()
                    viewModel.clearTransferImportSecretsAfterDispatch()
                    onStartBridgeOperation("transfer.import", payload)
                },
                startTransferExport = {
                    val payload = viewModel.transferExportPayloadJson()
                    viewModel.clearTransferExportPreview()
                    onStartBridgeOperation("transfer.export", payload)
                },
                cleanupAllArtifacts = {
                    if (uiState.transferPane.artifactCleanupPreview.approvesOperation("artifacts.cleanup")) {
                        val payload = viewModel.artifactCleanupPayloadJson(deleteAll = true)
                        viewModel.clearArtifactCleanupPreview()
                        onStartBridgeOperation("artifacts.cleanup", payload)
                    } else {
                        viewModel.previewArtifactCleanup(deleteAll = true)
                    }
                },
                pickImportArchive = onPickImportArchive,
                createExportDocument = onCreateExportDocument,
                refreshSystemSupport = viewModel::refreshSystemSupport,
                previewSupportBundle = viewModel::previewSupportBundle,
                startSupportBundle = { onStartBridgeOperation("support.bundle", viewModel.supportBundlePayloadJson()) },
                previewModuleBuild = viewModel::previewModuleBuild,
                startModuleBuild = { onStartBridgeOperation("system.module_build", viewModel.moduleBuildPayloadJson()) },
                previewRepair = viewModel::previewRepair,
                toggleRepairItem = viewModel::toggleRepairItem,
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
    notificationsEnabled: Boolean,
    selectChroot: (String) -> Unit,
    refreshSelectedChroot: () -> Unit,
    selectOperation: (String) -> Unit,
    refreshSelectedOperation: () -> Unit,
    cancelOperation: (String) -> Unit,
    retryOperation: (String) -> Unit,
    retryOperationWithFixes: (String) -> Unit,
    recoverLatestSnapshot: (String) -> Unit,
    requestedChrootWorkspaceTab: ChrootWorkspaceTab?,
    requestedChrootWorkspaceTabNonce: Long,
    updateInstallDraft: (com.mikeyphw.chrootctl.model.InstallDraft) -> Unit,
    refreshInstallForm: () -> Unit,
    previewInstall: () -> Unit,
    startInstall: () -> Unit,
    previewLifecycle: (String, String) -> Unit,
    startLifecycle: (String, String) -> Unit,
    executeRemove: (String, String) -> Unit,
    refreshSnapshots: (String) -> Unit,
    refreshStorage: (String) -> Unit,
    refreshLogs: (String, String?) -> Unit,
    previewSnapshotCreate: (String, String) -> Unit,
    startSnapshotCreate: (String, String) -> Unit,
    previewSnapshotAction: (String, String, String) -> Unit,
    startSnapshotRestore: (String, String, String) -> Unit,
    startSnapshotExport: (String, String) -> Unit,
    refreshUsers: (String) -> Unit,
    previewUserPayload: (String) -> Unit,
    clearUserPreview: () -> Unit,
    startUserOperation: (String, String) -> Unit,
    refreshServices: (String) -> Unit,
    refreshServiceDetail: (String, String) -> Unit,
    previewServicePayload: (String) -> Unit,
    clearServicePreview: () -> Unit,
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
    updateTransferImportPassword: (String) -> Unit,
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
    toggleRepairItem: (String) -> Unit,
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
    val currentPaneTitle = stringResource(destination.labelRes)
    Box(modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .widthIn(max = ChrootLayout.MaximumContentWidth)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .semantics { paneTitle = currentPaneTitle }
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
            val headerTone = if (destination == AppDestination.Home) {
                when {
                    state.refreshState is RefreshState.Failed -> StatusTone.Warning
                    state.refreshState is RefreshState.Refreshing -> StatusTone.Accent
                    homeReady -> StatusTone.Success
                    else -> StatusTone.Neutral
                }
            } else {
                StatusTone.Neutral
            }
            PageHeader(
                title = currentPaneTitle,
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
                    notificationsEnabled = notificationsEnabled,
                )
                AppDestination.Chroots -> ChrootsScreen(
                    chroots = state.chroots,
                    operations = state.operations,
                    capabilities = when (val home = state.home) {
                        is Loadable.Ready -> home.value.capabilities
                        else -> null
                    },
                    selectedName = state.selectedChrootName,
                    detail = state.chrootDetail,
                    lifecyclePreview = state.lifecyclePreview,
                    snapshotPane = state.snapshotPane,
                    storagePane = state.storagePane,
                    logsPane = state.logsPane,
                    usersPane = state.usersPane,
                    servicesPane = state.servicesPane,
                    systemSupportPane = state.systemSupportPane,
                    requestedWorkspaceTab = requestedChrootWorkspaceTab,
                    requestedWorkspaceTabNonce = requestedChrootWorkspaceTabNonce,
                    onSelect = selectChroot,
                    onRefreshDetail = refreshSelectedChroot,
                    onPreviewLifecycle = previewLifecycle,
                    onStartLifecycle = startLifecycle,
                    onExecuteRemove = executeRemove,
                    onRefreshSnapshots = refreshSnapshots,
                    onRefreshStorage = refreshStorage,
                    onRefreshLogs = refreshLogs,
                    onPreviewSnapshotCreate = previewSnapshotCreate,
                    onStartSnapshotCreate = startSnapshotCreate,
                    onPreviewSnapshotAction = previewSnapshotAction,
                    onStartSnapshotRestore = startSnapshotRestore,
                    onStartSnapshotExport = startSnapshotExport,
                    onRefreshUsers = refreshUsers,
                    onPreviewUserPayload = previewUserPayload,
                    onClearUserPreview = clearUserPreview,
                    onStartUserOperation = startUserOperation,
                    onRefreshServices = refreshServices,
                    onRefreshServiceDetail = refreshServiceDetail,
                    onPreviewServicePayload = previewServicePayload,
                    onClearServicePreview = clearServicePreview,
                    onStartServiceOperation = startServiceOperation,
                    onRefreshSystemSupport = refreshSystemSupport,
                    onPreviewSupportBundle = previewSupportBundle,
                    onStartSupportBundle = startSupportBundle,
                    onPreviewRepair = previewRepair,
                    onToggleRepairItem = toggleRepairItem,
                    onStartRepair = startRepair,
                )
                AppDestination.Install -> InstallScreen(
                    draft = state.installDraft,
                    form = state.installForm,
                    preview = state.installPreview,
                    onDraftChange = updateInstallDraft,
                    onRefreshForm = refreshInstallForm,
                    onPreview = previewInstall,
                    onStartInstall = startInstall,
                    onOpenActivity = openActivity,
                )
                AppDestination.Activity -> ActivityScreen(
                    operations = state.operations,
                    selectedOperationId = state.selectedOperationId,
                    detail = state.operationDetail,
                    onSelect = selectOperation,
                    onRefreshDetail = refreshSelectedOperation,
                    onCancelOperation = cancelOperation,
                    onRetryOperation = retryOperation,
                    onRetryWithFixes = retryOperationWithFixes,
                    onRecoverLatestSnapshot = recoverLatestSnapshot,
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
                    onUpdateTransferImportPassword = updateTransferImportPassword,
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
                    onToggleRepairItem = toggleRepairItem,
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
