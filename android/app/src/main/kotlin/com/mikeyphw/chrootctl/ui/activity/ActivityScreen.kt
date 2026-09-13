package com.mikeyphw.chrootctl.ui.activity

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.OperationDetail
import com.mikeyphw.chrootctl.model.OperationEventSummary
import com.mikeyphw.chrootctl.model.OperationSummary
import com.mikeyphw.chrootctl.ui.ChrootLayout
import com.mikeyphw.chrootctl.ui.OperationActivityFilter
import com.mikeyphw.chrootctl.ui.canCancelOperation
import com.mikeyphw.chrootctl.ui.canOpenSnapshotRecovery
import com.mikeyphw.chrootctl.ui.canRetryOperation
import com.mikeyphw.chrootctl.ui.canRetryWithFixes
import com.mikeyphw.chrootctl.ui.components.EmptyState
import com.mikeyphw.chrootctl.ui.components.ProgressRow
import com.mikeyphw.chrootctl.ui.components.StatusCard
import com.mikeyphw.chrootctl.ui.visibleOperations

@Composable
fun ActivityScreen(
    operations: List<OperationSummary>,
    selectedOperationId: String?,
    detail: OperationDetail,
    onSelect: (String) -> Unit,
    onRefreshDetail: () -> Unit,
    onCancelOperation: (String) -> Unit,
    onRetryOperation: (String) -> Unit,
    onRetryWithFixes: (String) -> Unit,
    onRecoverLatestSnapshot: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var filterName by rememberSaveable { mutableStateOf(OperationActivityFilter.All.name) }
    val filter = OperationActivityFilter.entries.firstOrNull { it.name == filterName } ?: OperationActivityFilter.All
    val visible = visibleOperations(operations, filter)
    // Destructive recovery confirmations are intentionally not saveable across
    // process death; the user must re-open and re-confirm stale-sensitive retry
    // actions after Activity recreation.
    var previewRetryOperation by remember { mutableStateOf<String?>(null) }
    var previewRetryWithFixes by remember { mutableStateOf(false) }

    Column(modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ActivityFilterRow(
            selected = filter,
            onSelected = { filterName = it.name },
        )
        if (operations.isEmpty()) {
            EmptyState(
                title = stringResource(R.string.activity_empty_title),
                body = stringResource(R.string.activity_empty_body),
            )
        } else if (visible.isEmpty()) {
            EmptyState(
                title = stringResource(R.string.activity_empty_title),
                body = "No operations match the selected recovery filter.",
            )
        } else {
            visible.forEach { operation ->
                OperationCard(
                    operation = operation,
                    selected = operation.operationId == selectedOperationId,
                    onSelect = { onSelect(operation.operationId) },
                    onCancel = { onCancelOperation(operation.operationId) },
                    onPreviewRetry = {
                        previewRetryOperation = operation.operationId
                        previewRetryWithFixes = false
                    },
                    onPreviewRetryWithFixes = {
                        previewRetryOperation = operation.operationId
                        previewRetryWithFixes = true
                    },
                    onRecoverSnapshot = { onRecoverLatestSnapshot(operation.operationId) },
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

    previewRetryOperation?.let { operationId ->
        val operation = operations.firstOrNull { it.operationId == operationId }
        RetryPreviewDialog(
            operation = operation,
            repair = previewRetryWithFixes,
            onDismiss = { previewRetryOperation = null },
            onRetry = {
                previewRetryOperation = null
                if (previewRetryWithFixes) {
                    onRetryWithFixes(operationId)
                } else {
                    onRetryOperation(operationId)
                }
            },
        )
    }
}

@Composable
private fun ActivityFilterRow(selected: OperationActivityFilter, onSelected: (OperationActivityFilter) -> Unit) {
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        OperationActivityFilter.entries.forEach { filter ->
            FilterChip(
                selected = selected == filter,
                onClick = { onSelected(filter) },
                modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                label = { Text(filter.label) },
            )
        }
    }
}

@Composable
private fun OperationCard(
    operation: OperationSummary,
    selected: Boolean,
    onSelect: () -> Unit,
    onCancel: () -> Unit,
    onPreviewRetry: () -> Unit,
    onPreviewRetryWithFixes: () -> Unit,
    onRecoverSnapshot: () -> Unit,
) {
    val container: @Composable (Modifier, @Composable () -> Unit) -> Unit = if (selected) {
        { modifier, content -> OutlinedCard(modifier, content = { content() }) }
    } else {
        { modifier, content -> Card(modifier, content = { content() }) }
    }
    container(Modifier.fillMaxWidth().clickable(onClick = onSelect)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(operation.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(operation.state, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelLarge)
            }
            Text(
                stringResource(R.string.operation_state_line, operation.kind, operation.state),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            operation.targetName?.let { target ->
                Text(stringResource(R.string.home_operation_target, target), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            ProgressRow(
                label = operation.phase ?: stringResource(R.string.value_no_phase),
                detail = operation.errorMessage ?: operation.progressText,
                percent = operation.progressPercent,
            )
            if (operation.stale || operation.missingInBackend) {
                Text(
                    if (operation.missingInBackend) stringResource(R.string.operation_missing_backend) else stringResource(R.string.operation_stale_cache),
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            operation.errorCode?.let { code ->
                Text(stringResource(R.string.operation_error_code, code), color = MaterialTheme.colorScheme.error)
            }
            if (operation.parentOperationId != null) {
                Text(stringResource(R.string.operation_parent_line, operation.parentOperationId), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (operation.nextSteps.isNotEmpty()) {
                Text(stringResource(R.string.operation_next_steps_line, operation.nextSteps.joinToString(" • ")), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (operation.canCancelOperation()) {
                    OutlinedButton(onClick = onCancel, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.operation_cancel_action)) }
                }
                if (operation.canRetryOperation()) {
                    OutlinedButton(onClick = onPreviewRetry, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.operation_retry_preview_action)) }
                }
                if (operation.canRetryWithFixes()) {
                    Button(onClick = onPreviewRetryWithFixes, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.operation_retry_fixes_preview_action)) }
                }
                if (operation.canOpenSnapshotRecovery()) {
                    OutlinedButton(onClick = onRecoverSnapshot, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.operation_restore_latest_preview_action)) }
                }
            }
        }
    }
}

@Composable
private fun RetryPreviewDialog(operation: OperationSummary?, repair: Boolean, onDismiss: () -> Unit, onRetry: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.operation_recovery_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(operation?.title ?: stringResource(R.string.value_not_reported), fontWeight = FontWeight.SemiBold)
                Text(if (repair) stringResource(R.string.operation_retry_fixes_preview_body) else stringResource(R.string.operation_retry_preview_body))
                operation?.targetName?.let { Text(stringResource(R.string.home_operation_target, it)) }
                operation?.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                operation?.nextSteps?.takeIf { it.isNotEmpty() }?.let { steps ->
                    Text(stringResource(R.string.operation_next_steps_line, steps.joinToString(" • ")))
                }
                operation?.warnings?.takeIf { it.isNotEmpty() }?.let { warnings ->
                    Text(stringResource(R.string.operation_warnings_line, warnings.joinToString(" • ")), color = MaterialTheme.colorScheme.error)
                }
            }
        },
        confirmButton = { Button(onClick = onRetry, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(if (repair) stringResource(R.string.operation_retry_fixes_action) else stringResource(R.string.operation_retry_action)) } },
        dismissButton = { TextButton(onClick = onDismiss, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_back)) } },
    )
}

