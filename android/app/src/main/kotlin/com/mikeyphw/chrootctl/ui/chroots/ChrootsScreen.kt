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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.CheckSummary
import com.mikeyphw.chrootctl.model.ChrootDetail
import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.ui.components.EmptyState
import com.mikeyphw.chrootctl.ui.components.PathText
import com.mikeyphw.chrootctl.ui.components.StatusCard

@Composable
fun ChrootsScreen(
    chroots: List<ChrootSummary>,
    selectedName: String?,
    detail: ChrootDetail,
    onSelect: (String) -> Unit,
    onRefreshDetail: () -> Unit,
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
                    onRefreshDetail = onRefreshDetail,
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
    onRefreshDetail: () -> Unit,
) {
    StatusCard(
        title = stringResource(R.string.chroot_detail_title, chroot.name),
        body = stringResource(R.string.chroot_detail_body),
        footer = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = onRefreshDetail, enabled = !refreshing) {
                    Text(if (refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.action_refresh_detail))
                }
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
