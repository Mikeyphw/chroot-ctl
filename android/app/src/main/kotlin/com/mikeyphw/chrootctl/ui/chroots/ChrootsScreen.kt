package com.mikeyphw.chrootctl.ui.chroots

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.CheckSummary
import com.mikeyphw.chrootctl.model.ChrootDetail
import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.LogsPane
import com.mikeyphw.chrootctl.model.OperationSummary
import com.mikeyphw.chrootctl.model.PreviewSummary
import com.mikeyphw.chrootctl.model.approvesOperation
import com.mikeyphw.chrootctl.model.SnapshotPane
import com.mikeyphw.chrootctl.model.SnapshotSummary
import com.mikeyphw.chrootctl.model.StoragePane
import com.mikeyphw.chrootctl.model.SystemSupportPane
import com.mikeyphw.chrootctl.model.ServiceUnitSummary
import com.mikeyphw.chrootctl.model.ServicesPane
import com.mikeyphw.chrootctl.model.UserSummary
import com.mikeyphw.chrootctl.model.UsersPane
import com.mikeyphw.chrootctl.ui.ChrootLayout
import com.mikeyphw.chrootctl.ui.ChrootListFilter
import com.mikeyphw.chrootctl.ui.ChrootWorkspaceTab
import com.mikeyphw.chrootctl.ui.LogWorkspaceFilter
import com.mikeyphw.chrootctl.ui.SnapshotWorkspaceAction
import com.mikeyphw.chrootctl.ui.ServiceWorkspaceFilter
import com.mikeyphw.chrootctl.ui.UserWorkspaceAction
import com.mikeyphw.chrootctl.ui.WorkspacePaneState
import com.mikeyphw.chrootctl.ui.UserWorkspaceFilter
import com.mikeyphw.chrootctl.ui.bridgeShapePrimaryMessage
import com.mikeyphw.chrootctl.ui.effectiveWorkspaceTab
import com.mikeyphw.chrootctl.ui.chrootListIsWorkspaceLauncherOnly
import com.mikeyphw.chrootctl.ui.chrootMatchesFilter
import com.mikeyphw.chrootctl.ui.chrootMatchesQuery
import com.mikeyphw.chrootctl.ui.chrootWorkspaceSummary
import com.mikeyphw.chrootctl.ui.chrootWorkspaceTabs
import com.mikeyphw.chrootctl.ui.isBridgeShapeError
import com.mikeyphw.chrootctl.ui.isRunningChrootStatus
import com.mikeyphw.chrootctl.ui.formatStorageBytes
import com.mikeyphw.chrootctl.ui.logWorkspaceBridgeLevel
import com.mikeyphw.chrootctl.ui.defaultSnapshotName
import com.mikeyphw.chrootctl.ui.matchingRecoverySnapshot
import com.mikeyphw.chrootctl.ui.operationNeedsSnapshotRecovery
import com.mikeyphw.chrootctl.ui.selectedChrootListFilter
import com.mikeyphw.chrootctl.ui.restoreWorkspaceNameOrNull
import com.mikeyphw.chrootctl.ui.selectedChrootWorkspaceTab
import com.mikeyphw.chrootctl.ui.selectedLogWorkspaceFilter
import com.mikeyphw.chrootctl.ui.selectedServiceWorkspaceFilter
import com.mikeyphw.chrootctl.ui.snapshotPreviewMatches
import com.mikeyphw.chrootctl.ui.serviceIsRunning
import com.mikeyphw.chrootctl.ui.serviceMatchesWorkspaceFilter
import com.mikeyphw.chrootctl.ui.serviceNeedsAttention
import com.mikeyphw.chrootctl.ui.serviceWorkspaceFilters
import com.mikeyphw.chrootctl.ui.selectedUserWorkspaceFilter
import com.mikeyphw.chrootctl.ui.userHasLoginShell
import com.mikeyphw.chrootctl.ui.userIsSystem
import com.mikeyphw.chrootctl.ui.userMatchesWorkspaceFilter
import com.mikeyphw.chrootctl.ui.userWorkspaceActions
import com.mikeyphw.chrootctl.ui.userWorkspaceFilters
import com.mikeyphw.chrootctl.ui.workspacePaneState
import com.mikeyphw.chrootctl.ui.workspaceSelectionNeedsRebind
import com.mikeyphw.chrootctl.ui.shouldPersistWorkspaceFallback
import com.mikeyphw.chrootctl.ui.workspaceTabSupported
import com.mikeyphw.chrootctl.ui.components.ActionFlowRow
import com.mikeyphw.chrootctl.ui.components.EmptyState
import com.mikeyphw.chrootctl.ui.components.LoadingState
import com.mikeyphw.chrootctl.ui.components.MetricCardData
import com.mikeyphw.chrootctl.ui.components.PathText
import com.mikeyphw.chrootctl.ui.components.ResponsiveMetricCards
import com.mikeyphw.chrootctl.ui.components.releaseSelectionSemantics
import com.mikeyphw.chrootctl.ui.components.SectionHeader
import com.mikeyphw.chrootctl.ui.components.StatusCard
import com.mikeyphw.chrootctl.ui.components.StatusPill
import com.mikeyphw.chrootctl.ui.components.StatusTone
import com.mikeyphw.chrootctl.protocol.BridgeCapabilities
import kotlinx.coroutines.delay
import org.json.JSONObject

@Composable
fun ChrootsScreen(
    chroots: List<ChrootSummary>,
    operations: List<OperationSummary>,
    capabilities: BridgeCapabilities?,
    selectedName: String?,
    detail: ChrootDetail,
    lifecyclePreview: PreviewSummary?,
    snapshotPane: SnapshotPane,
    storagePane: StoragePane,
    logsPane: LogsPane,
    usersPane: UsersPane,
    servicesPane: ServicesPane,
    systemSupportPane: SystemSupportPane,
    requestedWorkspaceTab: ChrootWorkspaceTab? = null,
    requestedWorkspaceTabNonce: Long = 0L,
    onSelect: (String) -> Unit,
    onRefreshDetail: () -> Unit,
    onPreviewLifecycle: (String, String) -> Unit,
    onStartLifecycle: (String, String) -> Unit,
    onExecuteRemove: (String, String) -> Unit,
    onRefreshSnapshots: (String) -> Unit,
    onRefreshStorage: (String) -> Unit,
    onRefreshLogs: (String, String?) -> Unit,
    onPreviewSnapshotCreate: (String, String) -> Unit,
    onStartSnapshotCreate: (String, String) -> Unit,
    onPreviewSnapshotAction: (String, String, String) -> Unit,
    onStartSnapshotRestore: (String, String, String) -> Unit,
    onStartSnapshotExport: (String, String) -> Unit,
    onRefreshUsers: (String) -> Unit,
    onPreviewUserPayload: (String) -> Unit,
    onClearUserPreview: () -> Unit,
    onStartUserOperation: (String, String) -> Unit,
    onRefreshServices: (String) -> Unit,
    onRefreshServiceDetail: (String, String) -> Unit,
    onPreviewServicePayload: (String) -> Unit,
    onClearServicePreview: () -> Unit,
    onStartServiceOperation: (String, String) -> Unit,
    onRefreshSystemSupport: () -> Unit,
    onPreviewSupportBundle: () -> Unit,
    onStartSupportBundle: () -> Unit,
    onPreviewRepair: () -> Unit,
    onToggleRepairItem: (String) -> Unit,
    onStartRepair: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var filterName by rememberSaveable { mutableStateOf(ChrootListFilter.All.name) }
    var workspaceName by rememberSaveable { mutableStateOf(selectedName) }
    var workspaceTabName by rememberSaveable { mutableStateOf(ChrootWorkspaceTab.Overview.name) }
    var requestedWorkspaceSelection by remember { mutableStateOf(selectedName) }
    val filter = selectedChrootListFilter(filterName)
    val workspaceTab = selectedChrootWorkspaceTab(workspaceTabName)
    val availableWorkspaceNames = chroots.map { it.name }.toSet()
    LaunchedEffect(requestedWorkspaceTab, requestedWorkspaceTabNonce) {
        requestedWorkspaceTab?.let { workspaceTabName = it.name }
    }
    val visibleChroots = chroots.filter { chroot ->
        chrootMatchesQuery(chroot, query) && chrootMatchesFilter(chroot, filter)
    }
    LaunchedEffect(workspaceName, availableWorkspaceNames) {
        val restored = restoreWorkspaceNameOrNull(workspaceName, availableWorkspaceNames)
        if (restored != workspaceName) workspaceName = restored
    }
    val workspaceChroot = workspaceName?.let { wanted ->
        detail.chroot?.takeIf { it.name == wanted } ?: chroots.firstOrNull { it.name == wanted }
    }
    LaunchedEffect(workspaceName, workspaceChroot?.name, selectedName, requestedWorkspaceSelection) {
        val restoredName = workspaceName
        if (workspaceSelectionNeedsRebind(restoredName, selectedName, workspaceChroot != null) && requestedWorkspaceSelection != restoredName) {
            requestedWorkspaceSelection = restoredName
            onSelect(checkNotNull(restoredName))
        } else if (restoredName != null && selectedName == restoredName) {
            requestedWorkspaceSelection = restoredName
        }
    }

    if (workspaceName != null && workspaceChroot != null) {
        ChrootWorkspaceScreen(
            chroot = workspaceChroot,
            operations = operations,
            capabilities = capabilities,
            checks = detail.checks,
            refreshing = detail.refreshing,
            errorMessage = detail.errorMessage,
            selectedTab = workspaceTab,
            lifecyclePreview = lifecyclePreview,
            snapshotPane = snapshotPane,
            storagePane = storagePane,
            logsPane = logsPane,
            usersPane = usersPane,
            servicesPane = servicesPane,
            systemSupportPane = systemSupportPane,
            onBack = { workspaceName = null },
            onSelectTab = { workspaceTabName = it.name },
            onRefreshDetail = onRefreshDetail,
            onPreviewLifecycle = onPreviewLifecycle,
            onStartLifecycle = onStartLifecycle,
            onExecuteRemove = onExecuteRemove,
            onRefreshSnapshots = onRefreshSnapshots,
            onRefreshStorage = onRefreshStorage,
            onRefreshLogs = onRefreshLogs,
            onPreviewSnapshotCreate = onPreviewSnapshotCreate,
            onStartSnapshotCreate = onStartSnapshotCreate,
            onPreviewSnapshotAction = onPreviewSnapshotAction,
            onStartSnapshotRestore = onStartSnapshotRestore,
            onStartSnapshotExport = onStartSnapshotExport,
            onRefreshUsers = onRefreshUsers,
            onPreviewUserPayload = onPreviewUserPayload,
            onClearUserPreview = onClearUserPreview,
            onStartUserOperation = onStartUserOperation,
            onRefreshServices = onRefreshServices,
            onRefreshServiceDetail = onRefreshServiceDetail,
            onPreviewServicePayload = onPreviewServicePayload,
            onClearServicePreview = onClearServicePreview,
            onStartServiceOperation = onStartServiceOperation,
            onRefreshSystemSupport = onRefreshSystemSupport,
            onPreviewSupportBundle = onPreviewSupportBundle,
            onStartSupportBundle = onStartSupportBundle,
            onPreviewRepair = onPreviewRepair,
            onToggleRepairItem = onToggleRepairItem,
            onStartRepair = onStartRepair,
            modifier = modifier,
        )
    } else {
        ChrootWorkspaceLauncher(
            chroots = chroots,
            visibleChroots = visibleChroots,
            query = query,
            filter = filter,
            onQueryChange = { query = it },
            onFilterChange = { filterName = it.name },
            onOpenWorkspace = { name ->
                workspaceName = name
                workspaceTabName = ChrootWorkspaceTab.Overview.name
                requestedWorkspaceSelection = name
                onSelect(name)
            },
            onPreviewLifecycle = onPreviewLifecycle,
            onPreviewSnapshotCreate = onPreviewSnapshotCreate,
            modifier = modifier,
        )
    }
}