@Composable
private fun OperationDetailCard(
    operation: OperationSummary,
    events: List<OperationEventSummary>,
    refreshing: Boolean,
    errorMessage: String?,
    onRefreshDetail: () -> Unit,
) {
    var showAllEvents by rememberSaveable(operation.operationId) { mutableStateOf(false) }
    val visibleEvents = if (showAllEvents) events.takeLast(MAX_EXPANDED_EVENTS) else events.takeLast(MAX_VISIBLE_EVENTS)
    StatusCard(
        title = stringResource(R.string.operation_detail_title, operation.operationId),
        body = stringResource(R.string.operation_detail_body),
        footer = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = onRefreshDetail, enabled = !refreshing, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(if (refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_detail))
                }
                errorMessage?.let { message -> Text(message, color = MaterialTheme.colorScheme.error) }
                DetailRow(stringResource(R.string.operation_detail_state), operation.state)
                DetailRow(stringResource(R.string.operation_detail_target), operation.targetName ?: stringResource(R.string.value_not_reported))
                DetailRow(stringResource(R.string.operation_detail_created), operation.createdAt.toString())
                operation.parentOperationId?.let { DetailRow(stringResource(R.string.operation_detail_parent), it) }
                operation.detailRefreshAt?.let { DetailRow(stringResource(R.string.operation_detail_refreshed), it.toString()) }
                operation.reconciledAt?.let { DetailRow(stringResource(R.string.operation_detail_reconciled), it.toString()) }
                if (operation.resultJson != null) DetailRow(stringResource(R.string.operation_detail_result), operation.resultJson)
                if (operation.nextSteps.isNotEmpty()) DetailRow(stringResource(R.string.operation_detail_next_steps), operation.nextSteps.joinToString(" • "))
                if (operation.warnings.isNotEmpty()) DetailRow(stringResource(R.string.operation_detail_warnings), operation.warnings.joinToString(" • "))
                Text("Event timeline", fontWeight = FontWeight.SemiBold)
                if (events.isEmpty()) {
                    Text(stringResource(R.string.operation_detail_events_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
                } else {
                    visibleEvents.forEach { event -> OperationEventRow(event) }
                    if (events.size > MAX_VISIBLE_EVENTS) {
                        TextButton(onClick = { showAllEvents = !showAllEvents }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                            Text(if (showAllEvents) stringResource(R.string.action_show_less) else stringResource(R.string.action_show_more))
                        }
                    }
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
private const val MAX_EXPANDED_EVENTS = 80
