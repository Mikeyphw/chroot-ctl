package com.mikeyphw.chrootctl.ui

import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mikeyphw.chrootctl.ui.activity.ActivityScreen
import com.mikeyphw.chrootctl.ui.chroots.ChrootsScreen
import com.mikeyphw.chrootctl.ui.home.HomeScreen
import com.mikeyphw.chrootctl.ui.install.InstallScreen
import com.mikeyphw.chrootctl.ui.tools.ToolsScreen

@Composable
fun ChrootCtlApp(
    viewModel: MainViewModel,
    onStartRefreshOperation: () -> Unit,
    onStartBridgeOperation: (String, String) -> Unit,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var destination by remember { mutableStateOf(AppDestination.Home) }

    ChrootCtlTheme {
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val wide = maxWidth >= 720.dp
            if (wide) {
                Row(Modifier.fillMaxSize()) {
                    NavigationRail {
                        AppDestination.entries.forEach { item ->
                            NavigationRailItem(
                                selected = item == destination,
                                onClick = { destination = item },
                                icon = { Text(stringResource(item.glyphRes)) },
                                label = { Text(stringResource(item.labelRes)) },
                            )
                        }
                    }
                    AppContent(
                        destination = destination,
                        state = uiState,
                        refresh = viewModel::refresh,
                        startRefreshOperation = onStartRefreshOperation,
                        openInstall = { destination = AppDestination.Install },
                        openActivity = { destination = AppDestination.Activity },
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
                        modifier = Modifier.weight(1f),
                    )
                }
            } else {
                Scaffold(
                    bottomBar = {
                        NavigationBar {
                            AppDestination.entries.forEach { item ->
                                NavigationBarItem(
                                    selected = item == destination,
                                    onClick = { destination = item },
                                    icon = { Text(stringResource(item.glyphRes)) },
                                    label = { Text(stringResource(item.labelRes)) },
                                )
                            }
                        }
                    },
                ) { padding ->
                    AppContent(
                        destination = destination,
                        state = uiState,
                        refresh = viewModel::refresh,
                        startRefreshOperation = onStartRefreshOperation,
                        openInstall = { destination = AppDestination.Install },
                        openActivity = { destination = AppDestination.Activity },
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
                        modifier = Modifier.padding(padding),
                    )
                }
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
    openInstall: () -> Unit,
    openActivity: () -> Unit,
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
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
    ) {
        Text(stringResource(destination.labelRes), style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.height(16.dp))
        when (destination) {
            AppDestination.Home -> HomeScreen(
                state = state.home,
                refreshState = state.refreshState,
                onRefresh = refresh,
                onStartRefreshOperation = startRefreshOperation,
                onOpenActivity = openActivity,
            )
            AppDestination.Chroots -> ChrootsScreen(
                chroots = state.chroots,
                selectedName = state.selectedChrootName,
                detail = state.chrootDetail,
                lifecyclePreview = state.lifecyclePreview,
                snapshotPane = state.snapshotPane,
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
            AppDestination.Tools -> ToolsScreen(state.toolGroups, onOpenInstall = openInstall)
        }
    }
}
