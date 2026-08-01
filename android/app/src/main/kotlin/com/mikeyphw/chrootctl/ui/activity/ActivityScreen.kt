package com.mikeyphw.chrootctl.ui.activity

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.OperationDetail
import com.mikeyphw.chrootctl.model.OperationEventSummary
import com.mikeyphw.chrootctl.model.OperationSummary
import com.mikeyphw.chrootctl.ui.components.EmptyState
import com.mikeyphw.chrootctl.ui.components.ProgressRow
import com.mikeyphw.chrootctl.ui.components.StatusCard

@Composable
fun ActivityScreen(
    operations: List<OperationSummary>,
    selectedOperationId: String?,
    detail: OperationDetail,
    onSelect: (String) -> Unit,
    onRefreshDetail: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (operations.isEmpty()) {
            EmptyState(
                title = stringResource(R.string.activity_empty_title),
                body = stringResource(R.string.activity_empty_body),
            )
        } else {
            operations.forEach { operation ->
                OperationCard(
                    operation = operation,
                    selected = operation.operationId == selectedOperationId,
                    onSelect = { onSelect(operation.operationId) },
                )
            }
            detail.operation?.let { operation ->
                OperationDetailCard(
                    operation = operation,
                    events = detail.events,
                    refreshing = detail.refreshing,
                    errorMessage = detail.errorMessage,
                    onRefreshDetail = onRefreshDetail,
                )
            }
        }
    }
}

@Composable
private fun OperationCard(operation: OperationSummary, selected: Boolean, onSelect: () -> Unit) {
    val container: @Composable (Modifier, @Composable () -> Unit) -> Unit = if (selected) {
        { modifier, content -> OutlinedCard(modifier, content = { content() }) }
    } else {
        { modifier, content -> Card(modifier, content = { content() }) }
    }
    container(Modifier.fillMaxWidth().clickable(onClick = onSelect)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(operation.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                stringResource(R.string.operation_state_line, operation.kind, operation.state),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            ProgressRow(
                label = operation.phase ?: stringResource(R.string.value_no_phase),
                detail = operation.errorMessage ?: operation.progressText,
                percent = operation.progressPercent,
            )
            operation.errorCode?.let { code ->
                Text(stringResource(R.string.operation_error_code, code), color = MaterialTheme.colorScheme.error)
            }
        }
    }
}

@Composable
private fun OperationDetailCard(
    operation: OperationSummary,
    events: List<OperationEventSummary>,
    refreshing: Boolean,
    errorMessage: String?,
    onRefreshDetail: () -> Unit,
) {
    StatusCard(
        title = stringResource(R.string.operation_detail_title, operation.operationId),
        body = stringResource(R.string.operation_detail_body),
        footer = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = onRefreshDetail, enabled = !refreshing) {
                    Text(if (refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_detail))
                }
                errorMessage?.let { message -> Text(message, color = MaterialTheme.colorScheme.error) }
                DetailRow(stringResource(R.string.operation_detail_state), operation.state)
                DetailRow(stringResource(R.string.operation_detail_target), operation.targetName ?: stringResource(R.string.value_not_reported))
                DetailRow(stringResource(R.string.operation_detail_created), operation.createdAt.toString())
                if (events.isEmpty()) {
                    Text(stringResource(R.string.operation_detail_events_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
                } else {
                    events.takeLast(MAX_VISIBLE_EVENTS).forEach { event -> OperationEventRow(event) }
                }
            }
        },
    )
}

@Composable
private fun DetailRow(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
        Text(value, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun OperationEventRow(event: OperationEventSummary) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(stringResource(R.string.operation_event_line, event.type, event.message), fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
        Text(event.timestamp.toString(), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
    }
}

private const val MAX_VISIBLE_EVENTS = 20
