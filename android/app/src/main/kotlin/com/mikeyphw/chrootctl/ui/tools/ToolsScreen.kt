package com.mikeyphw.chrootctl.ui.tools

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.CatalogEntrySummary
import com.mikeyphw.chrootctl.model.CatalogPane
import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.DebugPane
import com.mikeyphw.chrootctl.model.DebugProbeSummary
import com.mikeyphw.chrootctl.model.DebugTimelineSummary
import com.mikeyphw.chrootctl.model.PackagePane
import com.mikeyphw.chrootctl.model.PreviewSummary
import com.mikeyphw.chrootctl.model.RepairItemSummary
import com.mikeyphw.chrootctl.model.SystemRowSummary
import com.mikeyphw.chrootctl.model.SystemSupportPane
import com.mikeyphw.chrootctl.model.ToolCapabilityGroup
import com.mikeyphw.chrootctl.model.TransferPane
import com.mikeyphw.chrootctl.ui.ChrootLayout
import com.mikeyphw.chrootctl.ui.ToolsWorkspace
import com.mikeyphw.chrootctl.ui.components.ChipRow
import com.mikeyphw.chrootctl.ui.components.EmptyState
import com.mikeyphw.chrootctl.ui.normalizeToolsWorkspace
import kotlinx.coroutines.delay

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
    onToggleRepairItem: (String) -> Unit,
    onStartRepair: () -> Unit,
    onPreviewTempCleanup: () -> Unit,
    onStartTempCleanup: () -> Unit,
    onRefreshDebugWorkbench: (String) -> Unit,
    onStartDebugExport: () -> Unit,
    onPreviewSmokePlan: () -> Unit,
    onStartSmokeRun: () -> Unit,
    onRefreshSmokeReport: () -> Unit,
    onRefreshSmokeLastResult: () -> Unit,
    onPersistSmokeResult: () -> Unit,
    onExportSmokeEvidence: () -> Unit,
    onCreateSmokeFailureBundle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var workspaceKey by rememberSaveable { mutableStateOf(ToolsWorkspace.Catalog.key) }
    val workspace = normalizeToolsWorkspace(workspaceKey)
    Column(modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        WorkspaceSelector(workspace = workspace, onSelect = { workspaceKey = it.key })
        when (workspace) {
            ToolsWorkspace.Catalog -> CatalogCard(
                chroots = chroots,
                pane = catalogPane,
                onRefreshCatalog = onRefreshCatalog,
                onSetTarget = onSetCatalogTarget,
                onSetQuery = onSetCatalogQuery,
                onSetCategory = onSetCatalogCategory,
                onToggleEntry = onToggleCatalogEntry,
                onPreview = onPreviewCatalogApply,
                onApply = onStartCatalogApply,
                onOpenInstall = onOpenInstall,
            )
            ToolsWorkspace.Packages -> PackageCard(
                chroots = chroots,
                pane = packagePane,
                onRefreshInventory = onRefreshPackageInventory,
                onUpdateCompare = onUpdatePackageCompare,
                onCompare = onComparePackages,
            )
            ToolsWorkspace.Transfer -> TransferCard(
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
            ToolsWorkspace.Runtime -> SystemSupportCard(
                pane = systemSupportPane,
                onRefresh = onRefreshSystemSupport,
                onPreviewSupportBundle = onPreviewSupportBundle,
                onStartSupportBundle = onStartSupportBundle,
                onPreviewModuleBuild = onPreviewModuleBuild,
                onStartModuleBuild = onStartModuleBuild,
                onPreviewTempCleanup = onPreviewTempCleanup,
                onStartTempCleanup = onStartTempCleanup,
            )
            ToolsWorkspace.Logs -> LogsWorkspaceCard(
                pane = debugPane,
                onRefresh = onRefreshDebugWorkbench,
                onExport = onStartDebugExport,
                onPreviewSmokePlan = onPreviewSmokePlan,
                onStartSmokeRun = onStartSmokeRun,
                onRefreshSmokeReport = onRefreshSmokeReport,
                onRefreshSmokeLastResult = onRefreshSmokeLastResult,
                onPersistSmokeResult = onPersistSmokeResult,
                onExportSmokeEvidence = onExportSmokeEvidence,
                onCreateSmokeFailureBundle = onCreateSmokeFailureBundle,
            )
            ToolsWorkspace.Repair -> RepairWorkspaceCard(
                pane = systemSupportPane,
                onLoadPlan = onPreviewRepair,
                onToggleRepairItem = onToggleRepairItem,
                onPreviewSelected = onPreviewRepair,
                onApplySelected = onStartRepair,
            )
            ToolsWorkspace.Help -> HelpAndApiCard(groups = groups)
        }
    }
}

