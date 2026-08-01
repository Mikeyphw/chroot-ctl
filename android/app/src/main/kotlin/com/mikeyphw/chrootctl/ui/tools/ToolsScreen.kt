package com.mikeyphw.chrootctl.ui.tools

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.CatalogEntrySummary
import com.mikeyphw.chrootctl.model.CatalogPane
import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.PackagePane
import com.mikeyphw.chrootctl.model.PreviewSummary
import com.mikeyphw.chrootctl.model.ToolCapabilityGroup
import com.mikeyphw.chrootctl.model.TransferPane
import com.mikeyphw.chrootctl.model.DebugTimelineSummary
import com.mikeyphw.chrootctl.model.DebugProbeSummary
import com.mikeyphw.chrootctl.model.SystemRowSummary
import com.mikeyphw.chrootctl.model.DebugPane
import com.mikeyphw.chrootctl.model.SystemSupportPane
import com.mikeyphw.chrootctl.ui.components.ChipRow
import com.mikeyphw.chrootctl.ui.components.EmptyState

@Composable
fun ToolsScreen(
    groups: List<ToolCapabilityGroup>,
    chroots: List<ChrootSummary>,
    catalogPane: CatalogPane,
    packagePane: PackagePane,
    transferPane: TransferPane,
    systemSupportPane: SystemSupportPane,
    debugPane: DebugPane,
    onOpenInstall: () -> Unit,
    onRefreshCatalog: (String) -> Unit,
    onSetCatalogTarget: (String) -> Unit,
    onSetCatalogQuery: (String) -> Unit,
    onSetCatalogCategory: (String) -> Unit,
    onToggleCatalogEntry: (String) -> Unit,
    onPreviewCatalogApply: () -> Unit,
    onStartCatalogApply: () -> Unit,
    onRefreshPackageInventory: (String) -> Unit,
    onUpdatePackageCompare: (String, String) -> Unit,
    onComparePackages: () -> Unit,
    onUpdateTransferImportArchive: (String) -> Unit,
    onUpdateTransferImportTarget: (String) -> Unit,
    onUpdateTransferExportTarget: (String) -> Unit,
    onUpdateTransferExportArchive: (String) -> Unit,
    onInspectTransferImport: () -> Unit,
    onPreviewTransferExport: () -> Unit,
    onRefreshTransferArtifacts: () -> Unit,
    onStartTransferImport: () -> Unit,
    onStartTransferExport: () -> Unit,
    onCleanupAllArtifacts: () -> Unit,
    onPickImportArchive: () -> Unit,
    onCreateExportDocument: () -> Unit,
    onRefreshSystemSupport: () -> Unit,
    onPreviewSupportBundle: () -> Unit,
    onStartSupportBundle: () -> Unit,
    onPreviewModuleBuild: () -> Unit,
    onStartModuleBuild: () -> Unit,
    onPreviewRepair: () -> Unit,
    onStartRepair: () -> Unit,
    onPreviewTempCleanup: () -> Unit,
    onStartTempCleanup: () -> Unit,
    onRefreshDebugWorkbench: (String) -> Unit,
    onStartDebugExport: () -> Unit,
    onPreviewSmokePlan: () -> Unit,
    onStartSmokeRun: () -> Unit,
    onRefreshSmokeReport: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Button(onClick = onOpenInstall) { Text(stringResource(R.string.install_open_action)) }
        CatalogCard(
            chroots = chroots,
            pane = catalogPane,
            onRefreshCatalog = onRefreshCatalog,
            onSetTarget = onSetCatalogTarget,
            onSetQuery = onSetCatalogQuery,
            onSetCategory = onSetCatalogCategory,
            onToggleEntry = onToggleCatalogEntry,
            onPreview = onPreviewCatalogApply,
            onApply = onStartCatalogApply,
        )
        PackageCard(
            chroots = chroots,
            pane = packagePane,
            onRefreshInventory = onRefreshPackageInventory,
            onUpdateCompare = onUpdatePackageCompare,
            onCompare = onComparePackages,
        )
        TransferCard(
            chroots = chroots,
            pane = transferPane,
            onUpdateImportArchive = onUpdateTransferImportArchive,
            onUpdateImportTarget = onUpdateTransferImportTarget,
            onUpdateExportTarget = onUpdateTransferExportTarget,
            onUpdateExportArchive = onUpdateTransferExportArchive,
            onInspectImport = onInspectTransferImport,
            onPreviewExport = onPreviewTransferExport,
            onRefreshArtifacts = onRefreshTransferArtifacts,
            onStartImport = onStartTransferImport,
            onStartExport = onStartTransferExport,
            onCleanupAllArtifacts = onCleanupAllArtifacts,
            onPickImportArchive = onPickImportArchive,
            onCreateExportDocument = onCreateExportDocument,
        )
        SystemSupportCard(
            pane = systemSupportPane,
            onRefresh = onRefreshSystemSupport,
            onPreviewSupportBundle = onPreviewSupportBundle,
            onStartSupportBundle = onStartSupportBundle,
            onPreviewModuleBuild = onPreviewModuleBuild,
            onStartModuleBuild = onStartModuleBuild,
            onPreviewRepair = onPreviewRepair,
            onStartRepair = onStartRepair,
            onPreviewTempCleanup = onPreviewTempCleanup,
            onStartTempCleanup = onStartTempCleanup,
        )
        DebugWorkbenchCard(
            pane = debugPane,
            onRefresh = onRefreshDebugWorkbench,
            onExport = onStartDebugExport,
            onPreviewSmokePlan = onPreviewSmokePlan,
            onStartSmokeRun = onStartSmokeRun,
            onRefreshSmokeReport = onRefreshSmokeReport,
        )
        if (groups.isEmpty()) {
            EmptyState(
                title = stringResource(R.string.tools_empty_title),
                body = stringResource(R.string.tools_empty_body),
            )
        } else {
            groups.forEach { group -> ToolGroupCard(group) }
        }
    }
}