@Composable
private fun ChrootWorkspaceLauncher(
    chroots: List<ChrootSummary>,
    visibleChroots: List<ChrootSummary>,
    query: String,
    filter: ChrootListFilter,
    onQueryChange: (String) -> Unit,
    onFilterChange: (ChrootListFilter) -> Unit,
    onOpenWorkspace: (String) -> Unit,
    onPreviewLifecycle: (String, String) -> Unit,
    onPreviewSnapshotCreate: (String, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        SectionHeader(
            title = stringResource(R.string.chroots_workspace_launcher_title),
            body = if (chrootListIsWorkspaceLauncherOnly()) stringResource(R.string.chroots_workspace_launcher_body) else stringResource(R.string.chroots_phase32_body),
        )
        OutlinedTextField(
            value = query,
            onValueChange = onQueryChange,
            label = { Text(stringResource(R.string.chroots_search_label)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        ActionFlowRow {
            ChrootFilterButton(filter = ChrootListFilter.All, selected = filter == ChrootListFilter.All, onSelect = onFilterChange)
            ChrootFilterButton(filter = ChrootListFilter.Running, selected = filter == ChrootListFilter.Running, onSelect = onFilterChange)
            ChrootFilterButton(filter = ChrootListFilter.Stopped, selected = filter == ChrootListFilter.Stopped, onSelect = onFilterChange)
            ChrootFilterButton(filter = ChrootListFilter.Attention, selected = filter == ChrootListFilter.Attention, onSelect = onFilterChange)
        }
        when {
            chroots.isEmpty() -> EmptyState(
                title = stringResource(R.string.chroots_empty_title),
                body = stringResource(R.string.chroots_empty_body),
            )
            visibleChroots.isEmpty() -> EmptyState(
                title = stringResource(R.string.chroots_no_matches_title),
                body = stringResource(R.string.chroots_no_matches_body),
            )
            else -> visibleChroots.forEach { chroot ->
                Phase32ChrootCard(
                    chroot = chroot,
                    selected = false,
                    onSelect = { onOpenWorkspace(chroot.name) },
                    onPreviewLifecycle = onPreviewLifecycle,
                    onPreviewSnapshotCreate = { name ->
                        onPreviewSnapshotCreate(name, defaultSnapshotName())
                    },
                )
            }
        }
    }
}

@Composable
private fun ChrootFilterButton(filter: ChrootListFilter, selected: Boolean, onSelect: (ChrootListFilter) -> Unit) {
    val label = when (filter) {
        ChrootListFilter.All -> stringResource(R.string.chroot_filter_all)
        ChrootListFilter.Running -> stringResource(R.string.chroot_filter_running)
        ChrootListFilter.Stopped -> stringResource(R.string.chroot_filter_stopped)
        ChrootListFilter.Attention -> stringResource(R.string.chroot_filter_attention)
    }
    if (selected) {
        Button(onClick = { onSelect(filter) }, modifier = Modifier.releaseSelectionSemantics(selected)) { Text(label) }
    } else {
        OutlinedButton(onClick = { onSelect(filter) }, modifier = Modifier.releaseSelectionSemantics(selected)) { Text(label) }
    }
}

@Composable
private fun Phase32ChrootCard(
    chroot: ChrootSummary,
    selected: Boolean,
    onSelect: () -> Unit,
    onPreviewLifecycle: (String, String) -> Unit,
    onPreviewSnapshotCreate: (String) -> Unit,
) {
    val running = isRunningChrootStatus(chroot.status) || chroot.mountState?.let(::isRunningChrootStatus) == true
    val tone = when {
        chroot.warningCount > 0 -> StatusTone.Warning
        running -> StatusTone.Success
        else -> StatusTone.Neutral
    }
    val card: @Composable (Modifier, @Composable () -> Unit) -> Unit = if (selected) {
        { itemModifier, content -> OutlinedCard(itemModifier, content = { content() }) }
    } else {
        { itemModifier, content -> Card(itemModifier, content = { content() }) }
    }
    card(Modifier.fillMaxWidth().clickable(onClick = onSelect)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            ActionFlowRow {
                StatusPill(chroot.status.ifBlank { stringResource(R.string.value_unknown) }, tone)
                if (chroot.warningCount > 0) StatusPill(pluralStringResource(R.plurals.chroot_warnings_count, chroot.warningCount, chroot.warningCount), StatusTone.Warning)
                StatusPill(stringResource(R.string.chroot_workspace_app_chip), StatusTone.Accent)
            }
            Text(chroot.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(chrootWorkspaceSummary(chroot), color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                stringResource(
                    R.string.chroot_workspace_launcher_health_line,
                    chroot.mountState ?: stringResource(R.string.value_unknown),
                    chroot.health ?: stringResource(R.string.value_not_reported),
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            ActionFlowRow {
                Button(onClick = onSelect, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.action_open_workspace))
                }
                if (running) {
                    OutlinedButton(onClick = { onSelect(); onPreviewLifecycle(chroot.name, "restart") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                        Text(stringResource(R.string.action_preview_restart))
                    }
                } else {
                    OutlinedButton(onClick = { onSelect(); onPreviewLifecycle(chroot.name, "start") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                        Text(stringResource(R.string.action_preview_start))
                    }
                }
                OutlinedButton(onClick = { onSelect(); onPreviewSnapshotCreate(chroot.name) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.action_preview_snapshot))
                }
            }
        }
    }
}

@Composable
private fun ChrootWorkspaceScreen(
    chroot: ChrootSummary,
    operations: List<OperationSummary>,
    capabilities: BridgeCapabilities?,
    checks: List<CheckSummary>,
    refreshing: Boolean,
    errorMessage: String?,
    selectedTab: ChrootWorkspaceTab,
    lifecyclePreview: PreviewSummary?,
    snapshotPane: SnapshotPane,
    storagePane: StoragePane,
    logsPane: LogsPane,
    usersPane: UsersPane,
    servicesPane: ServicesPane,
    systemSupportPane: SystemSupportPane,
    onBack: () -> Unit,
    onSelectTab: (ChrootWorkspaceTab) -> Unit,
    onRefreshDetail: () -> Unit,
    onPreviewLifecycle: (String, String) -> Unit,
    onStartLifecycle: (String, String) -> Unit,
    onExecuteRemove: (String, String) -> Unit,
    onRefreshSnapshots: (String) -> Unit,
    onRefreshStorage: (String) -> Unit,
    onRefreshLogs: (String, String?) -> Unit,
    onPreviewSnapshotCreate: (String, String) -> Unit,
    onStartSnapshotCreate: (String, String) -> Unit,
    onPreviewSnapshotAction: (String, String, String) -> Unit,
    onStartSnapshotRestore: (String, String, String) -> Unit,
    onStartSnapshotExport: (String, String) -> Unit,
    onRefreshUsers: (String) -> Unit,
    onPreviewUserPayload: (String) -> Unit,
    onClearUserPreview: () -> Unit,
    onStartUserOperation: (String, String) -> Unit,
    onRefreshServices: (String) -> Unit,
    onRefreshServiceDetail: (String, String) -> Unit,
    onPreviewServicePayload: (String) -> Unit,
    onClearServicePreview: () -> Unit,
    onStartServiceOperation: (String, String) -> Unit,
    onRefreshSystemSupport: () -> Unit,
    onPreviewSupportBundle: () -> Unit,
    onStartSupportBundle: () -> Unit,
    onPreviewRepair: () -> Unit,
    onToggleRepairItem: (String) -> Unit,
    onStartRepair: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val availableOperations = capabilities?.operations?.toSet()
    val capabilitiesKnown = capabilities != null
    val effectiveTab = effectiveWorkspaceTab(selectedTab, availableOperations)
    val paneLabel = workspaceTabLabel(effectiveTab)
    val paneDescription = stringResource(R.string.chroot_workspace_pane_title, chroot.name, paneLabel)
    LaunchedEffect(selectedTab, effectiveTab, capabilitiesKnown) {
        if (shouldPersistWorkspaceFallback(selectedTab, effectiveTab, capabilitiesKnown)) onSelectTab(effectiveTab)
    }
    Column(
        modifier.semantics { paneTitle = paneDescription },
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        SectionHeader(
            title = stringResource(R.string.chroot_workspace_title, chroot.name),
            body = chrootWorkspaceSummary(chroot),
            action = {
                OutlinedButton(onClick = onBack, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.action_back_to_chroots))
                }
            },
        )
        ActionFlowRow(contentDescription = stringResource(R.string.chroot_workspace_tabs_label)) {
            chrootWorkspaceTabs().forEach { tab ->
                ChrootWorkspaceTabButton(
                    tab = tab,
                    selected = tab == effectiveTab,
                    supported = workspaceTabSupported(tab, availableOperations),
                    onSelect = onSelectTab,
                )
            }
        }
        if (capabilities != null && chrootWorkspaceTabs().any { !workspaceTabSupported(it, availableOperations) }) {
            StatusCard(
                title = stringResource(R.string.chroot_workspace_degraded_title),
                body = stringResource(R.string.chroot_workspace_degraded_body),
            )
        }
        if (chroot.stale) {
            StatusCard(
                title = stringResource(R.string.status_cached_data),
                body = stringResource(R.string.storage_stale_warning),
                footer = {
                    Button(
                        onClick = onRefreshDetail,
                        enabled = !refreshing,
                        modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                    ) {
                        Text(if (refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_detail))
                    }
                },
            )
        }
        when (effectiveTab) {
            ChrootWorkspaceTab.Overview -> WorkspaceOverviewTab(
                chroot = chroot,
                checks = checks,
                refreshing = refreshing,
                errorMessage = errorMessage,
                lifecyclePreview = lifecyclePreview,
                snapshotPane = snapshotPane,
                usersPane = usersPane,
                servicesPane = servicesPane,
                onRefreshDetail = onRefreshDetail,
                onPreviewLifecycle = onPreviewLifecycle,
                onStartLifecycle = onStartLifecycle,
                onPreviewSnapshotCreate = onPreviewSnapshotCreate,
                availableOperations = availableOperations,
                onOpenTab = onSelectTab,
            )
            ChrootWorkspaceTab.Services -> ServicesPanel(
                chroot = chroot,
                pane = servicesPane,
                onRefreshServices = onRefreshServices,
                onRefreshServiceDetail = onRefreshServiceDetail,
                onPreviewServicePayload = onPreviewServicePayload,
                onClearServicePreview = onClearServicePreview,
                onStartServiceOperation = onStartServiceOperation,
            )
            ChrootWorkspaceTab.Users -> UsersPanel(
                chroot = chroot,
                pane = usersPane,
                onRefreshUsers = onRefreshUsers,
                onPreviewUserPayload = onPreviewUserPayload,
                onClearUserPreview = onClearUserPreview,
                onStartUserOperation = onStartUserOperation,
            )
            ChrootWorkspaceTab.Snapshots -> SnapshotPanel(
                chroot = chroot,
                pane = snapshotPane,
                operations = operations,
                onRefreshSnapshots = onRefreshSnapshots,
                onPreviewSnapshotCreate = onPreviewSnapshotCreate,
                onStartSnapshotCreate = onStartSnapshotCreate,
                onPreviewSnapshotAction = onPreviewSnapshotAction,
                onStartSnapshotRestore = onStartSnapshotRestore,
                onStartSnapshotExport = onStartSnapshotExport,
            )
            ChrootWorkspaceTab.Storage -> StoragePanel(
                chroot = chroot,
                pane = storagePane,
                snapshotPane = snapshotPane,
                supportPane = systemSupportPane,
                onRefreshStorage = onRefreshStorage,
                onOpenAdvanced = { onSelectTab(ChrootWorkspaceTab.Advanced) },
                onPreviewSupportBundle = onPreviewSupportBundle,
                onStartSupportBundle = onStartSupportBundle,
            )
            ChrootWorkspaceTab.Logs -> LogsPanel(
                chroot = chroot,
                pane = logsPane,
                servicesPane = servicesPane,
                operations = operations,
                onRefreshLogs = onRefreshLogs,
                onRefreshServices = onRefreshServices,
                onRefreshServiceDetail = onRefreshServiceDetail,
            )
            ChrootWorkspaceTab.Advanced -> AdvancedWorkspaceTab(
                chroot = chroot,
                checks = checks,
                capabilities = capabilities,
                supportPane = systemSupportPane,
                lifecyclePreview = lifecyclePreview,
                onPreviewLifecycle = onPreviewLifecycle,
                onStartLifecycle = onStartLifecycle,
                onExecuteRemove = onExecuteRemove,
                onRefreshSystemSupport = onRefreshSystemSupport,
                onPreviewSupportBundle = onPreviewSupportBundle,
                onStartSupportBundle = onStartSupportBundle,
                onPreviewRepair = onPreviewRepair,
                onToggleRepairItem = onToggleRepairItem,
                onStartRepair = onStartRepair,
            )
        }
    }
}

@Composable
private fun ChrootWorkspaceTabButton(
    tab: ChrootWorkspaceTab,
    selected: Boolean,
    supported: Boolean,
    onSelect: (ChrootWorkspaceTab) -> Unit,
) {
    val label = workspaceTabLabel(tab)
    if (selected) {
        Button(
            onClick = { onSelect(tab) },
            enabled = supported,
            modifier = Modifier.releaseSelectionSemantics(selected),
        ) { Text(label) }
    } else {
        OutlinedButton(
            onClick = { onSelect(tab) },
            enabled = supported,
            modifier = Modifier.releaseSelectionSemantics(selected),
        ) { Text(label) }
    }
}

@Composable
private fun workspaceTabLabel(tab: ChrootWorkspaceTab): String = when (tab) {
    ChrootWorkspaceTab.Overview -> stringResource(R.string.chroot_workspace_tab_overview)
    ChrootWorkspaceTab.Services -> stringResource(R.string.chroot_workspace_tab_services)
    ChrootWorkspaceTab.Users -> stringResource(R.string.chroot_workspace_tab_users)
    ChrootWorkspaceTab.Snapshots -> stringResource(R.string.chroot_workspace_tab_snapshots)
    ChrootWorkspaceTab.Storage -> stringResource(R.string.chroot_workspace_tab_storage)
    ChrootWorkspaceTab.Logs -> stringResource(R.string.chroot_workspace_tab_logs)
    ChrootWorkspaceTab.Advanced -> stringResource(R.string.chroot_workspace_tab_advanced)
}

@Composable
private fun WorkspaceOverviewTab(
    chroot: ChrootSummary,
    checks: List<CheckSummary>,
    refreshing: Boolean,
    errorMessage: String?,
    lifecyclePreview: PreviewSummary?,
    snapshotPane: SnapshotPane,
    usersPane: UsersPane,
    servicesPane: ServicesPane,
    onRefreshDetail: () -> Unit,
    onPreviewLifecycle: (String, String) -> Unit,
    onStartLifecycle: (String, String) -> Unit,
    onPreviewSnapshotCreate: (String, String) -> Unit,
    availableOperations: Set<String>?,
    onOpenTab: (ChrootWorkspaceTab) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        errorMessage?.let { message ->
            BridgePaneError(message = message, onRetry = onRefreshDetail)
        }
        StatusCard(
            title = stringResource(R.string.chroot_workspace_overview_title),
            body = stringResource(R.string.chroot_workspace_overview_body),
            footer = {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    ActionFlowRow {
                        StatusPill(chroot.status.ifBlank { stringResource(R.string.value_unknown) }, if (chroot.warningCount > 0) StatusTone.Warning else StatusTone.Success)
                        StatusPill(chroot.health ?: stringResource(R.string.value_not_reported), if (chroot.warningCount > 0) StatusTone.Warning else StatusTone.Neutral)
                        if (refreshing) StatusPill(stringResource(R.string.action_refreshing), StatusTone.Accent)
                    }
                    ResponsiveMetricCards(
                        cards = listOf(
                            MetricCardData(stringResource(R.string.chroot_workspace_metric_services), servicesPane.services.size.toString(), stringResource(R.string.chroot_workspace_metric_services_detail)),
                            MetricCardData(stringResource(R.string.chroot_workspace_metric_users), usersPane.users.size.toString(), stringResource(R.string.chroot_workspace_metric_users_detail)),
                            MetricCardData(stringResource(R.string.chroot_workspace_metric_snapshots), snapshotPane.snapshots.size.toString(), stringResource(R.string.chroot_workspace_metric_snapshots_detail)),
                        ),
                    )
                    ActionFlowRow {
                        Button(onClick = onRefreshDetail, enabled = !refreshing, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                            Text(if (refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_detail))
                        }
                        if (isRunningChrootStatus(chroot.status) || chroot.mountState?.let(::isRunningChrootStatus) == true) {
                            OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "restart") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                                Text(stringResource(R.string.action_preview_restart))
                            }
                            Button(
                                onClick = { onStartLifecycle(chroot.name, "chroots.restart") },
                                enabled = lifecyclePreview.approvesOperation("chroots.restart"),
                                modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                            ) {
                                Text(stringResource(R.string.action_restart_chroot))
                            }
                        } else {
                            OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "start") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                                Text(stringResource(R.string.action_preview_start))
                            }
                            Button(
                                onClick = { onStartLifecycle(chroot.name, "chroots.start") },
                                enabled = lifecyclePreview.approvesOperation("chroots.start"),
                                modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                            ) {
                                Text(stringResource(R.string.action_start_chroot))
                            }
                        }
                        OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "upgrade") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                            Text(stringResource(R.string.action_preview_upgrade))
                        }
                        Button(
                            onClick = { onStartLifecycle(chroot.name, "chroots.upgrade") },
                            enabled = lifecyclePreview.approvesOperation("chroots.upgrade"),
                            modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                        ) {
                            Text(stringResource(R.string.action_upgrade_chroot))
                        }
                        OutlinedButton(onClick = { onPreviewSnapshotCreate(chroot.name, defaultSnapshotName()) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                            Text(stringResource(R.string.action_preview_snapshot))
                        }
                    }
                    ActionFlowRow {
                        OutlinedButton(onClick = { onOpenTab(ChrootWorkspaceTab.Services) }, enabled = workspaceTabSupported(ChrootWorkspaceTab.Services, availableOperations), modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.chroot_workspace_open_services)) }
                        OutlinedButton(onClick = { onOpenTab(ChrootWorkspaceTab.Users) }, enabled = workspaceTabSupported(ChrootWorkspaceTab.Users, availableOperations), modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.chroot_workspace_open_users)) }
                        OutlinedButton(onClick = { onOpenTab(ChrootWorkspaceTab.Snapshots) }, enabled = workspaceTabSupported(ChrootWorkspaceTab.Snapshots, availableOperations), modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.chroot_workspace_open_snapshots)) }
                        OutlinedButton(onClick = { onOpenTab(ChrootWorkspaceTab.Storage) }, enabled = workspaceTabSupported(ChrootWorkspaceTab.Storage, availableOperations), modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.chroot_workspace_open_storage)) }
                        OutlinedButton(onClick = { onOpenTab(ChrootWorkspaceTab.Logs) }, enabled = workspaceTabSupported(ChrootWorkspaceTab.Logs, availableOperations), modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.chroot_workspace_open_logs)) }
                    }
                    lifecyclePreview?.let { item -> PreviewSummaryBlock(item) }
                }
            },
        )
        if (checks.isEmpty()) {
            EmptyState(
                title = stringResource(R.string.chroot_workspace_checks_empty_title),
                body = stringResource(R.string.chroot_detail_checks_empty),
            )
        } else {
            StatusCard(
                title = stringResource(R.string.chroot_workspace_checks_title),
                body = stringResource(R.string.chroot_workspace_checks_body),
                footer = {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        checks.take(MAX_OVERVIEW_CHECKS).forEach { check -> CheckRow(check) }
                        if (checks.size > MAX_OVERVIEW_CHECKS) {
                            Text(pluralStringResource(R.plurals.chroot_workspace_checks_more, checks.size - MAX_OVERVIEW_CHECKS, checks.size - MAX_OVERVIEW_CHECKS), color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                },
            )
        }
    }
}