@Composable
private fun WorkspaceSelector(workspace: ToolsWorkspace, onSelect: (ToolsWorkspace) -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        ToolsWorkspace.entries.forEach { item ->
            FilterChip(
                modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                selected = workspace == item,
                onClick = { onSelect(item) },
                label = { Text(item.title) },
            )
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
    onOpenInstall: () -> Unit,
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(ToolsWorkspace.Catalog.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(ToolsWorkspace.Catalog.summary, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Button(onClick = onOpenInstall, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.install_open_action)) }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = pane.kind == "tool", onClick = { onRefreshCatalog("tool") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget), label = { Text(stringResource(R.string.catalog_tools_chip)) })
                FilterChip(selected = pane.kind == "addon", onClick = { onRefreshCatalog("addon") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget), label = { Text(stringResource(R.string.catalog_addons_chip)) })
            }
            OutlinedTextField(value = pane.targetName.orEmpty(), onValueChange = onSetTarget, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.catalog_target_label)) })
            OutlinedTextField(value = pane.query, onValueChange = onSetQuery, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.catalog_search_label)) })
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onRefreshCatalog(pane.kind) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.catalog_search_action)) }
                Button(onClick = onPreview, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.preview_action)) }
                Button(onClick = onApply, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget), enabled = pane.preview?.ok == true) { Text(stringResource(R.string.apply_action)) }
            }
            if (pane.categories.isNotEmpty()) {
                ChipRow(listOf(stringResource(R.string.catalog_all_categories)) + pane.categories)
                OutlinedTextField(value = pane.category, onValueChange = onSetCategory, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.catalog_category_label)) })
            }
            pane.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            pane.preview?.let { PreviewBlock(it) }
            val installedNames = chroots.map { it.name }.joinToString()
            if (installedNames.isNotBlank()) Text(stringResource(R.string.catalog_available_chroots, installedNames), color = MaterialTheme.colorScheme.onSurfaceVariant)
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
            Text(ToolsWorkspace.Packages.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(ToolsWorkspace.Packages.summary, color = MaterialTheme.colorScheme.onSurfaceVariant)
            val names = chroots.map { it.name }.joinToString()
            if (names.isNotBlank()) Text(stringResource(R.string.catalog_available_chroots, names), color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedTextField(value = left, onValueChange = { left = it; onUpdateCompare(it, right) }, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.package_left_label)) })
            OutlinedTextField(value = right, onValueChange = { right = it; onUpdateCompare(left, it) }, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.package_right_label)) })
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onRefreshInventory(left) }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.package_inventory_action)) }
                Button(onClick = onCompare, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.package_compare_action)) }
            }
            pane.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            pane.inventory?.let { inventory ->
                Text(pluralStringResource(R.plurals.package_inventory_summary, inventory.count, inventory.name, inventory.count))
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
            Text(ToolsWorkspace.Transfer.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(ToolsWorkspace.Transfer.summary, color = MaterialTheme.colorScheme.onSurfaceVariant)
            val names = chroots.map { it.name }.joinToString()
            if (names.isNotBlank()) Text(stringResource(R.string.catalog_available_chroots, names), color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedTextField(value = pane.importArchive, onValueChange = onUpdateImportArchive, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.transfer_import_archive_label)) })
            OutlinedTextField(value = pane.importTargetName, onValueChange = onUpdateImportTarget, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.transfer_import_target_label)) })
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPickImportArchive, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.transfer_pick_archive_action)) }
                Button(onClick = onInspectImport, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.transfer_inspect_action)) }
                Button(onClick = onStartImport, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget), enabled = pane.importInspection?.ok == true) { Text(stringResource(R.string.transfer_import_action)) }
            }
            pane.importInspection?.let { PreviewBlock(it) }
            OutlinedTextField(value = pane.exportTargetName, onValueChange = onUpdateExportTarget, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.transfer_export_target_label)) })
            OutlinedTextField(value = pane.exportArchive, onValueChange = onUpdateExportArchive, modifier = Modifier.fillMaxWidth(), label = { Text(stringResource(R.string.transfer_export_archive_label)) })
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onCreateExportDocument, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.transfer_create_document_action)) }
                Button(onClick = onPreviewExport, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.transfer_preview_export_action)) }
                Button(onClick = onStartExport, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget), enabled = pane.exportPreview?.ok == true) { Text(stringResource(R.string.transfer_export_action)) }
            }
            pane.exportPreview?.let { PreviewBlock(it) }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onRefreshArtifacts, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.transfer_refresh_artifacts_action)) }
                Button(onClick = onCleanupAllArtifacts, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.transfer_cleanup_artifacts_action)) }
            }
            pane.artifacts.take(8).forEach { artifact -> Text(stringResource(R.string.transfer_artifact_row, artifact.name, artifact.sizeBytes, artifact.modifiedAt), color = MaterialTheme.colorScheme.onSurfaceVariant) }
            pane.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
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
    onPreviewTempCleanup: () -> Unit,
    onStartTempCleanup: () -> Unit,
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(ToolsWorkspace.Runtime.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.system_support_body), color = MaterialTheme.colorScheme.onSurfaceVariant)
            Button(onClick = onRefresh, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.system_refresh_action)) }
            Text(stringResource(R.string.system_runtime_title), fontWeight = FontWeight.SemiBold)
            pane.runtimeRows.forEach { row -> SystemRow(row) }
            Text(stringResource(R.string.system_module_title), fontWeight = FontWeight.SemiBold)
            pane.moduleRows.forEach { row -> SystemRow(row) }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPreviewSupportBundle, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.support_preview_action)) }
                Button(onClick = onStartSupportBundle, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.support_bundle_action)) }
                Button(onClick = onPreviewModuleBuild, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.module_preview_action)) }
                Button(onClick = onStartModuleBuild, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.module_build_action)) }
                Button(onClick = onPreviewTempCleanup, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.cleanup_preview_action)) }
                Button(onClick = onStartTempCleanup, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget), enabled = pane.cleanupPreview?.ok == true) { Text(stringResource(R.string.cleanup_temp_action)) }
            }
            pane.supportPreview?.let { PreviewBlock(it) }
            pane.moduleBuildPreview?.let { PreviewBlock(it) }
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
private fun LogsWorkspaceCard(
    pane: DebugPane,
    onRefresh: (String) -> Unit,
    onExport: () -> Unit,
    onPreviewSmokePlan: () -> Unit,
    onStartSmokeRun: () -> Unit,
    onRefreshSmokeReport: () -> Unit,
    onRefreshSmokeLastResult: () -> Unit,
    onPersistSmokeResult: () -> Unit,
    onExportSmokeEvidence: () -> Unit,
    onCreateSmokeFailureBundle: () -> Unit,
) {
    DebugWorkbenchCard(
        pane = pane,
        onRefresh = onRefresh,
        onExport = onExport,
        onPreviewSmokePlan = onPreviewSmokePlan,
        onStartSmokeRun = onStartSmokeRun,
        onRefreshSmokeReport = onRefreshSmokeReport,
        onRefreshSmokeLastResult = onRefreshSmokeLastResult,
        onPersistSmokeResult = onPersistSmokeResult,
        onExportSmokeEvidence = onExportSmokeEvidence,
        onCreateSmokeFailureBundle = onCreateSmokeFailureBundle,
    )
}