@Composable
private fun CatalogCard(
    chroots: List<ChrootSummary>,
    pane: CatalogPane,
    onRefreshCatalog: (String) -> Unit,
    onSetTarget: (String) -> Unit,
    onSetQuery: (String) -> Unit,
    onSetCategory: (String) -> Unit,
    onToggleEntry: (String) -> Unit,
    onPreview: () -> Unit,
    onApply: () -> Unit,
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.catalog_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = pane.kind == "tool", onClick = { onRefreshCatalog("tool") }, label = { Text(stringResource(R.string.catalog_tools_chip)) })
                FilterChip(selected = pane.kind == "addon", onClick = { onRefreshCatalog("addon") }, label = { Text(stringResource(R.string.catalog_addons_chip)) })
            }
            OutlinedTextField(
                value = pane.targetName.orEmpty(),
                onValueChange = onSetTarget,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.catalog_target_label)) },
            )
            OutlinedTextField(
                value = pane.query,
                onValueChange = onSetQuery,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.catalog_search_label)) },
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onRefreshCatalog(pane.kind) }) { Text(stringResource(R.string.catalog_search_action)) }
                Button(onClick = onPreview) { Text(stringResource(R.string.preview_action)) }
                Button(onClick = onApply, enabled = pane.preview?.ok == true) { Text(stringResource(R.string.apply_action)) }
            }
            if (pane.categories.isNotEmpty()) {
                ChipRow(listOf(stringResource(R.string.catalog_all_categories)) + pane.categories)
                OutlinedTextField(
                    value = pane.category,
                    onValueChange = onSetCategory,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.catalog_category_label)) },
                )
            }
            pane.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            pane.preview?.let { PreviewBlock(it) }
            val installedNames = chroots.map { it.name }.joinToString()
            if (installedNames.isNotBlank()) {
                Text(stringResource(R.string.catalog_available_chroots, installedNames), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            pane.entries.take(12).forEach { entry -> CatalogEntryRow(entry, onToggleEntry) }
        }
    }
}

@Composable
private fun CatalogEntryRow(entry: CatalogEntrySummary, onToggleEntry: (String) -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Checkbox(checked = entry.selected, onCheckedChange = { onToggleEntry(entry.name) })
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(entry.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                Text(entry.description, color = MaterialTheme.colorScheme.onSurfaceVariant)
                ChipRow(entry.categories + entry.distros)
            }
        }
    }
}

