package com.mikeyphw.chrootctl.ui.install

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.InstallDraft
import com.mikeyphw.chrootctl.model.InstallFormSummary
import com.mikeyphw.chrootctl.model.PreviewSummary
import com.mikeyphw.chrootctl.model.approvesOperation
import com.mikeyphw.chrootctl.ui.ChrootLayout
import com.mikeyphw.chrootctl.ui.ChrootSpacing
import com.mikeyphw.chrootctl.ui.InstallDraftValidation
import com.mikeyphw.chrootctl.ui.validateInstallDraft
import com.mikeyphw.chrootctl.ui.components.ActionFlowRow
import com.mikeyphw.chrootctl.ui.components.ChipRow
import com.mikeyphw.chrootctl.ui.components.SectionHeader
import com.mikeyphw.chrootctl.ui.components.StatusCard
import com.mikeyphw.chrootctl.ui.components.StatusPill
import com.mikeyphw.chrootctl.ui.components.StatusTone

enum class InstallWizardStep {
    ChooseSystem,
    Configure,
    Review,
}

@Composable
fun InstallScreen(
    draft: InstallDraft,
    form: InstallFormSummary,
    preview: PreviewSummary?,
    onDraftChange: (InstallDraft) -> Unit,
    onRefreshForm: () -> Unit,
    onPreview: () -> Unit,
    onStartInstall: () -> Unit,
    onOpenActivity: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var stepName by rememberSaveable { mutableStateOf(InstallWizardStep.ChooseSystem.name) }
    val step = InstallWizardStep.entries.firstOrNull { it.name == stepName } ?: InstallWizardStep.ChooseSystem
    val validation = validateInstallDraft(draft)

    Column(modifier, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        SectionHeader(
            title = stringResource(R.string.install_phase32_title),
            body = stringResource(R.string.install_phase32_body),
            action = {
                OutlinedButton(onClick = onRefreshForm, enabled = !form.refreshing, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                    Text(if (form.refreshing) stringResource(R.string.action_refreshing) else stringResource(R.string.install_refresh_options))
                }
            },
        )
        InstallWizardStepper(step = step, onSelect = { stepName = it.name })
        form.errorMessage?.let { message -> Text(message, color = MaterialTheme.colorScheme.error) }
        when (step) {
            InstallWizardStep.ChooseSystem -> DistroChoiceStep(draft, form, validation, onDraftChange)
            InstallWizardStep.Configure -> ConfigureInstallStep(draft, form, validation, onDraftChange)
            InstallWizardStep.Review -> ReviewInstallStep(draft, validation, preview, onPreview, onStartInstall, onOpenActivity)
        }
        InstallWizardFooter(
            step = step,
            validation = validation,
            onBack = {
                stepName = when (step) {
                    InstallWizardStep.ChooseSystem -> InstallWizardStep.ChooseSystem.name
                    InstallWizardStep.Configure -> InstallWizardStep.ChooseSystem.name
                    InstallWizardStep.Review -> InstallWizardStep.Configure.name
                }
            },
            onNext = {
                stepName = when (step) {
                    InstallWizardStep.ChooseSystem -> InstallWizardStep.Configure.name
                    InstallWizardStep.Configure -> InstallWizardStep.Review.name
                    InstallWizardStep.Review -> InstallWizardStep.Review.name
                }
            },
        )
    }
}

@Composable
private fun InstallWizardStepper(step: InstallWizardStep, onSelect: (InstallWizardStep) -> Unit) {
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.xs),
        verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xs),
    ) {
        StepButton(InstallWizardStep.ChooseSystem, step, R.string.install_step_choose, onSelect)
        StepButton(InstallWizardStep.Configure, step, R.string.install_step_configure, onSelect)
        StepButton(InstallWizardStep.Review, step, R.string.install_step_review, onSelect)
    }
}

@Composable
private fun StepButton(item: InstallWizardStep, current: InstallWizardStep, labelRes: Int, onSelect: (InstallWizardStep) -> Unit) {
    if (item == current) {
        Button(onClick = { onSelect(item) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(labelRes)) }
    } else {
        OutlinedButton(onClick = { onSelect(item) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(labelRes)) }
    }
}