@Composable
private fun AdvancedWorkspaceTab(
    chroot: ChrootSummary,
    checks: List<CheckSummary>,
    capabilities: BridgeCapabilities?,
    supportPane: SystemSupportPane,
    lifecyclePreview: PreviewSummary?,
    onPreviewLifecycle: (String, String) -> Unit,
    onStartLifecycle: (String, String) -> Unit,
    onExecuteRemove: (String, String) -> Unit,
    onRefreshSystemSupport: () -> Unit,
    onPreviewSupportBundle: () -> Unit,
    onStartSupportBundle: () -> Unit,
    onPreviewRepair: () -> Unit,
    onToggleRepairItem: (String) -> Unit,
    onStartRepair: () -> Unit,
) {
    var capabilitiesVisible by rememberSaveable(chroot.name) { mutableStateOf(false) }
    var rawPayloadVisible by rememberSaveable(chroot.name) { mutableStateOf(false) }
    val paneState = workspacePaneState(
        refreshing = supportPane.refreshing,
        errorMessage = supportPane.errorMessage,
        hasContent = capabilities != null || checks.isNotEmpty() || supportPane.runtimeRows.isNotEmpty(),
    )
    val paneTitleText = stringResource(R.string.chroot_workspace_tab_advanced)
    Column(
        Modifier.fillMaxWidth().semantics { paneTitle = paneTitleText },
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        WorkspacePaneFeedback(
            state = paneState,
            loadingLabel = stringResource(R.string.workspace_loading_advanced),
            emptyTitle = stringResource(R.string.advanced_workspace_empty_title),
            emptyBody = stringResource(R.string.advanced_workspace_empty_body),
            errorMessage = supportPane.errorMessage,
            onRetry = onRefreshSystemSupport,
        )
        LifecyclePanel(
            chroot = chroot,
            preview = lifecyclePreview,
            onPreviewLifecycle = onPreviewLifecycle,
            onStartLifecycle = onStartLifecycle,
            onExecuteRemove = onExecuteRemove,
        )
        StatusCard(
            title = stringResource(R.string.advanced_runtime_title),
            body = stringResource(R.string.advanced_runtime_body),
            footer = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    DetailRow(stringResource(R.string.advanced_protocol), capabilities?.protocolVersion?.toString() ?: stringResource(R.string.value_not_reported))
                    DetailRow(stringResource(R.string.advanced_backend), capabilities?.backendVersion ?: stringResource(R.string.value_not_reported))
                    DetailRow(stringResource(R.string.advanced_arbitrary_shell), if (capabilities?.arbitraryShell == true) stringResource(R.string.value_yes) else stringResource(R.string.value_no))
                    DetailRow(stringResource(R.string.advanced_capabilities_count), capabilities?.operationCapabilities?.size?.toString() ?: "0")
                    OutlinedButton(
                        onClick = { capabilitiesVisible = !capabilitiesVisible },
                        modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                    ) {
                        Text(if (capabilitiesVisible) stringResource(R.string.advanced_hide_capabilities) else stringResource(R.string.advanced_show_capabilities))
                    }
                    if (capabilitiesVisible) {
                        capabilities?.operationCapabilities.orEmpty().forEach { capability ->
                            Text(
                                "${capability.name} · ${capability.mode} · ${capability.lockScope}",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                }
            },
        )
        StatusCard(
            title = stringResource(R.string.chroot_workspace_advanced_diagnostics_title),
            body = stringResource(R.string.chroot_workspace_advanced_diagnostics_body),
            footer = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    DetailRow(stringResource(R.string.chroot_detail_status), chroot.status)
                    DetailRow(stringResource(R.string.chroot_detail_release), listOfNotNull(chroot.distribution, chroot.release, chroot.architecture).joinToString(" · ").ifBlank { stringResource(R.string.value_not_reported) })
                    DetailRow(stringResource(R.string.chroot_detail_path), chroot.path ?: stringResource(R.string.value_not_reported))
                    if (checks.isEmpty()) {
                        Text(stringResource(R.string.chroot_detail_checks_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else {
                        checks.forEach { check -> CheckRow(check) }
                    }
                }
            },
        )
        StatusCard(
            title = stringResource(R.string.advanced_raw_payload_title),
            body = stringResource(R.string.advanced_raw_payload_body),
            footer = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    DetailRow(stringResource(R.string.chroot_detail_raw_size), chroot.rawJson.length.toString())
                    OutlinedButton(
                        onClick = { rawPayloadVisible = !rawPayloadVisible },
                        modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                    ) {
                        Text(if (rawPayloadVisible) stringResource(R.string.advanced_hide_raw) else stringResource(R.string.advanced_show_raw))
                    }
                    if (rawPayloadVisible) {
                        PathText(chroot.rawJson.take(MAX_RAW_PAYLOAD_CHARS), modifier = Modifier.fillMaxWidth())
                    }
                }
            },
        )
        StatusCard(
            title = stringResource(R.string.advanced_support_title),
            body = stringResource(R.string.advanced_support_body),
            footer = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    ActionFlowRow {
                        OutlinedButton(onClick = onRefreshSystemSupport, enabled = !supportPane.refreshing, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                            Text(if (supportPane.refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.system_refresh_action))
                        }
                        OutlinedButton(onClick = onPreviewSupportBundle, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.support_preview_action)) }
                        Button(onClick = onStartSupportBundle, enabled = supportPane.supportPreview?.ok == true, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.support_bundle_action)) }
                    }
                    supportPane.runtimeRows.forEach { row ->
                        Text(stringResource(R.string.system_row, row.label, row.value, row.state), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                    }
                    supportPane.supportPreview?.let { PreviewSummaryBlock(it) }
                }
            },
        )
        StatusCard(
            title = stringResource(R.string.repair_selective_title),
            body = stringResource(R.string.repair_selective_body),
            footer = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    ActionFlowRow {
                        OutlinedButton(onClick = onPreviewRepair, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.repair_load_plan_action)) }
                        OutlinedButton(onClick = onPreviewRepair, enabled = supportPane.selectedRepairItemIds.isNotEmpty(), modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.repair_preview_selected_action)) }
                        Button(
                            onClick = onStartRepair,
                            enabled = supportPane.selectedRepairItemIds.isNotEmpty() && supportPane.repairPreview?.ok == true,
                            modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                        ) { Text(stringResource(R.string.repair_apply_selected_action)) }
                    }
                    supportPane.repairItems.forEach { item ->
                        val selected = item.itemId in supportPane.selectedRepairItemIds
                        OutlinedCard(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text(item.summary.ifBlank { item.name }, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
                                Text(stringResource(R.string.repair_item_meta, item.kind, item.severity, item.action), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                                OutlinedButton(onClick = { onToggleRepairItem(item.itemId) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                                    Text(if (selected) stringResource(R.string.advanced_repair_deselect) else stringResource(R.string.advanced_repair_select))
                                }
                            }
                        }
                    }
                    if (supportPane.repairItems.isEmpty()) {
                        Text(stringResource(R.string.advanced_repair_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    supportPane.repairPreview?.let { PreviewSummaryBlock(it) }
                }
            },
        )
    }
}

