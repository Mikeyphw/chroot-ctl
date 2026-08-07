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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.CheckSummary
import com.mikeyphw.chrootctl.model.ChrootDetail
import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.PreviewSummary
import com.mikeyphw.chrootctl.model.SnapshotPane
import com.mikeyphw.chrootctl.model.SnapshotSummary
import com.mikeyphw.chrootctl.model.ServiceUnitSummary
import com.mikeyphw.chrootctl.model.ServicesPane
import com.mikeyphw.chrootctl.model.UserSummary
import com.mikeyphw.chrootctl.model.UsersPane
import com.mikeyphw.chrootctl.ui.ChrootLayout
import com.mikeyphw.chrootctl.ui.ChrootListFilter
import com.mikeyphw.chrootctl.ui.ChrootWorkspaceTab
import com.mikeyphw.chrootctl.ui.bridgeShapePrimaryMessage
import com.mikeyphw.chrootctl.ui.chrootListIsWorkspaceLauncherOnly
import com.mikeyphw.chrootctl.ui.chrootMatchesFilter
import com.mikeyphw.chrootctl.ui.chrootMatchesQuery
import com.mikeyphw.chrootctl.ui.chrootWorkspaceSummary
import com.mikeyphw.chrootctl.ui.chrootWorkspaceTabs
import com.mikeyphw.chrootctl.ui.isBridgeShapeError
import com.mikeyphw.chrootctl.ui.isRunningChrootStatus
import com.mikeyphw.chrootctl.ui.selectedChrootListFilter
import com.mikeyphw.chrootctl.ui.selectedChrootWorkspaceTab
import com.mikeyphw.chrootctl.ui.components.ActionFlowRow
import com.mikeyphw.chrootctl.ui.components.EmptyState
import com.mikeyphw.chrootctl.ui.components.MetricCardData
import com.mikeyphw.chrootctl.ui.components.PathText
import com.mikeyphw.chrootctl.ui.components.ResponsiveMetricCards
import com.mikeyphw.chrootctl.ui.components.SectionHeader
import com.mikeyphw.chrootctl.ui.components.StatusCard
import com.mikeyphw.chrootctl.ui.components.StatusPill
import com.mikeyphw.chrootctl.ui.components.StatusTone
import org.json.JSONObject

