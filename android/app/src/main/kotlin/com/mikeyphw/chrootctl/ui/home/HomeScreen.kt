package com.mikeyphw.chrootctl.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.HomeSnapshot
import com.mikeyphw.chrootctl.model.Loadable
import com.mikeyphw.chrootctl.model.ReadinessState
import com.mikeyphw.chrootctl.ui.RefreshState
import com.mikeyphw.chrootctl.ui.components.LoadingState
import com.mikeyphw.chrootctl.ui.components.MetricCard
import com.mikeyphw.chrootctl.ui.components.StatusCard

@Composable
fun HomeScreen(
    state: Loadable<HomeSnapshot>,
    refreshState: RefreshState,
    onRefresh: () -> Unit,
    onStartRefreshOperation: () -> Unit,
    onOpenActivity: () -> Unit,
    onRequestNotificationPermission: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(16.dp)) {
        when (state) {
            Loadable.Loading -> LoadingState(stringResource(R.string.status_checking_runtime))
            is Loadable.Blocked -> StatusCard(
                title = stringResource(R.string.status_backend_unavailable),
                body = state.message,
                footer = { Button(onClick = onRefresh) { Text(stringResource(R.string.action_retry)) } },
            )
            is Loadable.Ready -> HomeReady(
                snapshot = state.value,
                refreshState = refreshState,
                onRefresh = onRefresh,
                onStartRefreshOperation = onStartRefreshOperation,
                onOpenActivity = onOpenActivity,
                onRequestNotificationPermission = onRequestNotificationPermission,
            )
        }
    }
}

@Composable
private fun HomeReady(
    snapshot: HomeSnapshot,
    refreshState: RefreshState,
    onRefresh: () -> Unit,
    onStartRefreshOperation: () -> Unit,
    onOpenActivity: () -> Unit,
    onRequestNotificationPermission: () -> Unit,
) {
    StatusCard(
        title = snapshot.recommendedAction.title,
        body = snapshot.recommendedAction.body,
        footer = {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = onRefresh, enabled = refreshState !is RefreshState.Refreshing) {
                    Text(stringResource(R.string.action_refresh))
                }
                Button(onClick = onStartRefreshOperation) { Text(stringResource(R.string.action_run_refresh_operation)) }
                Button(onClick = onOpenActivity) { Text(stringResource(R.string.action_open_activity)) }
            }
        },
    )
    FlowRow(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        MetricCard(
            label = stringResource(R.string.metric_chroots),
            value = snapshot.chrootCount.toString(),
            detail = stringResource(R.string.metric_chroots_detail),
            modifier = Modifier.weight(1f),
        )
        MetricCard(
            label = stringResource(R.string.metric_operations),
            value = snapshot.operationCount.toString(),
            detail = stringResource(R.string.metric_operations_detail),
            modifier = Modifier.weight(1f),
        )
        MetricCard(
            label = stringResource(R.string.metric_warnings),
            value = snapshot.warningCount.toString(),
            detail = stringResource(R.string.metric_warnings_detail),
            modifier = Modifier.weight(1f),
        )
    }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(
                stringResource(R.string.home_readiness_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.fillMaxWidth(),
            )
            snapshot.readinessRows.forEach { row ->
                ReadinessRow(label = row.label, detail = row.detail, state = row.state)
            }
        }
    }
    ReleaseReadinessCard(snapshot)

    StatusCard(
        title = stringResource(R.string.notifications_permission_title),
        body = stringResource(R.string.notifications_permission_body),
        footer = { Button(onClick = onRequestNotificationPermission) { Text(stringResource(R.string.notifications_permission_action)) } },
    )
    if (refreshState is RefreshState.Failed) {
        StatusCard(title = stringResource(R.string.refresh_failed_title), body = refreshState.message)
    }
}

@Composable
private fun ReleaseReadinessCard(snapshot: HomeSnapshot) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(
                stringResource(R.string.release_readiness_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(snapshot.releaseReadiness.body, color = MaterialTheme.colorScheme.onSurfaceVariant)
            snapshot.releaseReadiness.rows.forEach { row ->
                ReadinessRow(label = row.label, detail = row.detail, state = row.state)
            }
        }
    }
}

@Composable
private fun ReadinessRow(label: String, detail: String, state: ReadinessState) {
    val marker = when (state) {
        ReadinessState.Ready -> stringResource(R.string.state_ready_marker)
        ReadinessState.Warning -> stringResource(R.string.state_warning_marker)
        ReadinessState.Blocked -> stringResource(R.string.state_blocked_marker)
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(marker)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(label, fontWeight = FontWeight.SemiBold)
            Text(detail, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        }
    }
}
