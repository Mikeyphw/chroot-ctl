package com.mikeyphw.chrootctl.ui.home

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.HomeSnapshot
import com.mikeyphw.chrootctl.model.Loadable
import com.mikeyphw.chrootctl.model.OperationSummary
import com.mikeyphw.chrootctl.model.ReadinessState
import com.mikeyphw.chrootctl.ui.BackendIssueKind
import com.mikeyphw.chrootctl.ui.ChrootLayout
import com.mikeyphw.chrootctl.ui.ChrootSpacing
import com.mikeyphw.chrootctl.ui.RefreshState
import com.mikeyphw.chrootctl.ui.classifyBackendIssue
import com.mikeyphw.chrootctl.ui.components.ActionFlowRow
import com.mikeyphw.chrootctl.ui.components.AppCard
import com.mikeyphw.chrootctl.ui.components.DashboardLoadingState
import com.mikeyphw.chrootctl.ui.components.MetricCardData
import com.mikeyphw.chrootctl.ui.components.RecoverableErrorState
import com.mikeyphw.chrootctl.ui.components.RefreshFailureBanner
import com.mikeyphw.chrootctl.ui.components.ResponsiveMetricCards
import com.mikeyphw.chrootctl.ui.components.SectionHeader
import com.mikeyphw.chrootctl.ui.components.StatusPill
import com.mikeyphw.chrootctl.ui.components.StatusTone
import com.mikeyphw.chrootctl.ui.isRunningChrootStatus
import com.mikeyphw.chrootctl.ui.isRunningOperationState

@Composable
fun HomeScreen(
    state: Loadable<HomeSnapshot>,
    chroots: List<ChrootSummary>,
    operations: List<OperationSummary>,
    refreshState: RefreshState,
    onRefresh: () -> Unit,
    onStartRefreshOperation: () -> Unit,
    onOpenChroots: () -> Unit,
    onOpenInstall: () -> Unit,
    onOpenActivity: () -> Unit,
    onRequestNotificationPermission: () -> Unit,
    notificationsEnabled: Boolean,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(ChrootSpacing.md)) {
        when (state) {
            Loadable.Loading -> {
                val failure = refreshState as? RefreshState.Failed
                if (failure != null) {
                    InitialBackendFailure(message = failure.message, onRetry = onRefresh)
                } else {
                    DashboardLoadingState(
                        label = stringResource(R.string.status_checking_runtime),
                        supportingText = stringResource(R.string.home_loading_supporting),
                        metrics = loadingMetrics(),
                    )
                }
            }
            is Loadable.Blocked -> InitialBackendFailure(message = state.message, onRetry = onRefresh)
            is Loadable.Ready -> HomeReady(
                snapshot = state.value,
                chroots = chroots,
                operations = operations,
                refreshState = refreshState,
                onRefresh = onRefresh,
                onStartRefreshOperation = onStartRefreshOperation,
                onOpenChroots = onOpenChroots,
                onOpenInstall = onOpenInstall,
                onOpenActivity = onOpenActivity,
                onRequestNotificationPermission = onRequestNotificationPermission,
                notificationsEnabled = notificationsEnabled,
            )
        }
    }
}

@Composable
private fun InitialBackendFailure(message: String, onRetry: () -> Unit) {
    val copy = backendIssueCopy(classifyBackendIssue(message))
    RecoverableErrorState(
        title = copy.title,
        body = copy.body,
        technicalDetails = message,
        attentionLabel = stringResource(R.string.status_needs_attention),
        retryLabel = stringResource(R.string.action_retry),
        showDetailsLabel = stringResource(R.string.action_show_technical_details),
        hideDetailsLabel = stringResource(R.string.action_hide_technical_details),
        onRetry = onRetry,
    )
}