@Composable
fun ChrootsScreen(
    chroots: List<ChrootSummary>,
    selectedName: String?,
    detail: ChrootDetail,
    lifecyclePreview: PreviewSummary?,
    snapshotPane: SnapshotPane,
    usersPane: UsersPane,
    servicesPane: ServicesPane,
    onSelect: (String) -> Unit,
    onRefreshDetail: () -> Unit,
    onPreviewLifecycle: (String, String) -> Unit,
    onStartLifecycle: (String, String) -> Unit,
    onExecuteRemove: (String, String) -> Unit,
    onRefreshSnapshots: (String) -> Unit,
    onPreviewSnapshotCreate: (String) -> Unit,
    onStartSnapshotCreate: (String) -> Unit,
    onPreviewSnapshotAction: (String, String, String) -> Unit,
    onStartSnapshotRestore: (String, String, String) -> Unit,
    onStartSnapshotExport: (String, String) -> Unit,
    onRefreshUsers: (String) -> Unit,
    onPreviewUserPayload: (String) -> Unit,
    onStartUserOperation: (String, String) -> Unit,
    onRefreshServices: (String) -> Unit,
    onRefreshServiceDetail: (String, String) -> Unit,
    onPreviewServicePayload: (String) -> Unit,
    onStartServiceOperation: (String, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var filterName by rememberSaveable { mutableStateOf(ChrootListFilter.All.name) }
    var workspaceName by rememberSaveable { mutableStateOf(selectedName) }
    var workspaceTabName by rememberSaveable { mutableStateOf(ChrootWorkspaceTab.Overview.name) }
    val filter = selectedChrootListFilter(filterName)
    val workspaceTab = selectedChrootWorkspaceTab(workspaceTabName)
    val visibleChroots = chroots.filter { chroot ->
        chrootMatchesQuery(chroot, query) && chrootMatchesFilter(chroot, filter)
    }
    val workspaceChroot = workspaceName?.let { wanted ->
        detail.chroot?.takeIf { it.name == wanted } ?: chroots.firstOrNull { it.name == wanted }
    }

    if (workspaceName != null && workspaceChroot != null) {
        ChrootWorkspaceScreen(
            chroot = workspaceChroot,
            checks = detail.checks,
            refreshing = detail.refreshing,
            errorMessage = detail.errorMessage,
            selectedTab = workspaceTab,
            lifecyclePreview = lifecyclePreview,
            snapshotPane = snapshotPane,
            usersPane = usersPane,
            servicesPane = servicesPane,
            onBack = { workspaceName = null },
            onSelectTab = { workspaceTabName = it.name },
            onRefreshDetail = onRefreshDetail,
            onPreviewLifecycle = onPreviewLifecycle,
            onStartLifecycle = onStartLifecycle,
            onExecuteRemove = onExecuteRemove,
            onRefreshSnapshots = onRefreshSnapshots,
            onPreviewSnapshotCreate = onPreviewSnapshotCreate,
            onStartSnapshotCreate = onStartSnapshotCreate,
            onPreviewSnapshotAction = onPreviewSnapshotAction,
            onStartSnapshotRestore = onStartSnapshotRestore,
            onStartSnapshotExport = onStartSnapshotExport,
            onRefreshUsers = onRefreshUsers,
            onPreviewUserPayload = onPreviewUserPayload,
            onStartUserOperation = onStartUserOperation,
            onRefreshServices = onRefreshServices,
            onRefreshServiceDetail = onRefreshServiceDetail,
            onPreviewServicePayload = onPreviewServicePayload,
            onStartServiceOperation = onStartServiceOperation,
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
                onSelect(name)
            },
            onPreviewLifecycle = onPreviewLifecycle,
            onStartLifecycle = onStartLifecycle,
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
    onStartLifecycle: (String, String) -> Unit,
    onPreviewSnapshotCreate: (String) -> Unit,
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
                    onStartLifecycle = onStartLifecycle,
                    onPreviewSnapshotCreate = onPreviewSnapshotCreate,
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
        Button(onClick = { onSelect(filter) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(label) }
    } else {
        OutlinedButton(onClick = { onSelect(filter) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(label) }
    }
}

@Composable
private fun Phase32ChrootCard(
    chroot: ChrootSummary,
    selected: Boolean,
    onSelect: () -> Unit,
    onPreviewLifecycle: (String, String) -> Unit,
    onStartLifecycle: (String, String) -> Unit,
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
                if (chroot.warningCount > 0) StatusPill(stringResource(R.string.chroot_warnings_count, chroot.warningCount), StatusTone.Warning)
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
                    OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "restart") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                        Text(stringResource(R.string.action_preview_restart))
                    }
                    Button(onClick = { onStartLifecycle(chroot.name, "chroots.restart") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                        Text(stringResource(R.string.action_restart_chroot))
                    }
                } else {
                    OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "start") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                        Text(stringResource(R.string.action_preview_start))
                    }
                    Button(onClick = { onStartLifecycle(chroot.name, "chroots.start") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                        Text(stringResource(R.string.action_start_chroot))
                    }
                }
                OutlinedButton(onClick = { onPreviewSnapshotCreate(chroot.name) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(stringResource(R.string.action_preview_snapshot))
                }
            }
        }
    }
}