@Composable
private fun WorkspacePaneFeedback(
    state: WorkspacePaneState,
    loadingLabel: String,
    emptyTitle: String,
    emptyBody: String,
    errorMessage: String?,
    onRetry: () -> Unit,
) {
    when (state) {
        WorkspacePaneState.Loading -> LoadingState(loadingLabel)
        WorkspacePaneState.Empty -> EmptyState(title = emptyTitle, body = emptyBody)
        WorkspacePaneState.Failure -> errorMessage?.let { BridgePaneError(message = it, onRetry = onRetry) }
        WorkspacePaneState.Ready -> errorMessage?.let { BridgePaneError(message = it, onRetry = onRetry) }
    }
}

@Composable
private fun BridgePaneError(message: String, onRetry: (() -> Unit)? = null) {
    var detailsVisible by rememberSaveable(message) { mutableStateOf(false) }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            StatusPill(stringResource(R.string.status_needs_attention), StatusTone.Danger)
            Text(
                if (isBridgeShapeError(message)) stringResource(R.string.bridge_shape_error_title) else stringResource(R.string.backend_issue_unknown_title),
                fontWeight = FontWeight.SemiBold,
            )
            Text(bridgeShapePrimaryMessage(message), color = MaterialTheme.colorScheme.onSurfaceVariant)
            ActionFlowRow {
                onRetry?.let { retry ->
                    Button(onClick = retry, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_retry)) }
                }
                TextButton(onClick = { detailsVisible = !detailsVisible }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(if (detailsVisible) stringResource(R.string.action_hide_technical_details) else stringResource(R.string.action_show_technical_details))
                }
            }
            if (detailsVisible) {
                PathText(message.take(1200), modifier = Modifier.fillMaxWidth())
            }
        }
    }
}

@Composable
private fun LifecyclePanel(
    chroot: ChrootSummary,
    preview: PreviewSummary?,
    onPreviewLifecycle: (String, String) -> Unit,
    onStartLifecycle: (String, String) -> Unit,
    onExecuteRemove: (String, String) -> Unit,
) {
    var removeConfirmation by remember(chroot.name) { mutableStateOf("") }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.lifecycle_actions_title), fontWeight = FontWeight.SemiBold)
            ActionFlowRow {
                OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "start") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_preview_start)) }
                Button(onClick = { onStartLifecycle(chroot.name, "chroots.start") }, enabled = preview.approvesOperation("chroots.start"), modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_start_chroot)) }
                OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "restart") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_preview_restart)) }
                Button(onClick = { onStartLifecycle(chroot.name, "chroots.restart") }, enabled = preview.approvesOperation("chroots.restart"), modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_restart_chroot)) }
                OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "upgrade") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_preview_upgrade)) }
                Button(onClick = { onStartLifecycle(chroot.name, "chroots.upgrade") }, enabled = preview.approvesOperation("chroots.upgrade"), modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_upgrade_chroot)) }
            }
            Text(stringResource(R.string.lifecycle_remove_safety_body), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            ActionFlowRow {
                OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "remove") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_preview_remove)) }
            }
            OutlinedTextField(
                value = removeConfirmation,
                onValueChange = { removeConfirmation = it },
                label = { Text(stringResource(R.string.lifecycle_remove_confirmation_label, chroot.name)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = { onExecuteRemove(chroot.name, removeConfirmation) },
                enabled = removeConfirmation == chroot.name && preview.approvesOperation("chroots.remove.execute"),
                modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
            ) {
                Text(stringResource(R.string.action_remove_chroot))
            }
            preview?.let { item -> PreviewSummaryBlock(item) }
        }
    }
}

@Composable
private fun SnapshotPanel(
    chroot: ChrootSummary,
    pane: SnapshotPane,
    operations: List<OperationSummary>,
    onRefreshSnapshots: (String) -> Unit,
    onPreviewSnapshotCreate: (String, String) -> Unit,
    onStartSnapshotCreate: (String, String) -> Unit,
    onPreviewSnapshotAction: (String, String, String) -> Unit,
    onStartSnapshotRestore: (String, String, String) -> Unit,
    onStartSnapshotExport: (String, String) -> Unit,
) {
    var reviewToken by remember(chroot.name) { mutableStateOf("") }
    val snapshots = if (pane.targetName == chroot.name) pane.snapshots else emptyList()
    val recovery = operations.asSequence()
        .filter { operationNeedsSnapshotRecovery(it, chroot.name) }
        .mapNotNull { operation -> matchingRecoverySnapshot(operation, snapshots)?.let { snapshot -> operation to snapshot } }
        .firstOrNull()
    val failedOperation = recovery?.first
    val recoverySnapshot = recovery?.second
    LaunchedEffect(chroot.name) {
        if (pane.targetName != chroot.name) onRefreshSnapshots(chroot.name)
    }
    val review = snapshotReviewToken(reviewToken, snapshots)
    val paneState = workspacePaneState(
        refreshing = pane.refreshing,
        errorMessage = pane.errorMessage,
        hasContent = snapshots.isNotEmpty() || pane.preview != null,
    )
    val paneTitleText = stringResource(R.string.snapshots_workspace_title)
    OutlinedCard(Modifier.fillMaxWidth().semantics { paneTitle = paneTitleText }) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.snapshots_workspace_title), fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.snapshots_workspace_body), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            ActionFlowRow {
                Button(onClick = { onRefreshSnapshots(chroot.name) }, enabled = !pane.refreshing, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(if (pane.refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_snapshots))
                }
                OutlinedButton(onClick = { reviewToken = SNAPSHOT_CREATE_REVIEW_TOKEN }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.snapshot_review_create))
                }
            }
            failedOperation?.let { operation ->
                StatusCard(
                    title = stringResource(R.string.snapshot_recovery_title),
                    body = stringResource(R.string.snapshot_recovery_body, operation.title, operation.state),
                    footer = {
                        if (recoverySnapshot != null) {
                            OutlinedButton(
                                onClick = { reviewToken = snapshotReviewTokenFor(SnapshotWorkspaceAction.Restore, recoverySnapshot.name) },
                                modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                            ) { Text(stringResource(R.string.snapshot_recovery_review_latest)) }
                        } else {
                            OutlinedButton(onClick = { onRefreshSnapshots(chroot.name) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                                Text(stringResource(R.string.snapshot_recovery_refresh))
                            }
                        }
                    },
                )
            }
            WorkspacePaneFeedback(
                state = paneState,
                loadingLabel = stringResource(R.string.workspace_loading_snapshots),
                emptyTitle = stringResource(R.string.snapshots_workspace_empty_title),
                emptyBody = stringResource(R.string.snapshot_list_empty),
                errorMessage = pane.errorMessage,
                onRetry = { onRefreshSnapshots(chroot.name) },
            )
            review?.let { (action, snapshot) ->
                SnapshotActionReviewSheet(
                    chroot = chroot,
                    action = action,
                    snapshot = snapshot,
                    preview = pane.preview,
                    previewAction = pane.previewAction,
                    previewSnapshot = pane.previewSnapshot,
                    onCancel = { reviewToken = "" },
                    onPreviewSnapshotCreate = onPreviewSnapshotCreate,
                    onStartSnapshotCreate = onStartSnapshotCreate,
                    onPreviewSnapshotAction = onPreviewSnapshotAction,
                    onStartSnapshotRestore = onStartSnapshotRestore,
                    onStartSnapshotExport = onStartSnapshotExport,
                )
            }
            if (review == null) pane.preview?.let { preview -> PreviewSummaryBlock(preview) }
            if (paneState == WorkspacePaneState.Ready && snapshots.isNotEmpty()) {
                snapshots.take(MAX_VISIBLE_SNAPSHOTS).forEach { snapshot ->
                    FocusedSnapshotRow(
                        snapshot = snapshot,
                        onReview = { action -> reviewToken = snapshotReviewTokenFor(action, snapshot.name) },
                    )
                }
            }
        }
    }
}