@Composable
private fun HomeReady(
    snapshot: HomeSnapshot,
    chroots: List<ChrootSummary>,
    operations: List<OperationSummary>,
    refreshState: RefreshState,
    onRefresh: () -> Unit,
    onStartRefreshOperation: () -> Unit,
    onOpenChroots: () -> Unit,
    onOpenInstall: () -> Unit,
    onOpenActivity: () -> Unit,
    onRequestNotificationPermission: () -> Unit,
    notificationsEnabled: Boolean,
) {
    if (refreshState is RefreshState.Failed) {
        val copy = backendIssueCopy(classifyBackendIssue(refreshState.message))
        RefreshFailureBanner(
            title = copy.title,
            body = stringResource(R.string.home_cached_refresh_failure_body, copy.body),
            technicalDetails = refreshState.message,
            retryLabel = stringResource(R.string.action_reconnect),
            showDetailsLabel = stringResource(R.string.action_show_technical_details),
            hideDetailsLabel = stringResource(R.string.action_hide_technical_details),
            onRetry = onRefresh,
        )
    }

    DashboardOverview(
        snapshot = snapshot,
        chroots = chroots,
        operations = operations,
        refreshState = refreshState,
        onRefresh = onRefresh,
        onOpenChroots = onOpenChroots,
        onOpenInstall = onOpenInstall,
        onOpenActivity = onOpenActivity,
    )

    SectionHeader(
        title = stringResource(R.string.home_metrics_title),
        body = stringResource(R.string.home_metrics_body),
    )
    val runningChroots = chroots.count { isRunningChrootStatus(it.status) }
    val runningOperations = operations.count { isRunningOperationState(it.state) }
    ResponsiveMetricCards(
        cards = listOf(
            MetricCardData(
                label = stringResource(R.string.metric_running_chroots),
                value = runningChroots.toString(),
                detail = pluralStringResource(R.plurals.metric_running_chroots_detail, snapshot.chrootCount, snapshot.chrootCount),
            ),
            MetricCardData(
                label = stringResource(R.string.metric_active_operations),
                value = runningOperations.toString(),
                detail = pluralStringResource(R.plurals.metric_active_operations_detail, snapshot.operationCount, snapshot.operationCount),
            ),
            MetricCardData(
                label = stringResource(R.string.metric_warnings),
                value = snapshot.warningCount.toString(),
                detail = stringResource(R.string.metric_warnings_detail),
            ),
        ),
    )

    RecentActivityCard(operations = operations, onOpenActivity = onOpenActivity)
    ReleaseReadinessCard(snapshot)

    if (!notificationsEnabled) {
        AppCard {
            Text(
                stringResource(R.string.notifications_permission_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.semantics { heading() },
            )
            Text(
                stringResource(R.string.notifications_permission_body),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            ActionFlowRow {
                OutlinedButton(
                    onClick = onStartRefreshOperation,
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) { Text(stringResource(R.string.action_run_refresh_operation)) }
                OutlinedButton(
                    onClick = onRequestNotificationPermission,
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) { Text(stringResource(R.string.notifications_permission_action)) }
            }
        }
    }
}

@Composable
private fun DashboardOverview(
    snapshot: HomeSnapshot,
    chroots: List<ChrootSummary>,
    operations: List<OperationSummary>,
    refreshState: RefreshState,
    onRefresh: () -> Unit,
    onOpenChroots: () -> Unit,
    onOpenInstall: () -> Unit,
    onOpenActivity: () -> Unit,
) {
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val expanded = maxWidth >= ChrootLayout.ExpandedMetricBreakpoint
        if (expanded) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.md)) {
                HomeHero(
                    snapshot = snapshot,
                    refreshState = refreshState,
                    onRefresh = onRefresh,
                    onOpenChroots = onOpenChroots,
                    onOpenInstall = onOpenInstall,
                    onOpenActivity = onOpenActivity,
                    modifier = Modifier.weight(1.25f),
                )
                SystemHealthCard(
                    snapshot = snapshot,
                    chroots = chroots,
                    operations = operations,
                    modifier = Modifier.weight(0.75f),
                )
            }
        } else {
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(ChrootSpacing.md)) {
                HomeHero(
                    snapshot = snapshot,
                    refreshState = refreshState,
                    onRefresh = onRefresh,
                    onOpenChroots = onOpenChroots,
                    onOpenInstall = onOpenInstall,
                    onOpenActivity = onOpenActivity,
                )
                SystemHealthCard(snapshot = snapshot, chroots = chroots, operations = operations)
            }
        }
    }
}