@Composable
private fun PackageCard(
    chroots: List<ChrootSummary>,
    pane: PackagePane,
    onRefreshInventory: (String) -> Unit,
    onUpdateCompare: (String, String) -> Unit,
    onCompare: () -> Unit,
) {
    var left by remember(pane.leftName) { mutableStateOf(pane.leftName) }
    var right by remember(pane.rightName) { mutableStateOf(pane.rightName) }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.package_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            val names = chroots.map { it.name }.joinToString()
            if (names.isNotBlank()) Text(stringResource(R.string.catalog_available_chroots, names), color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedTextField(value = left, onValueChange = { left = it; onUpdateCompare(it, right) }, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.package_left_label)) })
            OutlinedTextField(value = right, onValueChange = { right = it; onUpdateCompare(left, it) }, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.package_right_label)) })
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onRefreshInventory(left) }) { Text(stringResource(R.string.package_inventory_action)) }
                Button(onClick = onCompare) { Text(stringResource(R.string.package_compare_action)) }
            }
            pane.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            pane.inventory?.let { inventory ->
                Text(stringResource(R.string.package_inventory_summary, inventory.name, inventory.count))
                ChipRow(inventory.packages.take(16))
            }
            pane.comparison?.let { comparison ->
                Text(stringResource(R.string.package_compare_summary, comparison.leftCount, comparison.rightCount, comparison.commonCount))
                if (comparison.onlyLeft.isNotEmpty()) Text(stringResource(R.string.package_only_left, comparison.onlyLeft.take(12).joinToString()))
                if (comparison.onlyRight.isNotEmpty()) Text(stringResource(R.string.package_only_right, comparison.onlyRight.take(12).joinToString()))
            }
        }
    }
}

@Composable
private fun TransferCard(
    chroots: List<ChrootSummary>,
    pane: TransferPane,
    onUpdateImportArchive: (String) -> Unit,
    onUpdateImportTarget: (String) -> Unit,
    onUpdateExportTarget: (String) -> Unit,
    onUpdateExportArchive: (String) -> Unit,
    onInspectImport: () -> Unit,
    onPreviewExport: () -> Unit,
    onRefreshArtifacts: () -> Unit,
    onStartImport: () -> Unit,
    onStartExport: () -> Unit,
    onCleanupAllArtifacts: () -> Unit,
    onPickImportArchive: () -> Unit,
    onCreateExportDocument: () -> Unit,
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.transfer_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.transfer_saf_body), color = MaterialTheme.colorScheme.onSurfaceVariant)
            Button(onClick = onPickImportArchive) { Text(stringResource(R.string.transfer_pick_import_action)) }
            OutlinedTextField(value = pane.importArchive, onValueChange = onUpdateImportArchive, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.transfer_import_archive_label)) })
            OutlinedTextField(value = pane.importTargetName, onValueChange = onUpdateImportTarget, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.transfer_import_name_label)) })
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onInspectImport) { Text(stringResource(R.string.transfer_inspect_action)) }
                Button(onClick = onStartImport, enabled = pane.importArchive.isNotBlank()) { Text(stringResource(R.string.transfer_import_action)) }
            }
            pane.importInspection?.let { PreviewBlock(it) }
            val names = chroots.map { it.name }.joinToString()
            if (names.isNotBlank()) Text(stringResource(R.string.catalog_available_chroots, names), color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedTextField(value = pane.exportTargetName, onValueChange = onUpdateExportTarget, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.transfer_export_name_label)) })
            OutlinedTextField(value = pane.exportArchive, onValueChange = onUpdateExportArchive, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.transfer_export_archive_label)) }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPreviewExport) { Text(stringResource(R.string.preview_action)) }
                Button(onClick = onStartExport, enabled = pane.exportTargetName.isNotBlank()) { Text(stringResource(R.string.transfer_export_action)) }
                Button(onClick = onCreateExportDocument) { Text(stringResource(R.string.transfer_create_document_action)) }
            }
            pane.exportPreview?.let { PreviewBlock(it) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onRefreshArtifacts) { Text(stringResource(R.string.artifacts_refresh_action)) }
                Button(onClick = onCleanupAllArtifacts) { Text(stringResource(R.string.artifacts_cleanup_action)) }
            }
            pane.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            pane.artifacts.take(8).forEach { artifact ->
                Text(stringResource(R.string.artifact_row, artifact.name, artifact.sizeBytes), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun PreviewBlock(preview: PreviewSummary) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(preview.title, fontWeight = FontWeight.SemiBold)
            Text(preview.body)
            preview.blocking.forEach { Text(it, color = MaterialTheme.colorScheme.error) }
            preview.warnings.forEach { Text(it, color = MaterialTheme.colorScheme.tertiary) }
        }
    }
}