@Composable
private fun ChrootWorkspaceScreen(
    chroot: ChrootSummary,
    checks: List<CheckSummary>,
    refreshing: Boolean,
    errorMessage: String?,
    selectedTab: ChrootWorkspaceTab,
    lifecyclePreview: PreviewSummary?,
    snapshotPane: SnapshotPane,
    usersPane: UsersPane,
    servicesPane: ServicesPane,
    onBack: () -> Unit,
    onSelectTab: (ChrootWorkspaceTab) -> Unit,
    onRefreshDetail: () -> Unit,
    onPreviewLifecycle: (String, String) -> Unit,
    onStartLifecycle: (String, String) -> Unit,
    onExecuteRemove: (String, String) -> Unit,
    onRefreshSnapshots: (String) -> Unit,
    onPreviewSnapshotCreate: (String) -> Unit,
    onStartSnapshotCreate: (String) -> Unit,
    onPreviewSnapshotAction: (String, String, String) -> Unit,
    onStartSnapshotRestore: (String, String, String) -> Unit,
    onStartSnapshotExport: (String, String) -> Unit,
    onRefreshUsers: (String) -> Unit,
    onPreviewUserPayload: (String) -> Unit,
    onStartUserOperation: (String, String) -> Unit,
    onRefreshServices: (String) -> Unit,
    onRefreshServiceDetail: (String, String) -> Unit,
    onPreviewServicePayload: (String) -> Unit,
    onStartServiceOperation: (String, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(14.dp)) {
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
                ChrootWorkspaceTabButton(tab = tab, selected = tab == selectedTab, onSelect = onSelectTab)
            }
        }
        when (selectedTab) {
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
                onOpenTab = onSelectTab,
            )
            ChrootWorkspaceTab.Services -> ServicesPanel(
                chroot = chroot,
                pane = servicesPane,
                onRefreshServices = onRefreshServices,
                onRefreshServiceDetail = onRefreshServiceDetail,
                onPreviewServicePayload = onPreviewServicePayload,
                onStartServiceOperation = onStartServiceOperation,
            )
            ChrootWorkspaceTab.Users -> UsersPanel(
                chroot = chroot,
                pane = usersPane,
                onRefreshUsers = onRefreshUsers,
                onPreviewUserPayload = onPreviewUserPayload,
                onStartUserOperation = onStartUserOperation,
            )
            ChrootWorkspaceTab.Snapshots -> SnapshotPanel(
                chroot = chroot,
                pane = snapshotPane,
                onRefreshSnapshots = onRefreshSnapshots,
                onPreviewSnapshotCreate = onPreviewSnapshotCreate,
                onStartSnapshotCreate = onStartSnapshotCreate,
                onPreviewSnapshotAction = onPreviewSnapshotAction,
                onStartSnapshotRestore = onStartSnapshotRestore,
                onStartSnapshotExport = onStartSnapshotExport,
            )
            ChrootWorkspaceTab.Advanced -> AdvancedWorkspaceTab(
                chroot = chroot,
                checks = checks,
                lifecyclePreview = lifecyclePreview,
                onPreviewLifecycle = onPreviewLifecycle,
                onStartLifecycle = onStartLifecycle,
                onExecuteRemove = onExecuteRemove,
            )
        }
    }
}

