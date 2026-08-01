package com.mikeyphw.chrootctl.ui.chroots

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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import com.mikeyphw.chrootctl.ui.components.EmptyState
import com.mikeyphw.chrootctl.ui.components.PathText
import com.mikeyphw.chrootctl.ui.components.StatusCard

@Composable
fun ChrootsScreen(
    chroots: List<ChrootSummary>,
    selectedName: String?,
    detail: ChrootDetail,
    lifecyclePreview: PreviewSummary?,
    snapshotPane: SnapshotPane,
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
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        if (chroots.isEmpty()) {
            EmptyState(
                title = stringResource(R.string.chroots_empty_title),
                body = stringResource(R.string.chroots_empty_body),
            )
        } else {
            chroots.forEach { chroot ->
                ChrootCard(
                    chroot = chroot,
                    selected = chroot.name == selectedName,
                    onSelect = { onSelect(chroot.name) },
                )
            }
            detail.chroot?.let { chroot ->
                ChrootDetailCard(
                    chroot = chroot,
                    checks = detail.checks,
                    refreshing = detail.refreshing,
                    errorMessage = detail.errorMessage,
                    lifecyclePreview = lifecyclePreview,
                    snapshotPane = snapshotPane,
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
                )
            }
        }
    }
}

@Composable
private fun ChrootCard(chroot: ChrootSummary, selected: Boolean, onSelect: () -> Unit) {
    val container: @Composable (Modifier, @Composable () -> Unit) -> Unit = if (selected) {
        { modifier, content -> OutlinedCard(modifier, content = { content() }) }
    } else {
        { modifier, content -> Card(modifier, content = { content() }) }
    }
    container(Modifier.fillMaxWidth().clickable(onClick = onSelect)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(chroot.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                Text(chroot.status, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(
                listOfNotNull(chroot.distribution, chroot.release, chroot.architecture).joinToString(" · ").ifBlank {
                    stringResource(R.string.chroot_unknown_distribution)
                },
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            chroot.path?.let { path -> PathText(path) }
            Text(
                stringResource(
                    R.string.chroot_health_line,
                    chroot.mountState ?: stringResource(R.string.value_unknown),
                    chroot.health ?: stringResource(R.string.value_not_reported),
                    chroot.warningCount,
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun ChrootDetailCard(
    chroot: ChrootSummary,
    checks: List<CheckSummary>,
    refreshing: Boolean,
    errorMessage: String?,
    lifecyclePreview: PreviewSummary?,
    snapshotPane: SnapshotPane,
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
) {
    StatusCard(
        title = stringResource(R.string.chroot_detail_title, chroot.name),
        body = stringResource(R.string.chroot_detail_body),
        footer = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = onRefreshDetail, enabled = !refreshing) {
                    Text(if (refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_detail))
                }
                LifecyclePanel(
                    chroot = chroot,
                    preview = lifecyclePreview,
                    onPreviewLifecycle = onPreviewLifecycle,
                    onStartLifecycle = onStartLifecycle,
                    onExecuteRemove = onExecuteRemove,
                )
                SnapshotPanel(
                    chroot = chroot,
                    pane = snapshotPane,
                    onRefreshSnapshots = onRefreshSnapshots,
                    onPreviewSnapshotCreate = onPreviewSnapshotCreate,
                    onStartSnapshotCreate = onStartSnapshotCreate,
                    onPreviewSnapshotAction = onPreviewSnapshotAction,
                    onStartSnapshotRestore = onStartSnapshotRestore,
                    onStartSnapshotExport = onStartSnapshotExport,
                )
                errorMessage?.let { message -> Text(message, color = MaterialTheme.colorScheme.error) }
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
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onPreviewLifecycle(chroot.name, "start") }) { Text(stringResource(R.string.action_preview_start)) }
                Button(onClick = { onStartLifecycle(chroot.name, "chroots.start") }) { Text(stringResource(R.string.action_start_chroot)) }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onPreviewLifecycle(chroot.name, "restart") }) { Text(stringResource(R.string.action_preview_restart)) }
                Button(onClick = { onStartLifecycle(chroot.name, "chroots.restart") }) { Text(stringResource(R.string.action_restart_chroot)) }
            }
            Button(onClick = { onPreviewLifecycle(chroot.name, "remove") }) { Text(stringResource(R.string.action_preview_remove)) }
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
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
            pane.errorMessage?.let { message -> Text(message, color = MaterialTheme.colorScheme.error) }
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
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onPreviewSnapshotAction(snapshot.chrootName, snapshot.name, "restore") }) { Text(stringResource(R.string.action_preview_restore_snapshot)) }
            Button(
                onClick = { onStartSnapshotRestore(snapshot.chrootName, snapshot.name, restoreConfirmation) },
                enabled = restoreConfirmation == snapshot.chrootName,
            ) {
                Text(stringResource(R.string.action_restore_snapshot))
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onPreviewSnapshotAction(snapshot.chrootName, snapshot.name, "export") }) { Text(stringResource(R.string.action_preview_export_snapshot)) }
            Button(onClick = { onStartSnapshotExport(snapshot.chrootName, snapshot.name) }) { Text(stringResource(R.string.action_export_snapshot)) }
        }
    }
}

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