@Composable
private fun SnapshotActionReviewSheet(
    chroot: ChrootSummary,
    action: SnapshotWorkspaceAction,
    snapshot: SnapshotSummary?,
    preview: PreviewSummary?,
    previewAction: String?,
    previewSnapshot: String?,
    onCancel: () -> Unit,
    onPreviewSnapshotCreate: (String, String) -> Unit,
    onStartSnapshotCreate: (String, String) -> Unit,
    onPreviewSnapshotAction: (String, String, String) -> Unit,
    onStartSnapshotRestore: (String, String, String) -> Unit,
    onStartSnapshotExport: (String, String) -> Unit,
) {
    var restoreConfirmation by remember(chroot.name, action.name, snapshot?.name) { mutableStateOf("") }
    val createSnapshotName by remember(chroot.name, action.name, snapshot?.name) {
        mutableStateOf(defaultSnapshotName())
    }
    val reviewedSnapshotName = snapshot?.name ?: createSnapshotName
    val activePreview = preview?.takeIf {
        snapshotPreviewMatches(
            action = action,
            snapshotName = reviewedSnapshotName,
            previewAction = previewAction,
            previewSnapshot = previewSnapshot,
        )
    }
    val actionOperation = when (action) {
        SnapshotWorkspaceAction.Create -> "snapshots.create"
        SnapshotWorkspaceAction.Restore -> "snapshots.restore"
        SnapshotWorkspaceAction.Export -> "snapshots.export"
    }
    val executeEnabled = activePreview.approvesOperation(actionOperation) &&
        (action != SnapshotWorkspaceAction.Restore || restoreConfirmation == chroot.name)
    val actionLabel = when (action) {
        SnapshotWorkspaceAction.Create -> stringResource(R.string.action_create_snapshot)
        SnapshotWorkspaceAction.Restore -> stringResource(R.string.action_restore_snapshot)
        SnapshotWorkspaceAction.Export -> stringResource(R.string.action_export_snapshot)
    }
    val reviewTitle = stringResource(R.string.snapshot_action_review_title, actionLabel)
    StatusCard(
        title = reviewTitle,
        modifier = Modifier.semantics { paneTitle = reviewTitle },
        body = snapshot?.let { stringResource(R.string.snapshot_action_review_snapshot, it.name, it.createdAt) } ?: stringResource(R.string.snapshot_action_review_create_body, chroot.name),
        footer = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (action == SnapshotWorkspaceAction.Create) {
                    DetailRow(stringResource(R.string.snapshot_create_name), createSnapshotName)
                }
                if (action == SnapshotWorkspaceAction.Restore) {
                    OutlinedTextField(
                        value = restoreConfirmation,
                        onValueChange = { restoreConfirmation = it },
                        label = { Text(stringResource(R.string.snapshot_restore_confirmation_label, chroot.name)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                ActionFlowRow {
                    OutlinedButton(
                        onClick = {
                            when (action) {
                                SnapshotWorkspaceAction.Create -> onPreviewSnapshotCreate(chroot.name, createSnapshotName)
                                SnapshotWorkspaceAction.Restore -> snapshot?.let { onPreviewSnapshotAction(chroot.name, it.name, "restore") }
                                SnapshotWorkspaceAction.Export -> snapshot?.let { onPreviewSnapshotAction(chroot.name, it.name, "export") }
                            }
                        },
                        modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                    ) { Text(stringResource(R.string.snapshot_action_preview)) }
                    Button(
                        onClick = {
                            when (action) {
                                SnapshotWorkspaceAction.Create -> onStartSnapshotCreate(chroot.name, createSnapshotName)
                                SnapshotWorkspaceAction.Restore -> snapshot?.let { onStartSnapshotRestore(chroot.name, it.name, restoreConfirmation) }
                                SnapshotWorkspaceAction.Export -> snapshot?.let { onStartSnapshotExport(chroot.name, it.name) }
                            }
                        },
                        enabled = executeEnabled,
                        modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                    ) { Text(actionLabel) }
                    TextButton(onClick = onCancel, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_cancel)) }
                }
                activePreview?.let { PreviewSummaryBlock(it) }
            }
        },
    )
}

@Composable
private fun FocusedSnapshotRow(snapshot: SnapshotSummary, onReview: (SnapshotWorkspaceAction) -> Unit) {
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(snapshot.name, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
            Text(
                listOf(snapshot.kind, snapshot.createdAt, formatStorageBytes(snapshot.sizeBytes)).filter { it.isNotBlank() }.joinToString(" · "),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            ActionFlowRow {
                OutlinedButton(onClick = { onReview(SnapshotWorkspaceAction.Restore) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.snapshot_review_restore))
                }
                OutlinedButton(onClick = { onReview(SnapshotWorkspaceAction.Export) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.snapshot_review_export))
                }
            }
        }
    }
}

private const val SNAPSHOT_CREATE_REVIEW_TOKEN = "create:"
private const val SNAPSHOT_REVIEW_SEPARATOR = "\u001f"

private fun snapshotReviewTokenFor(action: SnapshotWorkspaceAction, snapshotName: String): String =
    "${action.name.lowercase()}:$SNAPSHOT_REVIEW_SEPARATOR$snapshotName"

private fun snapshotReviewToken(token: String, snapshots: List<SnapshotSummary>): Pair<SnapshotWorkspaceAction, SnapshotSummary?>? {
    if (token == SNAPSHOT_CREATE_REVIEW_TOKEN) return SnapshotWorkspaceAction.Create to null
    val separator = token.indexOf(SNAPSHOT_REVIEW_SEPARATOR)
    if (separator < 0) return null
    val action = when (token.substring(0, separator).removeSuffix(":")) {
        "restore" -> SnapshotWorkspaceAction.Restore
        "export" -> SnapshotWorkspaceAction.Export
        else -> return null
    }
    val snapshotName = token.substring(separator + SNAPSHOT_REVIEW_SEPARATOR.length)
    return snapshots.firstOrNull { it.name == snapshotName }?.let { action to it }
}

@Composable
private fun StoragePanel(
    chroot: ChrootSummary,
    pane: StoragePane,
    snapshotPane: SnapshotPane,
    supportPane: SystemSupportPane,
    onRefreshStorage: (String) -> Unit,
    onOpenAdvanced: () -> Unit,
    onPreviewSupportBundle: () -> Unit,
    onStartSupportBundle: () -> Unit,
) {
    val summary = pane.summary?.takeIf { it.name == chroot.name }
    val snapshotBytes = snapshotPane.takeIf { it.targetName == chroot.name }?.snapshots.orEmpty().sumOf { it.sizeBytes }
    LaunchedEffect(chroot.name) {
        if (pane.targetName != chroot.name) onRefreshStorage(chroot.name)
    }
    val paneState = workspacePaneState(pane.refreshing, pane.errorMessage, summary != null)
    val paneTitleText = stringResource(R.string.storage_workspace_title)
    OutlinedCard(Modifier.fillMaxWidth().semantics { paneTitle = paneTitleText }) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.storage_workspace_title), fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.storage_workspace_body), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            ActionFlowRow {
                Button(onClick = { onRefreshStorage(chroot.name) }, enabled = !pane.refreshing, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(if (pane.refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.storage_refresh))
                }
                OutlinedButton(onClick = onOpenAdvanced, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.storage_open_support)) }
            }
            ActionFlowRow {
                OutlinedButton(onClick = onPreviewSupportBundle, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.storage_preview_support_export))
                }
                Button(
                    onClick = onStartSupportBundle,
                    enabled = supportPane.supportPreview?.ok == true,
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(stringResource(R.string.storage_export_support_info))
                }
            }
            supportPane.supportPreview?.let { PreviewSummaryBlock(it) }
            WorkspacePaneFeedback(
                state = paneState,
                loadingLabel = stringResource(R.string.workspace_loading_storage),
                emptyTitle = stringResource(R.string.storage_workspace_empty_title),
                emptyBody = stringResource(R.string.storage_not_loaded),
                errorMessage = pane.errorMessage,
                onRetry = { onRefreshStorage(chroot.name) },
            )
            if (chroot.stale) {
                StatusPill(stringResource(R.string.storage_stale_warning), StatusTone.Warning)
            }
            if (paneState == WorkspacePaneState.Ready && summary != null) {
                if (!summary.rootfsExists) StatusPill(stringResource(R.string.storage_missing_rootfs), StatusTone.Danger)
                DetailRow(stringResource(R.string.storage_rootfs_path), summary.rootfsPath)
                DetailRow(stringResource(R.string.storage_rootfs_size), workspaceSizeLabel(summary.rootfsBytes, summary.rootfsBytesReliable, summary.rootfsByteErrorCount, summary.rootfsSkippedMounts))
                DetailRow(stringResource(R.string.storage_cache_path), summary.cachePath)
                DetailRow(stringResource(R.string.storage_cache_size), workspaceSizeLabel(summary.cacheBytes, summary.cacheBytesReliable, summary.cacheByteErrorCount, summary.cacheSkippedMounts))
                DetailRow(stringResource(R.string.storage_mount_state), "${summary.mountState} · mounted ${summary.mountedCount}/${summary.mountCount} · mismatched ${summary.mismatchedMountCount}")
                DetailRow(stringResource(R.string.storage_disk_free), "${formatStorageBytes(summary.freeBytes)} / ${formatStorageBytes(summary.totalBytes)}")
                DetailRow(stringResource(R.string.storage_snapshot_footprint), workspaceSizeLabel(summary.snapshotBytes.takeIf { it > 0L } ?: snapshotBytes, summary.snapshotBytesReliable, summary.snapshotByteErrorCount, summary.snapshotSkippedMounts))
                DetailRow(stringResource(R.string.storage_snapshot_directory), summary.snapshotDirectory)
                if (!summary.rootfsBytesReliable || !summary.cacheBytesReliable || !summary.snapshotBytesReliable) {
                    StatusCard(
                        title = stringResource(R.string.storage_size_estimate_title),
                        body = stringResource(R.string.storage_size_estimate_body),
                    )
                }
            }
        }
    }
}