@Composable
private fun DebugWorkbenchCard(
    pane: DebugPane,
    onRefresh: (String) -> Unit,
    onExport: () -> Unit,
    onPreviewSmokePlan: () -> Unit,
    onStartSmokeRun: () -> Unit,
    onRefreshSmokeReport: () -> Unit,
    onRefreshSmokeLastResult: () -> Unit,
    onPersistSmokeResult: () -> Unit,
    onExportSmokeEvidence: () -> Unit,
    onCreateSmokeFailureBundle: () -> Unit,
) {
    var liveTail by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(liveTail, pane.selectedGroup) {
        while (liveTail) {
            onRefresh("operations")
            delay(3_000L)
        }
    }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.logs_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.logs_body), color = MaterialTheme.colorScheme.onSurfaceVariant)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onRefresh("operations") }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.logs_refresh_action)) }
                OutlinedButton(onClick = { liveTail = !liveTail }, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(if (liveTail) stringResource(R.string.logs_stop_follow_action) else stringResource(R.string.logs_follow_action)) }
                Button(onClick = onExport, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.debug_export_action)) }
            }
            Text(stringResource(R.string.debug_timeline_title), fontWeight = FontWeight.SemiBold)
            if (pane.timeline.isEmpty()) Text(stringResource(R.string.logs_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
            pane.timeline.take(20).forEach { event -> DebugTimelineRow(event) }
            Text(stringResource(R.string.smoke_suite_title), fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.smoke_suite_body), color = MaterialTheme.colorScheme.onSurfaceVariant)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPreviewSmokePlan, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.smoke_preview_action)) }
                Button(onClick = onStartSmokeRun, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.smoke_run_action)) }
                Button(onClick = onRefreshSmokeReport, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.smoke_report_action)) }
                Button(onClick = onRefreshSmokeLastResult, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.smoke_last_result_action)) }
                Button(onClick = onPersistSmokeResult, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.smoke_persist_action)) }
                Button(onClick = onExportSmokeEvidence, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.smoke_export_action)) }
                Button(onClick = onCreateSmokeFailureBundle, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.smoke_failure_bundle_action)) }
            }
            pane.smokePlan?.let { PreviewBlock(it) }
            pane.smokeReport?.let { PreviewBlock(it) }
            pane.smokeLastResult?.let { PreviewBlock(it) }
            pane.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
    }
}