@Composable
private fun SystemSupportCard(
    pane: SystemSupportPane,
    onRefresh: () -> Unit,
    onPreviewSupportBundle: () -> Unit,
    onStartSupportBundle: () -> Unit,
    onPreviewModuleBuild: () -> Unit,
    onStartModuleBuild: () -> Unit,
    onPreviewRepair: () -> Unit,
    onStartRepair: () -> Unit,
    onPreviewTempCleanup: () -> Unit,
    onStartTempCleanup: () -> Unit,
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.system_support_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.system_support_body), color = MaterialTheme.colorScheme.onSurfaceVariant)
            Button(onClick = onRefresh) { Text(stringResource(R.string.system_refresh_action)) }
            Text(stringResource(R.string.system_runtime_title), fontWeight = FontWeight.SemiBold)
            pane.runtimeRows.forEach { row -> SystemRow(row) }
            Text(stringResource(R.string.system_module_title), fontWeight = FontWeight.SemiBold)
            pane.moduleRows.forEach { row -> SystemRow(row) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPreviewSupportBundle) { Text(stringResource(R.string.support_preview_action)) }
                Button(onClick = onStartSupportBundle) { Text(stringResource(R.string.support_bundle_action)) }
            }
            pane.supportPreview?.let { PreviewBlock(it) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPreviewModuleBuild) { Text(stringResource(R.string.module_preview_action)) }
                Button(onClick = onStartModuleBuild) { Text(stringResource(R.string.module_build_action)) }
            }
            pane.moduleBuildPreview?.let { PreviewBlock(it) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPreviewRepair) { Text(stringResource(R.string.repair_preview_action)) }
                Button(onClick = onStartRepair, enabled = pane.repairPreview?.ok == true) { Text(stringResource(R.string.repair_apply_action)) }
            }
            pane.repairPreview?.let { PreviewBlock(it) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPreviewTempCleanup) { Text(stringResource(R.string.cleanup_preview_action)) }
                Button(onClick = onStartTempCleanup, enabled = pane.cleanupPreview?.ok == true) { Text(stringResource(R.string.cleanup_temp_action)) }
            }
            pane.cleanupPreview?.let { PreviewBlock(it) }
            pane.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
    }
}

@Composable
private fun SystemRow(row: SystemRowSummary) {
    Text(stringResource(R.string.system_row, row.label, row.value, row.state), color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun DebugWorkbenchCard(
    pane: DebugPane,
    onRefresh: (String) -> Unit,
    onExport: () -> Unit,
    onPreviewSmokePlan: () -> Unit,
    onStartSmokeRun: () -> Unit,
    onRefreshSmokeReport: () -> Unit,
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.debug_workbench_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.debug_workbench_body), color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("all", "root", "backend", "storage", "runtime", "recovery", "operations").forEach { group ->
                    FilterChip(selected = pane.selectedGroup == group, onClick = { onRefresh(group) }, label = { Text(group) })
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onRefresh(pane.selectedGroup) }) { Text(stringResource(R.string.debug_run_probes_action)) }
                Button(onClick = onExport) { Text(stringResource(R.string.debug_export_action)) }
            }
            Text(stringResource(R.string.smoke_suite_title), fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.smoke_suite_body), color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPreviewSmokePlan) { Text(stringResource(R.string.smoke_preview_action)) }
                Button(onClick = onStartSmokeRun) { Text(stringResource(R.string.smoke_run_action)) }
                Button(onClick = onRefreshSmokeReport) { Text(stringResource(R.string.smoke_report_action)) }
            }
            pane.smokePlan?.let { PreviewBlock(it) }
            pane.smokeReport?.let { PreviewBlock(it) }
            pane.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Text(stringResource(R.string.debug_probes_title), fontWeight = FontWeight.SemiBold)
            if (pane.probes.isEmpty()) {
                Text(stringResource(R.string.debug_no_probes), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            pane.probes.take(12).forEach { probe -> DebugProbeRow(probe) }
            Text(stringResource(R.string.debug_timeline_title), fontWeight = FontWeight.SemiBold)
            pane.timeline.take(8).forEach { event -> DebugTimelineRow(event) }
        }
    }
}

@Composable
private fun DebugProbeRow(probe: DebugProbeSummary) {
    Text(stringResource(R.string.debug_probe_row, probe.group, probe.code, probe.status, probe.detail), color = MaterialTheme.colorScheme.onSurfaceVariant)
    if (probe.next.isNotBlank()) Text(stringResource(R.string.debug_probe_next, probe.next), color = MaterialTheme.colorScheme.tertiary)
}

@Composable
private fun DebugTimelineRow(event: DebugTimelineSummary) {
    Text(stringResource(R.string.debug_timeline_row, event.eventType, event.target, event.result, event.message), color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun ToolGroupCard(group: ToolCapabilityGroup) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(group.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.tools_group_body), color = MaterialTheme.colorScheme.onSurfaceVariant)
            ChipRow(group.operations)
        }
    }
}