@Composable
private fun LogsPanel(
    chroot: ChrootSummary,
    pane: LogsPane,
    servicesPane: ServicesPane,
    operations: List<OperationSummary>,
    onRefreshLogs: (String, String?) -> Unit,
    onRefreshServices: (String) -> Unit,
    onRefreshServiceDetail: (String, String) -> Unit,
) {
    var filterName by rememberSaveable(chroot.name) { mutableStateOf(LogWorkspaceFilter.All.name) }
    var liveTail by rememberSaveable(chroot.name) { mutableStateOf(false) }
    val filter = selectedLogWorkspaceFilter(filterName)
    val bridgeLevel = logWorkspaceBridgeLevel(filter)
    val entries = if (pane.targetName == chroot.name) pane.entries else emptyList()
    val recentOperations = operations.filter { it.targetName == chroot.name }.take(MAX_VISIBLE_LOG_OPERATIONS)
    val lifecycleOwner = LocalLifecycleOwner.current
    LaunchedEffect(chroot.name) {
        if (pane.targetName != chroot.name) onRefreshLogs(chroot.name, bridgeLevel)
        if (servicesPane.targetName != chroot.name) onRefreshServices(chroot.name)
    }
    val services = if (servicesPane.targetName == chroot.name) servicesPane.services else emptyList()
    LaunchedEffect(liveTail, filterName, chroot.name) {
        lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (liveTail) {
                onRefreshLogs(chroot.name, bridgeLevel)
                delay(LOG_POLL_INTERVAL_MS)
            }
        }
    }
    val paneState = workspacePaneState(
        refreshing = pane.refreshing,
        errorMessage = pane.errorMessage,
        hasContent = pane.targetName == chroot.name && (pane.logFile.isNotBlank() || entries.isNotEmpty()),
    )
    val paneTitleText = stringResource(R.string.logs_workspace_title)
    OutlinedCard(Modifier.fillMaxWidth().semantics { paneTitle = paneTitleText }) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.logs_workspace_title), fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.logs_workspace_body), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            ActionFlowRow(contentDescription = stringResource(R.string.logs_filters_label)) {
                LogWorkspaceFilter.entries.forEach { item ->
                    if (item == filter) {
                        Button(onClick = { filterName = item.name }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(logFilterLabel(item)) }
                    } else {
                        OutlinedButton(
                            onClick = {
                                filterName = item.name
                                onRefreshLogs(chroot.name, logWorkspaceBridgeLevel(item))
                            },
                            modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                        ) { Text(logFilterLabel(item)) }
                    }
                }
            }
            ActionFlowRow {
                Button(onClick = { onRefreshLogs(chroot.name, bridgeLevel) }, enabled = !pane.refreshing, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(if (pane.refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.logs_refresh_action))
                }
                OutlinedButton(onClick = { liveTail = !liveTail }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(if (liveTail) stringResource(R.string.logs_stop_follow_action) else stringResource(R.string.logs_follow_action))
                }
            }
            WorkspacePaneFeedback(
                state = paneState,
                loadingLabel = stringResource(R.string.workspace_loading_logs),
                emptyTitle = stringResource(R.string.logs_workspace_empty_title),
                emptyBody = stringResource(R.string.logs_empty),
                errorMessage = pane.errorMessage,
                onRetry = { onRefreshLogs(chroot.name, bridgeLevel) },
            )
            if (paneState == WorkspacePaneState.Ready && pane.logFile.isNotBlank()) {
                DetailRow(stringResource(R.string.logs_file_label), pane.logFile)
                DetailRow(stringResource(R.string.logs_snapshot_count_label), "${pane.count}/${pane.tail.takeIf { it > 0 } ?: MAX_VISIBLE_LOG_LINES}")
                if (pane.truncated || pane.stale) {
                    StatusPill(stringResource(if (pane.truncated) R.string.logs_snapshot_truncated else R.string.status_cached_data), StatusTone.Warning)
                }
            }
            if (paneState == WorkspacePaneState.Ready && entries.isEmpty()) {
                Text(stringResource(R.string.logs_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else if (paneState == WorkspacePaneState.Ready) {
                entries.takeLast(MAX_VISIBLE_LOG_LINES).forEach { entry ->
                    Text(
                        logEntryDisplay(entry),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            Text(stringResource(R.string.logs_operations_title), fontWeight = FontWeight.SemiBold)
            if (recentOperations.isEmpty()) {
                Text(stringResource(R.string.logs_operations_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                recentOperations.forEach { operation ->
                    Text(
                        listOfNotNull(operation.title, operation.state, operation.progressText.takeIf { it.isNotBlank() }, operation.errorCode).joinToString(" · "),
                        color = if (operationNeedsSnapshotRecovery(operation, chroot.name)) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            Text(stringResource(R.string.logs_service_journals_title), fontWeight = FontWeight.SemiBold)
            servicesPane.errorMessage?.takeIf { servicesPane.targetName == chroot.name }?.let { message ->
                BridgePaneError(message = message, onRetry = { onRefreshServices(chroot.name) })
            }
            services.forEach { service ->
                ActionFlowRow {
                    Text("${service.service} · ${service.status}", style = MaterialTheme.typography.bodySmall)
                    OutlinedButton(onClick = { onRefreshServiceDetail(chroot.name, service.service) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                        Text(stringResource(R.string.logs_view_journal))
                    }
                }
            }
            servicesPane.selectedService?.takeIf { it.chrootName == chroot.name && it.journalText.isNotBlank() }?.let { service ->
                StatusCard(title = stringResource(R.string.service_journal_title, service.service), body = service.journalText.take(MAX_JOURNAL_CHARS))
            }
        }
    }
}

private fun workspaceSizeLabel(bytes: Long, reliable: Boolean, errors: Int, skippedMounts: Int): String {
    val suffix = buildList {
        if (!reliable) add("estimate")
        if (errors > 0) add("$errors read error(s)")
        if (skippedMounts > 0) add("$skippedMounts mount(s) skipped")
    }.joinToString(" · ")
    return if (suffix.isBlank()) formatStorageBytes(bytes) else "${formatStorageBytes(bytes)} · $suffix"
}

private fun logEntryDisplay(entry: com.mikeyphw.chrootctl.model.ChrootLogEntrySummary): String {
    val level = entry.level.trim()
    val line = entry.line.trimEnd()
    if (level.isBlank()) return line
    val normalized = line.trimStart().uppercase()
    return if (normalized.startsWith(level.uppercase())) line else "$level · $line"
}

@Composable
private fun logFilterLabel(filter: LogWorkspaceFilter): String = when (filter) {
    LogWorkspaceFilter.All -> stringResource(R.string.logs_filter_all)
    LogWorkspaceFilter.Warning -> stringResource(R.string.logs_filter_warning)
    LogWorkspaceFilter.Error -> stringResource(R.string.logs_filter_error)
}

@Composable
private fun PreviewSummaryBlock(preview: PreviewSummary) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(preview.title, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
        Text(preview.body, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        if (preview.blocking.isNotEmpty()) Text(preview.blocking.joinToString(" • "), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        if (preview.warnings.isNotEmpty()) Text(preview.warnings.joinToString(" • "), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun UsersPanel(
    chroot: ChrootSummary,
    pane: UsersPane,
    onRefreshUsers: (String) -> Unit,
    onPreviewUserPayload: (String) -> Unit,
    onClearUserPreview: () -> Unit,
    onStartUserOperation: (String, String) -> Unit,
) {
    var filterName by rememberSaveable(chroot.name) { mutableStateOf(UserWorkspaceFilter.Managed.name) }
    var reviewUserToken by remember(chroot.name) { mutableStateOf("") }
    val filter = selectedUserWorkspaceFilter(filterName)
    val userList = if (pane.targetName == chroot.name) pane.users else emptyList()
    val visibleUsers = userList.filter { userMatchesWorkspaceFilter(it, filter) }
    val systemUsers = userList.filter(::userIsSystem)
    val reviewUser = reviewUsername(reviewUserToken)
        ?.let { username -> userList.firstOrNull { it.username == username } }
    val reviewIsAdd = reviewUserToken == ADD_USER_REVIEW_TOKEN
    val paneState = workspacePaneState(pane.refreshing, pane.errorMessage, userList.isNotEmpty())
    val paneTitleText = stringResource(R.string.users_workspace_title)

    OutlinedCard(Modifier.fillMaxWidth().semantics { paneTitle = paneTitleText }) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(R.string.users_workspace_title), fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.users_workspace_body), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            ActionFlowRow(contentDescription = stringResource(R.string.users_workspace_filters_label)) {
                userWorkspaceFilters().forEach { item ->
                    UserFilterButton(
                        filter = item,
                        selected = item == filter,
                        onSelect = { filterName = it.name },
                    )
                }
            }
            ActionFlowRow {
                Button(
                    onClick = { onRefreshUsers(chroot.name) },
                    enabled = !pane.refreshing,
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(if (pane.refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_users))
                }
                OutlinedButton(
                    onClick = { onClearUserPreview(); reviewUserToken = ADD_USER_REVIEW_TOKEN },
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(stringResource(R.string.action_review_add_user))
                }
            }
            WorkspacePaneFeedback(
                state = paneState,
                loadingLabel = stringResource(R.string.workspace_loading_users),
                emptyTitle = stringResource(R.string.users_workspace_empty_title),
                emptyBody = stringResource(R.string.users_list_empty),
                errorMessage = pane.errorMessage,
                onRetry = { onRefreshUsers(chroot.name) },
            )
            if (reviewIsAdd || reviewUser != null) {
                UserActionReviewSheet(
                    chroot = chroot.name,
                    user = reviewUser,
                    preview = pane.preview,
                    onCancel = { reviewUserToken = ""; onClearUserPreview() },
                    onPreviewUserPayload = onPreviewUserPayload,
                    onClearUserPreview = onClearUserPreview,
                    onStartUserOperation = onStartUserOperation,
                )
            }
            pane.preview?.let { preview -> PreviewSummaryBlock(preview) }
            when {
                paneState == WorkspacePaneState.Ready && visibleUsers.isEmpty() -> EmptyState(
                    title = stringResource(R.string.users_workspace_no_matches_title),
                    body = stringResource(R.string.users_workspace_no_matches_body),
                )
                paneState == WorkspacePaneState.Ready -> visibleUsers.forEach { user ->
                    FocusedUserRow(
                        user = user,
                        onReviewUserActions = { onClearUserPreview(); reviewUserToken = userReviewToken(user.username) },
                    )
                }
            }
            if (filter != UserWorkspaceFilter.SystemUsers && systemUsers.isNotEmpty()) {
                TextButton(
                    onClick = { filterName = UserWorkspaceFilter.SystemUsers.name },
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(pluralStringResource(R.plurals.action_show_system_users, systemUsers.size, systemUsers.size))
                }
            } else if (filter == UserWorkspaceFilter.SystemUsers) {
                TextButton(
                    onClick = { filterName = UserWorkspaceFilter.Managed.name },
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(stringResource(R.string.action_hide_system_users))
                }
            }
        }
    }
}

@Composable
private fun UserFilterButton(
    filter: UserWorkspaceFilter,
    selected: Boolean,
    onSelect: (UserWorkspaceFilter) -> Unit,
) {
    val label = when (filter) {
        UserWorkspaceFilter.Managed -> stringResource(R.string.user_filter_managed)
        UserWorkspaceFilter.LoginUsers -> stringResource(R.string.user_filter_login)
        UserWorkspaceFilter.SystemUsers -> stringResource(R.string.user_filter_system)
    }
    if (selected) {
        Button(onClick = { onSelect(filter) }, modifier = Modifier.releaseSelectionSemantics(selected)) { Text(label) }
    } else {
        OutlinedButton(onClick = { onSelect(filter) }, modifier = Modifier.releaseSelectionSemantics(selected)) { Text(label) }
    }
}

@Composable
private fun FocusedUserRow(
    user: UserSummary,
    onReviewUserActions: () -> Unit,
) {
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(user.username, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyMedium)
            Text(
                listOf("uid=${user.uid}", "gid=${user.gid}", user.shell.ifBlank { stringResource(R.string.value_not_reported) })
                    .joinToString(" · "),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            ActionFlowRow {
                if (userHasLoginShell(user)) {
                    StatusPill(stringResource(R.string.user_badge_login), StatusTone.Accent)
                }
                if (user.sudo) {
                    StatusPill(stringResource(R.string.user_badge_sudo), StatusTone.Success)
                }
                if (user.protectedAccount || user.username.equals("root", ignoreCase = true)) {
                    StatusPill(stringResource(R.string.user_badge_root), StatusTone.Warning)
                }
                if (user.system && !user.username.equals("root", ignoreCase = true)) {
                    StatusPill(stringResource(R.string.user_filter_system), StatusTone.Warning)
                }
            }
            OutlinedButton(
                onClick = onReviewUserActions,
                modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
            ) {
                Text(stringResource(R.string.action_review_user_actions))
            }
        }
    }
}

@Composable
private fun UserActionReviewSheet(
    chroot: String,
    user: UserSummary?,
    preview: PreviewSummary?,
    onCancel: () -> Unit,
    onPreviewUserPayload: (String) -> Unit,
    onClearUserPreview: () -> Unit,
    onStartUserOperation: (String, String) -> Unit,
) {
    val existingUser = user != null
    val actions = userWorkspaceActions(user)
    if (actions.isEmpty()) {
        val reviewTitle = stringResource(R.string.user_action_review_title, user?.username.orEmpty())
        OutlinedCard(Modifier.fillMaxWidth().semantics { paneTitle = reviewTitle }) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(reviewTitle, fontWeight = FontWeight.SemiBold, modifier = Modifier.semantics { heading() })
                Text("This is a protected or system account. It is read-only in chrootctl to prevent UID/GID, sudo, password, shell, or removal damage.", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                val reasons = user?.policyReasons.orEmpty()
                if (reasons.isNotEmpty()) Text(reasons.joinToString(" • "), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                TextButton(onClick = onCancel, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.action_cancel))
                }
            }
        }
        return
    }
    var actionName by remember(chroot, user?.username) { mutableStateOf(actions.first().name) }
    val action = actions.firstOrNull { it.name == actionName } ?: actions.first()
    var draftUsername by remember(chroot, user?.username) { mutableStateOf(user?.username.orEmpty()) }
    var draftShell by remember(chroot, user?.username) { mutableStateOf(user?.shell?.takeIf { it.isNotBlank() } ?: "/bin/bash") }
    var draftSudo by remember(chroot, user?.username) { mutableStateOf(user?.sudo ?: false) }
    var confirmation by remember(chroot, user?.username, actionName) { mutableStateOf("") }
    var password by remember(chroot, user?.username, actionName) { mutableStateOf("") }
    var confirmPassword by remember(chroot, user?.username, actionName) { mutableStateOf("") }

    val username = user?.username ?: draftUsername.trim()
    val payload = when (action) {
        UserWorkspaceAction.Add -> userPayload(chroot, username, "add").put("shell", draftShell).put("sudo", draftSudo).toString()
        UserWorkspaceAction.SyncUidGid -> userPayload(chroot, username, "sync_uid_gid").put("fixOwnership", true).toString()
        UserWorkspaceAction.SetShell -> userPayload(chroot, username, "set_shell").put("shell", draftShell).toString()
        UserWorkspaceAction.ToggleSudo -> userPayload(chroot, username, "set_sudo").put("enabled", !(user?.sudo ?: false)).toString()
        UserWorkspaceAction.SetPassword -> userPayload(chroot, username, "set_password")
            .put("password", password)
            .put("confirmPassword", confirmPassword)
            .put("confirmation", confirmation)
            .toString()
        UserWorkspaceAction.Remove -> userPayload(chroot, username, "remove")
            .put("confirmation", confirmation)
            .put("deleteHome", false)
            .toString()
    }
    val operation = when (action) {
        UserWorkspaceAction.Add -> "users.add"
        UserWorkspaceAction.SyncUidGid -> "users.sync_uid_gid"
        UserWorkspaceAction.SetShell -> "users.set_shell"
        UserWorkspaceAction.ToggleSudo -> "users.set_sudo"
        UserWorkspaceAction.SetPassword -> "users.set_password"
        UserWorkspaceAction.Remove -> "users.remove"
    }
    val canSubmit = when (action) {
        UserWorkspaceAction.Add -> username.isNotBlank() && draftShell.isNotBlank()
        UserWorkspaceAction.SyncUidGid -> existingUser && user?.mutable == true
        UserWorkspaceAction.SetShell -> existingUser && user?.mutable == true && draftShell.isNotBlank()
        UserWorkspaceAction.ToggleSudo -> existingUser && user?.mutable == true
        UserWorkspaceAction.SetPassword -> existingUser && user?.mutable == true && confirmation == username && password.isNotBlank() && password == confirmPassword
        UserWorkspaceAction.Remove -> existingUser && user?.mutable == true && confirmation == username
    }
    val reviewTitle = if (existingUser) {
        stringResource(R.string.user_action_review_title, username)
    } else {
        stringResource(R.string.user_add_review_title)
    }

    OutlinedCard(Modifier.fillMaxWidth().semantics { paneTitle = reviewTitle }) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                reviewTitle,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.semantics { heading() },
            )
            Text(stringResource(R.string.user_action_review_body, chroot), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            user?.let { currentUser ->
                ActionFlowRow(contentDescription = stringResource(R.string.user_action_review_actions_label)) {
                    actions.forEach { item ->
                        UserActionSelector(
                            action = item,
                            selected = item == action,
                            user = currentUser,
                            onSelect = { onClearUserPreview(); actionName = it.name },
                        )
                    }
                }
            }
            when (action) {
                UserWorkspaceAction.Add -> {
                    OutlinedTextField(value = draftUsername, onValueChange = { onClearUserPreview(); draftUsername = it }, label = { Text(stringResource(R.string.user_name_label)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(value = draftShell, onValueChange = { onClearUserPreview(); draftShell = it }, label = { Text(stringResource(R.string.user_shell_label)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    OutlinedButton(onClick = { onClearUserPreview(); draftSudo = !draftSudo }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                        Text(if (draftSudo) stringResource(R.string.user_add_sudo_enabled) else stringResource(R.string.user_add_sudo_disabled))
                    }
                }
                UserWorkspaceAction.SetShell -> OutlinedTextField(value = draftShell, onValueChange = { onClearUserPreview(); draftShell = it }, label = { Text(stringResource(R.string.user_shell_label)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                UserWorkspaceAction.SetPassword -> {
                    OutlinedTextField(value = confirmation, onValueChange = { onClearUserPreview(); confirmation = it }, label = { Text(stringResource(R.string.user_confirmation_exact_label, username)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(value = password, onValueChange = { onClearUserPreview(); password = it }, label = { Text(stringResource(R.string.user_password_label)) }, singleLine = true, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(value = confirmPassword, onValueChange = { onClearUserPreview(); confirmPassword = it }, label = { Text(stringResource(R.string.user_confirm_password_label)) }, singleLine = true, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
                }
                UserWorkspaceAction.Remove -> OutlinedTextField(value = confirmation, onValueChange = { onClearUserPreview(); confirmation = it }, label = { Text(stringResource(R.string.user_confirmation_exact_label, username)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                UserWorkspaceAction.SyncUidGid,
                UserWorkspaceAction.ToggleSudo -> Unit
            }
            Text(userActionReviewSummary(action, user, draftShell, draftSudo), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            ActionFlowRow {
                OutlinedButton(
                    onClick = { onPreviewUserPayload(payload) },
                    enabled = canSubmit,
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(stringResource(R.string.action_preview_command))
                }
                Button(
                    onClick = {
                        val dispatchPayload = payload
                        onStartUserOperation(operation, dispatchPayload)
                        if (action == UserWorkspaceAction.SetPassword) {
                            password = ""
                            confirmPassword = ""
                            confirmation = ""
                        }
                    },
                    enabled = canSubmit && preview.approvesOperation(operation),
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(userActionExecuteLabel(action, user))
                }
                TextButton(onClick = onCancel, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.action_cancel))
                }
            }
        }
    }
}

@Composable
private fun UserActionSelector(
    action: UserWorkspaceAction,
    selected: Boolean,
    user: UserSummary,
    onSelect: (UserWorkspaceAction) -> Unit,
) {
    val label = userActionSelectorLabel(action, user)
    if (selected) {
        Button(onClick = { onSelect(action) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(label) }
    } else {
        OutlinedButton(onClick = { onSelect(action) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(label) }
    }
}

@Composable
private fun userActionSelectorLabel(action: UserWorkspaceAction, user: UserSummary): String = when (action) {
    UserWorkspaceAction.Add -> stringResource(R.string.action_add_user)
    UserWorkspaceAction.SyncUidGid -> stringResource(R.string.action_sync_user)
    UserWorkspaceAction.SetShell -> stringResource(R.string.action_set_shell)
    UserWorkspaceAction.ToggleSudo -> if (user.sudo) stringResource(R.string.action_disable_sudo) else stringResource(R.string.action_enable_sudo)
    UserWorkspaceAction.SetPassword -> stringResource(R.string.action_set_password)
    UserWorkspaceAction.Remove -> stringResource(R.string.action_remove_user)
}

@Composable
private fun userActionExecuteLabel(action: UserWorkspaceAction, user: UserSummary?): String = when (action) {
    UserWorkspaceAction.Add -> stringResource(R.string.action_add_user)
    UserWorkspaceAction.SyncUidGid -> stringResource(R.string.action_sync_user)
    UserWorkspaceAction.SetShell -> stringResource(R.string.action_set_shell)
    UserWorkspaceAction.ToggleSudo -> if (user?.sudo == true) stringResource(R.string.action_disable_sudo) else stringResource(R.string.action_enable_sudo)
    UserWorkspaceAction.SetPassword -> stringResource(R.string.action_set_password)
    UserWorkspaceAction.Remove -> stringResource(R.string.action_remove_user)
}

@Composable
private fun userActionReviewSummary(
    action: UserWorkspaceAction,
    user: UserSummary?,
    shell: String,
    sudo: Boolean,
): String = when (action) {
    UserWorkspaceAction.Add -> stringResource(R.string.user_action_summary_add, shell, if (sudo) stringResource(R.string.user_add_sudo_enabled) else stringResource(R.string.user_add_sudo_disabled))
    UserWorkspaceAction.SyncUidGid -> stringResource(R.string.user_action_summary_sync)
    UserWorkspaceAction.SetShell -> stringResource(R.string.user_action_summary_shell, shell)
    UserWorkspaceAction.ToggleSudo -> stringResource(if (user?.sudo == true) R.string.user_action_summary_sudo_disable else R.string.user_action_summary_sudo_enable)
    UserWorkspaceAction.SetPassword -> stringResource(R.string.user_action_summary_password)
    UserWorkspaceAction.Remove -> stringResource(R.string.user_action_summary_remove)
}

private const val ADD_USER_REVIEW_TOKEN = "add:"
private const val USER_REVIEW_TOKEN_PREFIX = "user:"

private fun userReviewToken(username: String): String = USER_REVIEW_TOKEN_PREFIX + username

private fun reviewUsername(token: String): String? = token
    .takeIf { it.startsWith(USER_REVIEW_TOKEN_PREFIX) }
    ?.removePrefix(USER_REVIEW_TOKEN_PREFIX)
    ?.takeIf { it.isNotBlank() }

@Composable
private fun ServicesPanel(
    chroot: ChrootSummary,
    pane: ServicesPane,
    onRefreshServices: (String) -> Unit,
    onRefreshServiceDetail: (String, String) -> Unit,
    onPreviewServicePayload: (String) -> Unit,
    onClearServicePreview: () -> Unit,
    onStartServiceOperation: (String, String) -> Unit,
) {
    var filterName by rememberSaveable(chroot.name) { mutableStateOf(ServiceWorkspaceFilter.All.name) }
    var pendingActionToken by remember(chroot.name) { mutableStateOf("") }
    val filter = selectedServiceWorkspaceFilter(filterName)
    val serviceList = if (pane.targetName == chroot.name) pane.services else emptyList()
    val visibleServices = serviceList.filter { serviceMatchesWorkspaceFilter(it, filter) }
    val pendingServiceReview = pendingServiceActionToken(pendingActionToken)?.let { action ->
        serviceList.firstOrNull { it.chrootName == action.chrootName && it.service == action.service }
            ?.let { service -> service to action }
    }
    val paneState = workspacePaneState(pane.refreshing, pane.errorMessage, serviceList.isNotEmpty())
    val paneTitleText = stringResource(R.string.services_workspace_title)

    OutlinedCard(Modifier.fillMaxWidth().semantics { paneTitle = paneTitleText }) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(R.string.services_workspace_title), fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.services_workspace_body), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            ActionFlowRow(contentDescription = stringResource(R.string.services_workspace_filters_label)) {
                serviceWorkspaceFilters().forEach { item ->
                    ServiceFilterButton(
                        filter = item,
                        selected = item == filter,
                        onSelect = { filterName = it.name },
                    )
                }
            }
            ActionFlowRow {
                Button(
                    onClick = { onRefreshServices(chroot.name) },
                    enabled = !pane.refreshing,
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(if (pane.refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_services))
                }
            }
            WorkspacePaneFeedback(
                state = paneState,
                loadingLabel = stringResource(R.string.workspace_loading_services),
                emptyTitle = stringResource(R.string.services_workspace_empty_title),
                emptyBody = stringResource(R.string.services_list_empty),
                errorMessage = pane.errorMessage,
                onRetry = { onRefreshServices(chroot.name) },
            )
            pendingServiceReview?.let { (service, reviewAction) ->
                ServiceActionReviewSheet(
                    service = service,
                    action = reviewAction.action,
                    preview = pane.preview,
                    onCancel = { pendingActionToken = ""; onClearServicePreview() },
                    onPreviewServicePayload = onPreviewServicePayload,
                    onStartServiceOperation = onStartServiceOperation,
                )
            }
            pane.preview?.let { preview -> PreviewSummaryBlock(preview) }
            pane.selectedService?.takeIf { it.journalText.isNotBlank() }?.let { service ->
                StatusCard(
                    title = stringResource(R.string.service_journal_title, service.service),
                    body = service.journalText.take(MAX_JOURNAL_CHARS),
                )
            }
            when {
                paneState == WorkspacePaneState.Ready && visibleServices.isEmpty() -> EmptyState(
                    title = stringResource(R.string.services_workspace_no_matches_title),
                    body = stringResource(R.string.services_workspace_no_matches_body),
                )
                paneState == WorkspacePaneState.Ready -> visibleServices.forEach { service ->
                    FocusedServiceRow(
                        service = service,
                        onRefreshServiceDetail = onRefreshServiceDetail,
                        onSelectServiceAction = { selected, action ->
                            onClearServicePreview()
                            pendingActionToken = serviceActionToken(selected, action)
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun ServiceFilterButton(
    filter: ServiceWorkspaceFilter,
    selected: Boolean,
    onSelect: (ServiceWorkspaceFilter) -> Unit,
) {
    val label = when (filter) {
        ServiceWorkspaceFilter.All -> stringResource(R.string.service_filter_all)
        ServiceWorkspaceFilter.Running -> stringResource(R.string.service_filter_running)
        ServiceWorkspaceFilter.Enabled -> stringResource(R.string.service_filter_enabled)
        ServiceWorkspaceFilter.Stale -> stringResource(R.string.service_filter_stale)
        ServiceWorkspaceFilter.Failed -> stringResource(R.string.service_filter_failed)
    }
    if (selected) {
        Button(onClick = { onSelect(filter) }, modifier = Modifier.releaseSelectionSemantics(selected)) { Text(label) }
    } else {
        OutlinedButton(onClick = { onSelect(filter) }, modifier = Modifier.releaseSelectionSemantics(selected)) { Text(label) }
    }
}

@Composable
private fun FocusedServiceRow(
    service: ServiceUnitSummary,
    onRefreshServiceDetail: (String, String) -> Unit,
    onSelectServiceAction: (ServiceUnitSummary, String) -> Unit,
) {
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(service.service, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyMedium)
            Text(
                listOf(service.chrootName, service.description).filter { it.isNotBlank() }.joinToString(" · "),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            ActionFlowRow {
                StatusPill(service.status.ifBlank { stringResource(R.string.value_unknown) }, serviceStatusTone(service))
                StatusPill(if (service.enabled) stringResource(R.string.service_badge_enabled) else stringResource(R.string.service_badge_disabled), if (service.enabled) StatusTone.Success else StatusTone.Neutral)
                if (service.boot) StatusPill(stringResource(R.string.service_badge_boot), StatusTone.Accent)
                if (serviceNeedsAttention(service)) StatusPill(stringResource(R.string.status_needs_attention), StatusTone.Warning)
            }
            ActionFlowRow {
                Button(
                    onClick = { onRefreshServiceDetail(service.chrootName, service.service) },
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(stringResource(R.string.action_service_journal))
                }
                val primaryAction = if (serviceIsRunning(service)) "stop" else "start"
                Button(
                    onClick = { onSelectServiceAction(service, primaryAction) },
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(serviceActionLabel(primaryAction))
                }
                OutlinedButton(
                    onClick = { onSelectServiceAction(service, "restart") },
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(stringResource(R.string.action_service_restart))
                }
                OutlinedButton(
                    onClick = { onSelectServiceAction(service, if (service.enabled) "disable" else "enable") },
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(serviceActionLabel(if (service.enabled) "disable" else "enable"))
                }
            }
        }
    }
}

@Composable
private fun ServiceActionReviewSheet(
    service: ServiceUnitSummary,
    action: String,
    preview: PreviewSummary?,
    onCancel: () -> Unit,
    onPreviewServicePayload: (String) -> Unit,
    onStartServiceOperation: (String, String) -> Unit,
) {
    val payload = servicePayload(service.chrootName, service.service, action).toString()
    val operation = serviceActionOperation(action)
    val reviewTitle = stringResource(R.string.service_action_review_title, serviceActionLabel(action), service.service)
    OutlinedCard(Modifier.fillMaxWidth().semantics { paneTitle = reviewTitle }) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                reviewTitle,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.semantics { heading() },
            )
            Text(
                stringResource(R.string.service_action_review_body, service.chrootName),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            ActionFlowRow {
                OutlinedButton(onClick = { onPreviewServicePayload(payload) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.action_preview_command))
                }
                Button(onClick = { onStartServiceOperation(operation, payload) }, enabled = preview.approvesOperation(operation), modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(serviceActionLabel(action))
                }
                TextButton(onClick = onCancel, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.action_cancel))
                }
            }
        }
    }
}

@Composable
private fun serviceActionLabel(action: String): String = when (action) {
    "start" -> stringResource(R.string.action_service_start)
    "stop" -> stringResource(R.string.action_service_stop)
    "restart" -> stringResource(R.string.action_service_restart)
    "enable" -> stringResource(R.string.action_service_enable)
    "disable" -> stringResource(R.string.action_service_disable)
    else -> stringResource(R.string.action_service_start)
}

private fun serviceStatusTone(service: ServiceUnitSummary): StatusTone = when {
    serviceNeedsAttention(service) -> StatusTone.Warning
    serviceIsRunning(service) -> StatusTone.Success
    else -> StatusTone.Neutral
}

private fun serviceActionOperation(action: String): String = when (action) {
    "start" -> "services.start"
    "stop" -> "services.stop"
    "restart" -> "services.restart"
    "enable" -> "services.enable"
    "disable" -> "services.disable"
    else -> "services.start"
}

private data class PendingServiceAction(val chrootName: String, val service: String, val action: String)

private fun serviceActionToken(service: ServiceUnitSummary, action: String): String =
    listOf(service.chrootName, service.service, action).joinToString(SERVICE_ACTION_SEPARATOR)

private fun pendingServiceActionToken(token: String): PendingServiceAction? {
    val parts = token.split(SERVICE_ACTION_SEPARATOR)
    if (parts.size != 3 || parts.any { it.isBlank() }) return null
    return PendingServiceAction(parts[0], parts[1], parts[2])
}

private fun userPayload(chroot: String, username: String, action: String): JSONObject = JSONObject()
    .put("name", chroot)
    .put("username", username)
    .put("action", action)

private fun servicePayload(chroot: String, service: String, action: String): JSONObject = JSONObject()
    .put("name", chroot)
    .put("service", service)
    .put("action", action)

@Composable
private fun DetailRow(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
        Text(value, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun CheckRow(check: CheckSummary) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(stringResource(R.string.chroot_check_line, check.severity.uppercase(), check.title), fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
        Text(check.message, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
    }
}

private const val MAX_VISIBLE_SNAPSHOTS = 8
private const val MAX_JOURNAL_CHARS = 1_600
private const val MAX_OVERVIEW_CHECKS = 4
private const val MAX_VISIBLE_LOG_LINES = 80
private const val MAX_VISIBLE_LOG_OPERATIONS = 10
private const val MAX_RAW_PAYLOAD_CHARS = 4_000
private const val LOG_POLL_INTERVAL_MS = 5_000L
private const val SERVICE_ACTION_SEPARATOR = "\u001f"
