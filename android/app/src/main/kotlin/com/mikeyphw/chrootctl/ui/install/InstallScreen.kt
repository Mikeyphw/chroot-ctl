package com.mikeyphw.chrootctl.ui.install

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.InstallDraft
import com.mikeyphw.chrootctl.model.InstallFormSummary
import com.mikeyphw.chrootctl.model.PreviewSummary
import com.mikeyphw.chrootctl.ui.components.ChipRow
import com.mikeyphw.chrootctl.ui.components.StatusCard

@Composable
fun InstallScreen(
    draft: InstallDraft,
    form: InstallFormSummary,
    preview: PreviewSummary?,
    onDraftChange: (InstallDraft) -> Unit,
    onRefreshForm: () -> Unit,
    onPreview: () -> Unit,
    onStartInstall: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        StatusCard(
            title = stringResource(R.string.install_native_title),
            body = stringResource(R.string.install_native_body),
            footer = {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        OutlinedButton(onClick = onRefreshForm, enabled = !form.refreshing) {
                            Text(if (form.refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.install_refresh_options))
                        }
                        Button(onClick = onPreview) { Text(stringResource(R.string.install_preview_action)) }
                    }
                    form.errorMessage?.let { message -> Text(message, color = MaterialTheme.colorScheme.error) }
                    OptionLine(stringResource(R.string.install_form_distros), form.distros)
                    OptionLine(stringResource(R.string.install_form_profiles), form.profiles)
                    OptionLine(stringResource(R.string.install_form_desktops), form.desktops)
                }
            },
        )
        InstallDraftCard(draft = draft, onDraftChange = onDraftChange)
        preview?.let { summary -> PreviewCard(summary = summary, onStartInstall = onStartInstall) }
    }
}

@Composable
private fun InstallDraftCard(draft: InstallDraft, onDraftChange: (InstallDraft) -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(R.string.install_request_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = draft.distro,
                    onValueChange = { onDraftChange(draft.copy(distro = it)) },
                    label = { Text(stringResource(R.string.install_field_distro)) },
                    modifier = Modifier.weight(1f),
                )
                OutlinedTextField(
                    value = draft.name,
                    onValueChange = { onDraftChange(draft.copy(name = it)) },
                    label = { Text(stringResource(R.string.install_field_name)) },
                    modifier = Modifier.weight(1f),
                )
            }
            OutlinedTextField(
                value = draft.username,
                onValueChange = { onDraftChange(draft.copy(username = it)) },
                label = { Text(stringResource(R.string.install_field_username)) },
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = draft.profile,
                    onValueChange = { onDraftChange(draft.copy(profile = it)) },
                    label = { Text(stringResource(R.string.install_field_profile)) },
                    modifier = Modifier.weight(1f),
                )
                OutlinedTextField(
                    value = draft.desktop,
                    onValueChange = { onDraftChange(draft.copy(desktop = it)) },
                    label = { Text(stringResource(R.string.install_field_desktop)) },
                    modifier = Modifier.weight(1f),
                )
            }
            OutlinedTextField(
                value = draft.mirror,
                onValueChange = { onDraftChange(draft.copy(mirror = it)) },
                label = { Text(stringResource(R.string.install_field_mirror)) },
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun PreviewCard(summary: PreviewSummary, onStartInstall: () -> Unit) {
    StatusCard(
        title = summary.title,
        body = summary.body,
        footer = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    if (summary.ok) stringResource(R.string.preview_ready) else stringResource(R.string.preview_blocked),
                    color = if (summary.ok) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                    fontWeight = FontWeight.SemiBold,
                )
                if (summary.blocking.isNotEmpty()) OptionLine(stringResource(R.string.preview_blocking), summary.blocking)
                if (summary.warnings.isNotEmpty()) OptionLine(stringResource(R.string.preview_warnings), summary.warnings)
                Button(onClick = onStartInstall, enabled = summary.ok) { Text(stringResource(R.string.install_start_action)) }
            }
        },
    )
}

@Composable
private fun OptionLine(label: String, values: List<String>) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
        if (values.isEmpty()) {
            Text(stringResource(R.string.value_not_reported), color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            ChipRow(values.take(MAX_VISIBLE_OPTIONS))
        }
    }
}

private const val MAX_VISIBLE_OPTIONS = 8