@Composable
private fun RepairWorkspaceCard(
    pane: SystemSupportPane,
    onLoadPlan: () -> Unit,
    onToggleRepairItem: (String) -> Unit,
    onPreviewSelected: () -> Unit,
    onApplySelected: () -> Unit,
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.repair_selective_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.repair_selective_body), color = MaterialTheme.colorScheme.onSurfaceVariant)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onLoadPlan, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(stringResource(R.string.repair_load_plan_action)) }
                Button(onClick = onPreviewSelected, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget), enabled = pane.selectedRepairItemIds.isNotEmpty()) { Text(stringResource(R.string.repair_preview_selected_action)) }
                Button(onClick = onApplySelected, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget), enabled = pane.selectedRepairItemIds.isNotEmpty() && pane.repairPreview?.ok == true) { Text(stringResource(R.string.repair_apply_selected_action)) }
            }
            pane.repairItems.forEach { item -> RepairItemRow(item, checked = item.itemId in pane.selectedRepairItemIds, onToggle = { onToggleRepairItem(item.itemId) }) }
            if (pane.repairItems.isEmpty()) Text("Load the repair plan to see exact registry decisions.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            pane.repairPreview?.let { PreviewBlock(it) }
        }
    }
}

@Composable
private fun RepairItemRow(item: RepairItemSummary, checked: Boolean, onToggle: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Checkbox(checked = checked, onCheckedChange = { onToggle() })
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(item.summary.ifBlank { item.name }, fontWeight = FontWeight.SemiBold)
                Text(stringResource(R.string.repair_item_meta, item.kind, item.severity, item.action), color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (item.impact.isNotBlank()) Text(item.impact, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun HelpAndApiCard(groups: List<ToolCapabilityGroup>) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(R.string.help_open_action), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            HelpRow(stringResource(R.string.help_getting_started_title), stringResource(R.string.help_getting_started_body))
            HelpRow(stringResource(R.string.help_operations_title), stringResource(R.string.help_operations_body))
            HelpRow(stringResource(R.string.help_recovery_title), stringResource(R.string.help_recovery_body))
            HelpRow(stringResource(R.string.help_storage_title), stringResource(R.string.help_storage_body))
            HelpRow(stringResource(R.string.help_privacy_title), stringResource(R.string.help_privacy_body))
            Text(stringResource(R.string.help_api_title), fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.help_api_body), color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (groups.isEmpty()) {
                EmptyState(title = stringResource(R.string.tools_empty_title), body = stringResource(R.string.help_api_unavailable))
            } else {
                groups.forEach { group -> ToolGroupCard(group) }
            }
        }
    }
}

@Composable
private fun HelpRow(title: String, body: String) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(title, fontWeight = FontWeight.SemiBold)
        Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