@Composable
private fun ChrootWorkspaceTabButton(tab: ChrootWorkspaceTab, selected: Boolean, onSelect: (ChrootWorkspaceTab) -> Unit) {
    val label = when (tab) {
        ChrootWorkspaceTab.Overview -> stringResource(R.string.chroot_workspace_tab_overview)
        ChrootWorkspaceTab.Services -> stringResource(R.string.chroot_workspace_tab_services)
        ChrootWorkspaceTab.Users -> stringResource(R.string.chroot_workspace_tab_users)
        ChrootWorkspaceTab.Snapshots -> stringResource(R.string.chroot_workspace_tab_snapshots)
        ChrootWorkspaceTab.Advanced -> stringResource(R.string.chroot_workspace_tab_advanced)
    }
    if (selected) {
        Button(onClick = { onSelect(tab) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(label) }
    } else {
        OutlinedButton(onClick = { onSelect(tab) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(label) }
    }
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
    onPreviewSnapshotCreate: (String) -> Unit,
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
                            Button(onClick = { onStartLifecycle(chroot.name, "chroots.restart") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                                Text(stringResource(R.string.action_restart_chroot))
                            }
                        } else {
                            Button(onClick = { onStartLifecycle(chroot.name, "chroots.start") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                                Text(stringResource(R.string.action_start_chroot))
                            }
                        }
                        OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "upgrade") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                            Text(stringResource(R.string.action_preview_upgrade))
                        }
                        OutlinedButton(onClick = { onPreviewSnapshotCreate(chroot.name) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                            Text(stringResource(R.string.action_preview_snapshot))
                        }
                    }
                    ActionFlowRow {
                        OutlinedButton(onClick = { onOpenTab(ChrootWorkspaceTab.Services) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.chroot_workspace_open_services)) }
                        OutlinedButton(onClick = { onOpenTab(ChrootWorkspaceTab.Users) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.chroot_workspace_open_users)) }
                        OutlinedButton(onClick = { onOpenTab(ChrootWorkspaceTab.Snapshots) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.chroot_workspace_open_snapshots)) }
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
                            Text(stringResource(R.string.chroot_workspace_checks_more, checks.size - MAX_OVERVIEW_CHECKS), color = MaterialTheme.colorScheme.onSurfaceVariant)
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
    lifecyclePreview: PreviewSummary?,
    onPreviewLifecycle: (String, String) -> Unit,
    onStartLifecycle: (String, String) -> Unit,
    onExecuteRemove: (String, String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        LifecyclePanel(
            chroot = chroot,
            preview = lifecyclePreview,
            onPreviewLifecycle = onPreviewLifecycle,
            onStartLifecycle = onStartLifecycle,
            onExecuteRemove = onExecuteRemove,
        )
        StatusCard(
            title = stringResource(R.string.chroot_workspace_advanced_diagnostics_title),
            body = stringResource(R.string.chroot_workspace_advanced_diagnostics_body),
            footer = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    DetailRow(stringResource(R.string.chroot_detail_status), chroot.status)
                    DetailRow(stringResource(R.string.chroot_detail_release), listOfNotNull(chroot.distribution, chroot.release, chroot.architecture).joinToString(" · ").ifBlank { stringResource(R.string.value_not_reported) })
                    DetailRow(stringResource(R.string.chroot_detail_path), chroot.path ?: stringResource(R.string.value_not_reported))
                    DetailRow(stringResource(R.string.chroot_detail_raw_size), chroot.rawJson.length.toString())
                    if (checks.isEmpty()) {
                        Text(stringResource(R.string.chroot_detail_checks_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else {
                        checks.forEach { check -> CheckRow(check) }
                    }
                }
            },
        )
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
                Button(onClick = { onStartLifecycle(chroot.name, "chroots.start") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_start_chroot)) }
                OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "restart") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_preview_restart)) }
                Button(onClick = { onStartLifecycle(chroot.name, "chroots.restart") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_restart_chroot)) }
                OutlinedButton(onClick = { onPreviewLifecycle(chroot.name, "upgrade") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_preview_upgrade)) }
                Button(onClick = { onStartLifecycle(chroot.name, "chroots.upgrade") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_upgrade_chroot)) }
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
                enabled = removeConfirmation == chroot.name,
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
    onRefreshSnapshots: (String) -> Unit,
    onPreviewSnapshotCreate: (String) -> Unit,
    onStartSnapshotCreate: (String) -> Unit,
    onPreviewSnapshotAction: (String, String, String) -> Unit,
    onStartSnapshotRestore: (String, String, String) -> Unit,
    onStartSnapshotExport: (String, String) -> Unit,
) {
    var restoreConfirmation by remember(chroot.name) { mutableStateOf("") }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.snapshot_actions_title), fontWeight = FontWeight.SemiBold)
            ActionFlowRow {
                Button(onClick = { onRefreshSnapshots(chroot.name) }, enabled = !pane.refreshing) {
                    Text(if (pane.refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_snapshots))
                }
                Button(onClick = { onPreviewSnapshotCreate(chroot.name) }) { Text(stringResource(R.string.action_preview_snapshot)) }
            }
            Button(onClick = { onStartSnapshotCreate(chroot.name) }) { Text(stringResource(R.string.action_create_snapshot)) }
            OutlinedTextField(
                value = restoreConfirmation,
                onValueChange = { restoreConfirmation = it },
                label = { Text(stringResource(R.string.snapshot_restore_confirmation_label, chroot.name)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            pane.errorMessage?.let { message -> BridgePaneError(message = message, onRetry = { onRefreshSnapshots(chroot.name) }) }
            pane.preview?.let { preview -> PreviewSummaryBlock(preview) }
            if (pane.targetName == chroot.name && pane.snapshots.isNotEmpty()) {
                pane.snapshots.take(MAX_VISIBLE_SNAPSHOTS).forEach { snapshot ->
                    SnapshotRow(
                        snapshot = snapshot,
                        restoreConfirmation = restoreConfirmation,
                        onPreviewSnapshotAction = onPreviewSnapshotAction,
                        onStartSnapshotRestore = onStartSnapshotRestore,
                        onStartSnapshotExport = onStartSnapshotExport,
                    )
                }
            } else {
                Text(stringResource(R.string.snapshot_list_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
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
private fun SnapshotRow(
    snapshot: SnapshotSummary,
    restoreConfirmation: String,
    onPreviewSnapshotAction: (String, String, String) -> Unit,
    onStartSnapshotRestore: (String, String, String) -> Unit,
    onStartSnapshotExport: (String, String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(snapshot.name, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
        Text(listOf(snapshot.kind, snapshot.createdAt, snapshot.sizeBytes.toString()).joinToString(" · "), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        ActionFlowRow {
            Button(onClick = { onPreviewSnapshotAction(snapshot.chrootName, snapshot.name, "restore") }) { Text(stringResource(R.string.action_preview_restore_snapshot)) }
            Button(
                onClick = { onStartSnapshotRestore(snapshot.chrootName, snapshot.name, restoreConfirmation) },
                enabled = restoreConfirmation == snapshot.chrootName,
            ) {
                Text(stringResource(R.string.action_restore_snapshot))
            }
        }
        ActionFlowRow {
            Button(onClick = { onPreviewSnapshotAction(snapshot.chrootName, snapshot.name, "export") }) { Text(stringResource(R.string.action_preview_export_snapshot)) }
            Button(onClick = { onStartSnapshotExport(snapshot.chrootName, snapshot.name) }) { Text(stringResource(R.string.action_export_snapshot)) }
        }
    }
}

@Composable
private fun UsersPanel(
    chroot: ChrootSummary,
    pane: UsersPane,
    onRefreshUsers: (String) -> Unit,
    onPreviewUserPayload: (String) -> Unit,
    onStartUserOperation: (String, String) -> Unit,
) {
    var username by remember(chroot.name) { mutableStateOf("") }
    var shell by remember(chroot.name) { mutableStateOf("/bin/bash") }
    var sudo by remember(chroot.name) { mutableStateOf(false) }
    var confirmation by remember(chroot.name) { mutableStateOf("") }
    var password by remember(chroot.name) { mutableStateOf("") }
    var confirmPassword by remember(chroot.name) { mutableStateOf("") }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.users_actions_title), fontWeight = FontWeight.SemiBold)
            Button(onClick = { onRefreshUsers(chroot.name) }, enabled = !pane.refreshing) {
                Text(if (pane.refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_users))
            }
            OutlinedTextField(value = username, onValueChange = { username = it }, label = { Text(stringResource(R.string.user_name_label)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(value = shell, onValueChange = { shell = it }, label = { Text(stringResource(R.string.user_shell_label)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Button(onClick = { sudo = !sudo }) { Text(if (sudo) stringResource(R.string.action_disable_sudo_choice) else stringResource(R.string.action_enable_sudo_choice)) }
            val addPayload = userPayload(chroot.name, username, "add").put("shell", shell).put("sudo", sudo).toString()
            ActionFlowRow {
                Button(onClick = { onPreviewUserPayload(addPayload) }, enabled = username.isNotBlank()) { Text(stringResource(R.string.action_preview_add_user)) }
                Button(onClick = { onStartUserOperation("users.add", addPayload) }, enabled = username.isNotBlank()) { Text(stringResource(R.string.action_add_user)) }
            }
            OutlinedTextField(value = confirmation, onValueChange = { confirmation = it }, label = { Text(stringResource(R.string.user_confirmation_label)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(value = password, onValueChange = { password = it }, label = { Text(stringResource(R.string.user_password_label)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(value = confirmPassword, onValueChange = { confirmPassword = it }, label = { Text(stringResource(R.string.user_confirm_password_label)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            pane.errorMessage?.let { message -> BridgePaneError(message = message, onRetry = { onRefreshUsers(chroot.name) }) }
            pane.preview?.let { preview -> PreviewSummaryBlock(preview) }
            if (pane.targetName == chroot.name && pane.users.isNotEmpty()) {
                pane.users.forEach { user ->
                    UserRow(
                        chroot = chroot.name,
                        user = user,
                        shell = shell,
                        confirmation = confirmation,
                        password = password,
                        confirmPassword = confirmPassword,
                        onPreviewUserPayload = onPreviewUserPayload,
                        onStartUserOperation = onStartUserOperation,
                    )
                }
            } else {
                Text(stringResource(R.string.users_list_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun UserRow(
    chroot: String,
    user: UserSummary,
    shell: String,
    confirmation: String,
    password: String,
    confirmPassword: String,
    onPreviewUserPayload: (String) -> Unit,
    onStartUserOperation: (String, String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(user.username, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
        Text(listOf("uid=${user.uid}", "gid=${user.gid}", user.shell, if (user.sudo) "sudo" else "no sudo").joinToString(" · "), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        ActionFlowRow {
            val syncPayload = userPayload(chroot, user.username, "sync_uid_gid").put("fixOwnership", true).toString()
            Button(onClick = { onPreviewUserPayload(syncPayload) }) { Text(stringResource(R.string.action_preview_sync_user)) }
            Button(onClick = { onStartUserOperation("users.sync_uid_gid", syncPayload) }) { Text(stringResource(R.string.action_sync_user)) }
        }
        ActionFlowRow {
            val shellPayload = userPayload(chroot, user.username, "set_shell").put("shell", shell).toString()
            Button(onClick = { onPreviewUserPayload(shellPayload) }) { Text(stringResource(R.string.action_preview_set_shell)) }
            Button(onClick = { onStartUserOperation("users.set_shell", shellPayload) }) { Text(stringResource(R.string.action_set_shell)) }
        }
        ActionFlowRow {
            val sudoPayload = userPayload(chroot, user.username, "set_sudo").put("enabled", !user.sudo).toString()
            Button(onClick = { onPreviewUserPayload(sudoPayload) }) { Text(stringResource(R.string.action_preview_sudo)) }
            Button(onClick = { onStartUserOperation("users.set_sudo", sudoPayload) }) { Text(if (user.sudo) stringResource(R.string.action_disable_sudo) else stringResource(R.string.action_enable_sudo)) }
        }
        ActionFlowRow {
            val passwordPayload = userPayload(chroot, user.username, "set_password").put("password", password).put("confirmPassword", confirmPassword).put("confirmation", confirmation).toString()
            Button(onClick = { onPreviewUserPayload(passwordPayload) }) { Text(stringResource(R.string.action_preview_password)) }
            Button(onClick = { onStartUserOperation("users.set_password", passwordPayload) }, enabled = confirmation == user.username && password.isNotBlank() && password == confirmPassword) { Text(stringResource(R.string.action_set_password)) }
        }
        ActionFlowRow {
            val removePayload = userPayload(chroot, user.username, "remove").put("confirmation", confirmation).put("deleteHome", false).toString()
            Button(onClick = { onPreviewUserPayload(removePayload) }) { Text(stringResource(R.string.action_preview_remove_user)) }
            Button(onClick = { onStartUserOperation("users.remove", removePayload) }, enabled = confirmation == user.username) { Text(stringResource(R.string.action_remove_user)) }
        }
    }
}

@Composable
private fun ServicesPanel(
    chroot: ChrootSummary,
    pane: ServicesPane,
    onRefreshServices: (String) -> Unit,
    onRefreshServiceDetail: (String, String) -> Unit,
    onPreviewServicePayload: (String) -> Unit,
    onStartServiceOperation: (String, String) -> Unit,
) {
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.services_actions_title), fontWeight = FontWeight.SemiBold)
            Button(onClick = { onRefreshServices(chroot.name) }, enabled = !pane.refreshing) {
                Text(if (pane.refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_services))
            }
            pane.errorMessage?.let { message -> BridgePaneError(message = message, onRetry = { onRefreshServices(chroot.name) }) }
            pane.preview?.let { preview -> PreviewSummaryBlock(preview) }
            pane.selectedService?.takeIf { it.journalText.isNotBlank() }?.let { service ->
                Text(stringResource(R.string.service_journal_title, service.service), fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
                Text(service.journalText.take(MAX_JOURNAL_CHARS), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            }
            if (pane.targetName == chroot.name && pane.services.isNotEmpty()) {
                pane.services.forEach { service ->
                    ServiceRow(
                        service = service,
                        onRefreshServiceDetail = onRefreshServiceDetail,
                        onPreviewServicePayload = onPreviewServicePayload,
                        onStartServiceOperation = onStartServiceOperation,
                    )
                }
            } else {
                Text(stringResource(R.string.services_list_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun ServiceRow(
    service: ServiceUnitSummary,
    onRefreshServiceDetail: (String, String) -> Unit,
    onPreviewServicePayload: (String) -> Unit,
    onStartServiceOperation: (String, String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(service.service, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
        Text(listOf(service.chrootName, service.status, if (service.enabled) "enabled" else "disabled", service.description).filter { it.isNotBlank() }.joinToString(" · "), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        Button(onClick = { onRefreshServiceDetail(service.chrootName, service.service) }) { Text(stringResource(R.string.action_service_journal)) }
        ActionFlowRow {
            ServiceActionButton(service, "start", R.string.action_service_start, onPreviewServicePayload, onStartServiceOperation)
            ServiceActionButton(service, "stop", R.string.action_service_stop, onPreviewServicePayload, onStartServiceOperation)
            ServiceActionButton(service, "restart", R.string.action_service_restart, onPreviewServicePayload, onStartServiceOperation)
        }
        ActionFlowRow {
            ServiceActionButton(service, "enable", R.string.action_service_enable, onPreviewServicePayload, onStartServiceOperation)
            ServiceActionButton(service, "disable", R.string.action_service_disable, onPreviewServicePayload, onStartServiceOperation)
        }
    }
}

@Composable
private fun ServiceActionButton(
    service: ServiceUnitSummary,
    action: String,
    labelRes: Int,
    onPreviewServicePayload: (String) -> Unit,
    onStartServiceOperation: (String, String) -> Unit,
) {
    val payload = servicePayload(service.chrootName, service.service, action).toString()
    val operation = when (action) {
        "start" -> "services.start"
        "stop" -> "services.stop"
        "restart" -> "services.restart"
        "enable" -> "services.enable"
        "disable" -> "services.disable"
        else -> "services.start"
    }
    ActionFlowRow {
        Button(onClick = { onPreviewServicePayload(payload) }) { Text(stringResource(R.string.action_preview_short)) }
        Button(onClick = { onStartServiceOperation(operation, payload) }) { Text(stringResource(labelRes)) }
    }
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