@Composable
private fun HomeHero(
    snapshot: HomeSnapshot,
    refreshState: RefreshState,
    onRefresh: () -> Unit,
    onOpenChroots: () -> Unit,
    onOpenInstall: () -> Unit,
    onOpenActivity: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val blocked = snapshot.readinessRows.any { it.state == ReadinessState.Blocked }
    val tone = when {
        blocked -> StatusTone.Danger
        snapshot.stale || snapshot.warningCount > 0 -> StatusTone.Warning
        else -> StatusTone.Success
    }
    val statusLabel = when {
        refreshState is RefreshState.Refreshing -> stringResource(R.string.status_refreshing)
        snapshot.stale -> stringResource(R.string.status_cached_data)
        blocked -> stringResource(R.string.status_needs_attention)
        snapshot.warningCount > 0 -> stringResource(R.string.status_review_recommended)
        else -> stringResource(R.string.status_everything_operational)
    }
    Card(
        modifier = modifier.fillMaxWidth().heightIn(min = 260.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(
            Modifier.fillMaxWidth().padding(ChrootSpacing.xl),
            verticalArrangement = Arrangement.spacedBy(ChrootSpacing.md),
        ) {
            StatusPill(label = statusLabel, tone = tone)
            Text(
                stringResource(R.string.home_hero_title),
                style = MaterialTheme.typography.headlineLarge,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.semantics { heading() },
            )
            Text(
                stringResource(R.string.home_hero_body),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyLarge,
            )
            if (snapshot.recommendedAction.title.isNotBlank() || snapshot.recommendedAction.body.isNotBlank()) {
                Column(verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xxs)) {
                    Text(
                        snapshot.recommendedAction.title,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        snapshot.recommendedAction.body,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            val recommendedActionLabel = snapshot.recommendedAction.actionLabel
                .takeIf { it.isNotBlank() }
                ?: stringResource(R.string.home_action_open_chroots)
            ActionFlowRow {
                Button(
                    onClick = when (snapshot.recommendedAction.destination) {
                        "activity" -> onOpenActivity
                        "chroots" -> onOpenChroots
                        "install" -> onOpenInstall
                        "refresh" -> onRefresh
                        else -> onOpenChroots
                    },
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) { Text(recommendedActionLabel) }
                OutlinedButton(
                    onClick = onOpenInstall,
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) { Text(stringResource(R.string.home_action_new_chroot)) }
                OutlinedButton(
                    onClick = onOpenChroots,
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) { Text(stringResource(R.string.home_action_open_chroots)) }
                TextButton(
                    onClick = onOpenActivity,
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) { Text(stringResource(R.string.action_open_activity)) }
                TextButton(
                    onClick = onRefresh,
                    enabled = refreshState !is RefreshState.Refreshing,
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) { Text(stringResource(R.string.action_refresh)) }
            }
        }
    }
}

@Composable
private fun SystemHealthCard(
    snapshot: HomeSnapshot,
    chroots: List<ChrootSummary>,
    operations: List<OperationSummary>,
    modifier: Modifier = Modifier,
) {
    var binaryDetailsExpanded by rememberSaveable { mutableStateOf(false) }
    val readyRows = snapshot.readinessRows.count { it.state == ReadinessState.Ready }
    val runningChroots = chroots.count { isRunningChrootStatus(it.status) }
    val activeOperations = operations.count { isRunningOperationState(it.state) }
    AppCard(modifier) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.sm),
            verticalAlignment = Alignment.Top,
        ) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xxs)) {
                Text(
                    stringResource(R.string.home_system_health_title),
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.semantics { heading() },
                )
                Text(
                    stringResource(R.string.home_system_health_body),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            StatusPill(
                label = pluralStringResource(R.plurals.home_health_ready_count, snapshot.readinessRows.size, readyRows, snapshot.readinessRows.size),
                tone = if (readyRows == snapshot.readinessRows.size) StatusTone.Success else StatusTone.Warning,
            )
        }
        HealthRow(
            label = stringResource(R.string.home_health_root_service),
            detail = stringResource(R.string.home_health_root_service_detail, snapshot.bridgeInfo.backend, snapshot.bridgeInfo.pid),
            state = if (snapshot.bridgeInfo.ok) ReadinessState.Ready else ReadinessState.Blocked,
        )
        snapshot.bridgeInfo.binaryResolutionJson?.let { raw ->
            TextButton(onClick = { binaryDetailsExpanded = !binaryDetailsExpanded }) {
                Text(if (binaryDetailsExpanded) "Hide binary technical details" else "Binary technical details")
            }
            if (binaryDetailsExpanded) {
                val detail = runCatching { org.json.JSONObject(raw).toString(2) }.getOrDefault(raw)
                Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        HealthRow(
            label = stringResource(R.string.home_health_runtime),
            detail = stringResource(
                R.string.home_health_runtime_detail,
                snapshot.capabilities.backendVersion,
                snapshot.capabilities.protocolVersion,
            ),
            state = if (snapshot.capabilities.protocolVersion == 1) ReadinessState.Ready else ReadinessState.Warning,
        )
        HealthRow(
            label = stringResource(R.string.home_health_chroots),
            detail = pluralStringResource(R.plurals.home_health_chroots_detail, runningChroots, runningChroots, snapshot.chrootCount),
            state = if (snapshot.warningCount == 0) ReadinessState.Ready else ReadinessState.Warning,
        )
        HealthRow(
            label = stringResource(R.string.home_health_operations),
            detail = pluralStringResource(R.plurals.home_health_operations_detail, activeOperations, activeOperations),
            state = ReadinessState.Ready,
        )
    }
}

@Composable
private fun RecentActivityCard(operations: List<OperationSummary>, onOpenActivity: () -> Unit) {
    val recent = operations.sortedByDescending { it.createdAt }.take(3)
    AppCard {
        SectionHeader(
            title = stringResource(R.string.home_recent_activity_title),
            body = stringResource(R.string.home_recent_activity_body),
            action = {
                TextButton(onClick = onOpenActivity) { Text(stringResource(R.string.action_see_all)) }
            },
        )
        if (recent.isEmpty()) {
            Text(
                stringResource(R.string.activity_empty_body),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            recent.forEach { operation -> OperationRow(operation) }
        }
    }
}

@Composable
private fun OperationRow(operation: OperationSummary) {
    val targetName = operation.targetName?.takeIf { it.isNotBlank() }
    val targetDetail = if (targetName != null) {
        stringResource(R.string.home_operation_target, targetName)
    } else {
        operation.progressText
    }
    val tone = when {
        operation.state.equals("failed", ignoreCase = true) -> StatusTone.Danger
        isRunningOperationState(operation.state) -> StatusTone.Accent
        operation.state.equals("completed", ignoreCase = true) || operation.state.equals("succeeded", ignoreCase = true) -> StatusTone.Success
        else -> StatusTone.Neutral
    }
    Row(
        Modifier.fillMaxWidth().padding(vertical = ChrootSpacing.xs),
        horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.sm),
        verticalAlignment = Alignment.Top,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xxs)) {
            Text(operation.title, fontWeight = FontWeight.SemiBold)
            Text(
                targetDetail,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        StatusPill(label = operation.state, tone = tone)
    }
}

@Composable
private fun ReleaseReadinessCard(snapshot: HomeSnapshot) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    AppCard {
        Text(
            stringResource(R.string.home_readiness_title),
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.SemiBold,
        )
        SectionHeader(
            title = stringResource(R.string.release_readiness_title),
            body = snapshot.releaseReadiness.body,
            action = {
                TextButton(onClick = { expanded = !expanded }) {
                    Text(stringResource(if (expanded) R.string.action_show_less else R.string.action_show_more))
                }
            },
        )
        if (expanded) {
            snapshot.releaseReadiness.rows.forEach { row -> HealthRow(row.label, row.detail, row.state) }
        }
    }
}