@Composable
private fun DistroChoiceStep(draft: InstallDraft, form: InstallFormSummary, validation: InstallDraftValidation, onDraftChange: (InstallDraft) -> Unit) {
    StatusCard(
        title = stringResource(R.string.install_choose_title),
        body = stringResource(R.string.install_choose_body),
        footer = {
            val choices = phase32Choices(form.distros, draft.distro, listOf("ubuntu", "arch"))
            ActionFlowRow {
                choices.forEach { distro ->
                    ChoiceButton(
                        label = distro,
                        selected = distro == draft.distro,
                        onClick = { onDraftChange(draft.copy(distro = distro, name = if (draft.name.isBlank() || draft.name == draft.distro) distro else draft.name)) },
                    )
                }
            }
            OptionLine(stringResource(R.string.install_form_distros), form.distros)
            if (!validation.distroValid) Text(stringResource(R.string.install_distro_error), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        },
    )
}

@Composable
private fun ConfigureInstallStep(
    draft: InstallDraft,
    form: InstallFormSummary,
    validation: InstallDraftValidation,
    onDraftChange: (InstallDraft) -> Unit,
) {
    var advancedVisible by rememberSaveable { mutableStateOf(false) }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(R.string.install_configure_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            ValidatedTextField(
                value = draft.name,
                onValueChange = { onDraftChange(draft.copy(name = it)) },
                label = stringResource(R.string.install_field_name),
                valid = validation.nameValid,
                error = stringResource(R.string.install_name_error),
            )
            ValidatedTextField(
                value = draft.username,
                onValueChange = { onDraftChange(draft.copy(username = it)) },
                label = stringResource(R.string.install_field_username),
                valid = validation.usernameValid,
                error = stringResource(R.string.install_username_error),
            )
            Text("Target architecture", fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
            ActionFlowRow {
                phase32Choices(form.architectures, draft.arch, listOf("arm64", "amd64")).forEach { arch ->
                    ChoiceButton(arch, selected = arch == draft.arch, onClick = { onDraftChange(draft.copy(arch = arch)) })
                }
            }
            if (!validation.archValid) Text("This distribution/architecture combination is not supported.", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            Text(stringResource(R.string.install_profile_choices), fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
            ActionFlowRow {
                phase32Choices(form.profiles, draft.profile, listOf("minimal", "dev", "xfce4", "plasma", "custom")).forEach { profile ->
                    ChoiceButton(profile, selected = profile == draft.profile, onClick = { onDraftChange(draft.copy(profile = profile)) })
                }
            }
            Text(stringResource(R.string.install_desktop_choices), fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
            ActionFlowRow {
                phase32Choices(form.desktops, draft.desktop, listOf("none", "xfce4", "plasma")).forEach { desktop ->
                    ChoiceButton(desktop, selected = desktop == draft.desktop, onClick = { onDraftChange(draft.copy(desktop = desktop)) })
                }
            }
            OutlinedButton(onClick = { advancedVisible = !advancedVisible }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                Text(if (advancedVisible) stringResource(R.string.install_hide_advanced) else stringResource(R.string.install_show_advanced))
            }
            AnimatedVisibility(advancedVisible) {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    OutlinedTextField(
                        value = draft.release,
                        onValueChange = { onDraftChange(draft.copy(release = it)) },
                        label = { Text(stringResource(R.string.install_field_release)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = draft.version,
                        onValueChange = { onDraftChange(draft.copy(version = it)) },
                        label = { Text(stringResource(R.string.install_field_version)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = draft.mirror,
                        onValueChange = { onDraftChange(draft.copy(mirror = it)) },
                        label = { Text(stringResource(R.string.install_field_mirror)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Text("Resume / repair", fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
                    ActionFlowRow {
                        ChoiceButton("Resume", selected = draft.resume, onClick = { onDraftChange(draft.copy(resume = !draft.resume, repair = false)) })
                        ChoiceButton("Repair", selected = draft.repair, onClick = { onDraftChange(draft.copy(repair = !draft.repair, resume = false)) })
                        ChoiceButton("Overwrite existing", selected = draft.overwriteExisting, onClick = { onDraftChange(draft.copy(overwriteExisting = !draft.overwriteExisting)) })
                    }
                    OptionLine(stringResource(R.string.install_form_desktops), form.desktops)
                }
            }
        }
    }
}

@Composable
private fun ReviewInstallStep(
    draft: InstallDraft,
    validation: InstallDraftValidation,
    preview: PreviewSummary?,
    onPreview: () -> Unit,
    onStartInstall: () -> Unit,
    onOpenActivity: () -> Unit,
) {
    StatusCard(
        title = stringResource(R.string.install_review_title),
        body = stringResource(R.string.install_review_body),
        footer = {
            ReviewLine(stringResource(R.string.install_field_distro), draft.distro)
            ReviewLine(stringResource(R.string.install_field_name), draft.name)
            ReviewLine(stringResource(R.string.install_field_username), draft.username)
            ReviewLine(stringResource(R.string.install_field_profile), draft.profile)
            ReviewLine(stringResource(R.string.install_field_desktop), draft.desktop)
            ReviewLine("Preset", draft.preset)
            ReviewLine("Recovery mode", when { draft.repair -> "Repair"; draft.resume -> "Resume"; else -> "Fresh install" })
            ReviewLine("Overwrite existing", if (draft.overwriteExisting) "Explicitly allowed" else "Blocked unless target is empty/managed")
            ReviewLine(stringResource(R.string.install_review_safety), stringResource(R.string.install_review_safety_body))
            ActionFlowRow {
                Button(onClick = onPreview, enabled = validation.valid, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.install_preview_action)) }
                OutlinedButton(onClick = onOpenActivity, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_open_activity)) }
            }
            if (!validation.valid) Text(stringResource(R.string.install_validation_blocked), color = MaterialTheme.colorScheme.error)
            preview?.let { summary -> PreviewCard(summary = summary, onStartInstall = onStartInstall, onOpenActivity = onOpenActivity) }
        },
    )
}

@Composable
private fun InstallWizardFooter(
    step: InstallWizardStep,
    validation: InstallDraftValidation,
    onBack: () -> Unit,
    onNext: () -> Unit,
) {
    ActionFlowRow {
        OutlinedButton(onClick = onBack, enabled = step != InstallWizardStep.ChooseSystem, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
            Text(stringResource(R.string.action_back))
        }
        if (step != InstallWizardStep.Review) {
            val canContinue = when (step) {
                InstallWizardStep.ChooseSystem -> validation.distroValid
                InstallWizardStep.Configure -> validation.valid
                InstallWizardStep.Review -> false
            }
            Button(onClick = onNext, enabled = canContinue, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) {
                Text(stringResource(R.string.action_continue))
            }
        }
    }
}

@Composable
private fun ChoiceButton(label: String, selected: Boolean, onClick: () -> Unit) {
    if (selected) {
        Button(onClick = onClick, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(label) }
    } else {
        OutlinedButton(onClick = onClick, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(label) }
    }
}

@Composable
private fun ValidatedTextField(value: String, onValueChange: (String) -> Unit, label: String, valid: Boolean, error: String) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            label = { Text(label) },
            singleLine = true,
            isError = !valid,
            modifier = Modifier.fillMaxWidth(),
        )
        if (!valid) Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun PreviewCard(summary: PreviewSummary, onStartInstall: () -> Unit, onOpenActivity: () -> Unit) {
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            StatusPill(
                label = if (summary.ok) stringResource(R.string.preview_ready) else stringResource(R.string.preview_blocked),
                tone = if (summary.ok) StatusTone.Success else StatusTone.Danger,
            )
            Text(summary.title, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.titleMedium)
            Text(summary.body, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (summary.blocking.isNotEmpty()) OptionLine(stringResource(R.string.preview_blocking), summary.blocking)
            if (summary.warnings.isNotEmpty()) OptionLine(stringResource(R.string.preview_warnings), summary.warnings)
            Text(stringResource(R.string.install_foreground_handoff_body), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            LinearProgressIndicator(progress = { if (summary.ok) 1f else 0.35f }, modifier = Modifier.fillMaxWidth())
            ActionFlowRow {
                Button(onClick = onStartInstall, enabled = summary.approvesOperation("install.run"), modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.install_start_action)) }
                OutlinedButton(onClick = onOpenActivity, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.action_open_activity)) }
            }
        }
    }
}

@Composable
private fun ReviewLine(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
        Text(value.ifBlank { stringResource(R.string.value_not_reported) }, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
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

private fun phase32Choices(serverValues: List<String>, current: String, fallback: List<String>): List<String> =
    (listOf(current).filter { it.isNotBlank() } + serverValues + fallback)
        .map { it.trim() }
        .filter { it.isNotEmpty() }
        .distinct()
        .take(MAX_VISIBLE_OPTIONS)

private const val MAX_VISIBLE_OPTIONS = 8