@Composable
private fun HealthRow(label: String, detail: String, state: ReadinessState) {
    val marker = when (state) {
        ReadinessState.Ready -> stringResource(R.string.state_ready_marker)
        ReadinessState.Warning -> stringResource(R.string.state_warning_marker)
        ReadinessState.Blocked -> stringResource(R.string.state_blocked_marker)
    }
    val tone = when (state) {
        ReadinessState.Ready -> StatusTone.Success
        ReadinessState.Warning -> StatusTone.Warning
        ReadinessState.Blocked -> StatusTone.Danger
    }
    Row(
        Modifier.fillMaxWidth().padding(vertical = ChrootSpacing.xs),
        horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.sm),
        verticalAlignment = Alignment.Top,
    ) {
        StatusPill(label = marker, tone = tone)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xxs)) {
            Text(label, fontWeight = FontWeight.SemiBold)
            Text(detail, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun loadingMetrics(): List<MetricCardData> = listOf(
    MetricCardData(
        label = stringResource(R.string.metric_running_chroots),
        value = stringResource(R.string.value_loading_dash),
        detail = stringResource(R.string.metric_loading_detail),
    ),
    MetricCardData(
        label = stringResource(R.string.metric_active_operations),
        value = stringResource(R.string.value_loading_dash),
        detail = stringResource(R.string.metric_loading_detail),
    ),
    MetricCardData(
        label = stringResource(R.string.metric_warnings),
        value = stringResource(R.string.value_loading_dash),
        detail = stringResource(R.string.metric_loading_detail),
    ),
)

private data class BackendIssueCopy(val title: String, val body: String)

@Composable
private fun backendIssueCopy(kind: BackendIssueKind): BackendIssueCopy = when (kind) {
    BackendIssueKind.ServiceDisconnected -> BackendIssueCopy(
        stringResource(R.string.backend_issue_disconnected_title),
        stringResource(R.string.backend_issue_disconnected_body),
    )
    BackendIssueKind.Timeout -> BackendIssueCopy(
        stringResource(R.string.backend_issue_timeout_title),
        stringResource(R.string.backend_issue_timeout_body),
    )
    BackendIssueKind.InvalidResponse -> BackendIssueCopy(
        stringResource(R.string.backend_issue_invalid_response_title),
        stringResource(R.string.backend_issue_invalid_response_body),
    )
    BackendIssueKind.PermissionDenied -> BackendIssueCopy(
        stringResource(R.string.backend_issue_permission_title),
        stringResource(R.string.backend_issue_permission_body),
    )
    BackendIssueKind.RuntimeMissing -> BackendIssueCopy(
        stringResource(R.string.backend_issue_runtime_title),
        stringResource(R.string.backend_issue_runtime_body),
    )
    BackendIssueKind.Unknown -> BackendIssueCopy(
        stringResource(R.string.backend_issue_unknown_title),
        stringResource(R.string.backend_issue_unknown_body),
    )
}
