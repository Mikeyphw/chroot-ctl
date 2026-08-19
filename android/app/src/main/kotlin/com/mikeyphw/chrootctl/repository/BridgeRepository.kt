package com.mikeyphw.chrootctl.repository

import com.mikeyphw.chrootctl.data.CheckResultEntity
import com.mikeyphw.chrootctl.data.ChrootCtlDatabase
import com.mikeyphw.chrootctl.data.ChrootEntity
import com.mikeyphw.chrootctl.data.HOME_SNAPSHOT_ID
import com.mikeyphw.chrootctl.data.HomeSnapshotEntity
import com.mikeyphw.chrootctl.data.OperationEntity
import com.mikeyphw.chrootctl.data.OperationEventEntity
import com.mikeyphw.chrootctl.model.CheckSummary
import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.HomeSnapshot
import com.mikeyphw.chrootctl.model.InstallDraft
import com.mikeyphw.chrootctl.model.InstallFormSummary
import com.mikeyphw.chrootctl.model.PreviewSummary
import com.mikeyphw.chrootctl.model.RepairItemSummary
import com.mikeyphw.chrootctl.model.SnapshotSummary
import com.mikeyphw.chrootctl.model.StorageSummary
import com.mikeyphw.chrootctl.model.ChrootLogEntrySummary
import com.mikeyphw.chrootctl.model.ServiceUnitSummary
import com.mikeyphw.chrootctl.model.UserSummary
import com.mikeyphw.chrootctl.model.Loadable
import com.mikeyphw.chrootctl.model.OperationEventSummary
import com.mikeyphw.chrootctl.model.OperationSummary
import com.mikeyphw.chrootctl.model.ReadinessRow
import com.mikeyphw.chrootctl.model.ReadinessState
import com.mikeyphw.chrootctl.model.RecommendedAction
import com.mikeyphw.chrootctl.model.ReleaseReadinessSummary
import com.mikeyphw.chrootctl.model.ToolCapabilityGroup
import com.mikeyphw.chrootctl.model.CatalogEntrySummary
import com.mikeyphw.chrootctl.model.PackageInventorySummary
import com.mikeyphw.chrootctl.model.PackageCompareSummary
import com.mikeyphw.chrootctl.model.TransferArtifactSummary
import com.mikeyphw.chrootctl.model.SystemRowSummary
import com.mikeyphw.chrootctl.model.DebugTimelineSummary
import com.mikeyphw.chrootctl.model.DebugProbeSummary
import com.mikeyphw.chrootctl.protocol.BridgeCapabilities
import com.mikeyphw.chrootctl.protocol.BridgeEnvelope
import com.mikeyphw.chrootctl.protocol.BridgeRequest
import com.mikeyphw.chrootctl.protocol.RootBridgeInfo
import com.mikeyphw.chrootctl.root.RootServiceClient
import android.os.ParcelFileDescriptor
import androidx.room.withTransaction
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

class BridgeRepository(
    private val rootClient: RootServiceClient,
    private val database: ChrootCtlDatabase,
) {
    val cachedHome: Flow<Loadable<HomeSnapshot>> = combine(
        database.homeSnapshotDao().observe(),
        database.chrootDao().observeAll(),
        database.operationDao().observeRecent(HOME_OPERATION_LIMIT),
    ) { snapshot, chroots, operations ->
        if (snapshot == null) {
            Loadable.Loading
        } else {
            Loadable.Ready(snapshot.toHomeSnapshot(chroots, operations))
        }
    }

    val chroots: Flow<List<ChrootSummary>> = database.chrootDao().observeAll().map { rows -> rows.map { it.toSummary() } }
    val operations: Flow<List<OperationSummary>> = database.operationDao().observeRecent(HOME_OPERATION_LIMIT).map { rows ->
        rows.map { it.toSummary() }
    }

    fun chrootChecks(name: String?): Flow<List<CheckSummary>> = if (name.isNullOrBlank()) {
        flowOf(emptyList())
    } else {
        database.checkDao().observeScope(chrootScope(name)).map { rows -> rows.map { it.toSummary() } }
    }

    fun operationEvents(operationId: String?): Flow<List<OperationEventSummary>> = if (operationId.isNullOrBlank()) {
        flowOf(emptyList())
    } else {
        database.operationDao().observeEvents(operationId).map { rows -> rows.map { it.toSummary() } }
    }

    fun operation(operationId: String?): Flow<OperationSummary?> = if (operationId.isNullOrBlank()) {
        flowOf(null)
    } else {
        database.operationDao().observeById(operationId).map { row -> row?.toSummary() }
    }

    suspend fun refreshHome(): Result<HomeSnapshot> = runCatching {
        val bridgeInfo = RootBridgeInfo.fromJson(rootClient.serviceInfo())
        check(bridgeInfo.ok) { bridgeInfo.message }
        val capabilities = BridgeCapabilities.fromEnvelope(rootClient.capabilities())
        check(!capabilities.arbitraryShell) { "Unsafe arbitrary-shell capability was reported" }
        val state = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest("system.dashboard").toJson())).requireData()
        val releaseReadiness = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest("release.readiness").toJson())).requireData()
        val chrootArray = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest("chroots.list").toJson())).requireArray()
        val operationArray = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest("operations.list").toJson())).requireArray()
        val now = System.currentTimeMillis()
        val chrootEntities = chrootArray.toJsonObjects().map { item -> item.toChrootEntity(now) }
        val operationEntities = operationArray.toJsonObjects().map { item -> item.toOperationEntity(now, stale = false) }
        val warningCount = countWarnings(state, chrootEntities, operationEntities)
        val snapshot = HomeSnapshotEntity(
            id = HOME_SNAPSHOT_ID,
            bridgeInfoJson = bridgeInfo.toJson(),
            capabilitiesJson = capabilities.toJson(),
            dashboardJson = state.put("releaseReadiness", releaseReadiness).toString(),
            chrootCount = chrootEntities.size,
            operationCount = operationEntities.size,
            warningCount = warningCount,
            lastRefreshAt = now,
            stale = false,
        )
        database.withTransaction {
            database.chrootDao().replaceSnapshot(chrootEntities)
            operationEntities.forEach { operation -> database.operationDao().persistOperation(operation) }
            database.checkDao().replaceScope("home", state.extractChecks(now, "home"))
            database.homeSnapshotDao().upsert(snapshot)
        }
        snapshot.toHomeSnapshot(chrootEntities, operationEntities)
    }.onFailure {
        database.withTransaction {
            database.chrootDao().markAllStale()
            database.homeSnapshotDao().markStale()
        }
    }

    suspend fun refreshChrootDetail(name: String): Result<Unit> = runCatching {
        val now = System.currentTimeMillis()
        val chroot = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("chroots.get", JSONObject().put("name", name)).toJson()),
        ).requireData()
        database.chrootDao().upsertAll(listOf(chroot.toChrootEntity(now)))
        val status = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("system.status", JSONObject().put("name", name).put("details", true)).toJson()),
        ).requireDataOrWrappedArray("checks", "system.status")
        val doctor = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("system.doctor", JSONObject().put("name", name)).toJson()),
        ).requireDataOrWrappedArray("checks", "system.doctor")
        val checks = status.extractChecks(now, chrootScope(name)) + doctor.extractChecks(now, chrootScope(name))
        database.checkDao().replaceScope(chrootScope(name), checks.ifEmpty { listOf(status.toSyntheticCheck(name, now), doctor.toSyntheticCheck(name, now)) })
    }

    suspend fun refreshOperationDetail(operationId: String): Result<Unit> = runCatching {
        persistOperationEnvelope(operationId, rootClient.operationState(operationId))
    }

    suspend fun reconcileOperation(operationId: String): Result<Unit> = runCatching {
        persistOperationEnvelope(operationId, rootClient.reconcileOperation(operationId))
    }

    private suspend fun persistOperationEnvelope(operationId: String, raw: String) {
        val data = BridgeEnvelope.fromJson(raw).requireData()
        val events = data.optJSONArray("progressEvents")?.toJsonObjects()?.map { event ->
            event.toOperationEventEntity(operationId)
        }.orEmpty()
        database.operationDao().persistOperation(
            data.toOperationEntity(System.currentTimeMillis(), stale = false),
            events,
        )
    }

    suspend fun startSystemRefresh(onEvent: suspend (JSONObject) -> Unit): Result<String?> = runCatching {
        var operationId: String? = null
        val request = BridgeRequest("system.refresh", JSONObject().put("title", "Native state refresh")).toJson()
        val started = rootClient.streamOperation(request) { line ->
            val event = JSONObject(line)
            recordOperationEvent(event)
            operationId = event.optString("operationId").takeIf(String::isNotBlank) ?: operationId
            onEvent(event)
        }
        val startEnvelope = JSONObject(started)
        check(startEnvelope.optBoolean("ok")) { startEnvelope.optJSONObject("error")?.optString("message") ?: "Operation did not start" }
        refreshHome()
        operationId
    }

    suspend fun cancelOperation(operationId: String): Result<Unit> = runCatching {
        val data = BridgeEnvelope.fromJson(rootClient.cancelOperation(operationId)).requireData()
        database.operationDao().upsert(data.toOperationEntity(System.currentTimeMillis(), stale = false))
    }

    suspend fun recordOperationEvent(event: JSONObject) {
        val operationId = event.optString("operationId").takeIf(String::isNotBlank) ?: return
        val existing = database.operationDao().findById(operationId)
        database.operationDao().persistOperation(
            event.toOperationEntity(existing),
            listOf(event.toOperationEventEntity(operationId)),
        )
    }


    suspend fun refreshInstallForm(draft: InstallDraft): Result<InstallFormSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("install.form", draft.toJsonPayload()).toJson()),
        ).requireData()
        data.toInstallFormSummary()
    }

    suspend fun previewInstall(draft: InstallDraft): Result<PreviewSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.preview(BridgeRequest("install.preview", draft.toJsonPayload()).toJson()),
        ).requireData()
        data.toPreviewSummary("Install preview")
    }

    suspend fun previewLifecycle(name: String, action: String): Result<PreviewSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.preview(
                BridgeRequest(
                    "chroots.lifecycle.preview",
                    JSONObject().put("name", name).put("action", action),
                ).toJson(),
            ),
        ).requireData()
        data.toPreviewSummary("${action.replaceFirstChar { it.uppercase() }} preview")
    }

    suspend fun refreshSnapshots(name: String): Result<List<SnapshotSummary>> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("snapshots.list", JSONObject().put("name", name)).toJson()),
        ).requireArrayFromData("snapshots", "items")
        data.toJsonObjects().map { item -> item.toSnapshotSummary() }
    }

    suspend fun refreshStorage(name: String): Result<StorageSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("storage.status", JSONObject().put("name", name)).toJson()),
        ).requireData()
        data.toStorageSummary()
    }

    suspend fun refreshLogs(name: String, level: String? = null): Result<Pair<String, List<ChrootLogEntrySummary>>> = runCatching {
        val payload = JSONObject().put("name", name).put("tail", 200)
        level?.takeIf(String::isNotBlank)?.let { payload.put("level", it) }
        val data = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("logs.list", payload).toJson()),
        ).requireData()
        val entries = data.optJSONArray("entries").toJsonObjects().map { row ->
            ChrootLogEntrySummary(
                line = row.firstString("line", "message", "text"),
                level = row.firstString("level", "severity").ifBlank { "INFO" },
            )
        }
        data.firstString("logFile", "log_file") to entries
    }

    suspend fun previewSnapshotCreate(name: String, snapshot: String): Result<PreviewSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.preview(
                BridgeRequest(
                    "snapshots.preview",
                    JSONObject().put("name", name).put("action", "create").put("snapshot", snapshot),
                ).toJson(),
            ),
        ).requireData()
        data.toPreviewSummary("Snapshot preview")
    }

    suspend fun previewSnapshotAction(name: String, snapshot: String, action: String): Result<PreviewSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.preview(
                BridgeRequest(
                    "snapshots.preview",
                    JSONObject().put("name", name).put("action", action).put("snapshot", snapshot),
                ).toJson(),
            ),
        ).requireData()
        data.toPreviewSummary("Snapshot ${action.replaceFirstChar { it.uppercase() }} preview")
    }

    suspend fun refreshUsers(name: String): Result<List<UserSummary>> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("users.list", JSONObject().put("name", name)).toJson()),
        ).requireArrayFromData("users", "items")
        data.toJsonObjects().map { item -> item.toUserSummary() }
    }

    suspend fun previewUserAction(payload: JSONObject): Result<PreviewSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.preview(BridgeRequest("users.preview", payload).toJson()),
        ).requireData()
        data.toPreviewSummary("User preview")
    }

    suspend fun refreshServices(name: String): Result<List<ServiceUnitSummary>> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("services.list", JSONObject().put("name", name)).toJson()),
        ).requireArrayFromData("services", "items")
        data.toJsonObjects().map { item -> item.toServiceUnitSummary() }
    }

    suspend fun refreshServiceDetail(name: String, service: String): Result<ServiceUnitSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("services.journal", JSONObject().put("name", name).put("service", service)).toJson()),
        ).requireData()
        data.toServiceUnitDetailSummary()
    }

    suspend fun previewServiceAction(payload: JSONObject): Result<PreviewSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.preview(BridgeRequest("services.preview", payload).toJson()),
        ).requireData()
        data.toPreviewSummary("Service preview")
    }



    suspend fun refreshCatalog(kind: String, targetName: String?, query: String, category: String): Result<Pair<List<CatalogEntrySummary>, List<String>>> = runCatching {
        val payload = JSONObject()
            .put("kind", kind)
            .put("query", query)
            .put("category", category.takeIf(String::isNotBlank) ?: JSONObject.NULL)
        if (!targetName.isNullOrBlank()) payload.put("name", targetName)
        val operation = if (kind == "addon") "catalog.addons" else "catalog.tools"
        val data = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest(operation, payload).toJson())).requireData()
        val entries = data.optJSONArray("entries").toJsonObjects().map { item -> item.toCatalogEntrySummary() }
        val categories = data.optJSONArray("categories").toStringListLocal()
        entries to categories
    }

    suspend fun previewCatalog(kind: String, targetName: String, names: List<String>): Result<PreviewSummary> = runCatching {
        val payload = JSONObject()
            .put("kind", kind)
            .put("name", targetName)
            .put("names", JSONArray(names))
        val data = BridgeEnvelope.fromJson(rootClient.preview(BridgeRequest("catalog.preview", payload).toJson())).requireData()
        data.toPreviewSummary("Catalog preview")
    }

    suspend fun refreshPackageInventory(name: String): Result<PackageInventorySummary> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("packages.inventory", JSONObject().put("name", name)).toJson()),
        ).requireData()
        data.toPackageInventorySummary()
    }

    suspend fun comparePackages(left: String, right: String): Result<PackageCompareSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("packages.compare", JSONObject().put("left", left).put("right", right)).toJson()),
        ).requireData()
        data.toPackageCompareSummary()
    }

    suspend fun inspectTransferImport(archive: String, name: String = "", conflict: String = "rename", password: String = ""): Result<PreviewSummary> = runCatching {
        val payload = JSONObject().put("archive", archive).put("conflict", conflict)
        if (name.isNotBlank()) payload.put("name", name)
        if (password.isNotBlank()) payload.put("password", password)
        val data = BridgeEnvelope.fromJson(
            rootClient.preview(BridgeRequest("transfer.import_preview", payload).toJson()),
        ).requireData()
        data.toPreviewSummary("Import preview")
    }

    suspend fun previewTransferExport(name: String, archive: String): Result<PreviewSummary> = runCatching {
        val payload = JSONObject().put("name", name)
        if (archive.isNotBlank()) payload.put("archive", archive)
        val data = BridgeEnvelope.fromJson(rootClient.preview(BridgeRequest("transfer.preview_export", payload).toJson())).requireData()
        data.toPreviewSummary("Export preview")
    }

    suspend fun refreshTransferArtifacts(): Result<List<TransferArtifactSummary>> = runCatching {
        val data = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest("artifacts.list").toJson())).requireData()
        data.optJSONArray("items").toJsonObjects().map { item -> item.toTransferArtifactSummary() }
    }

    suspend fun previewArtifactCleanup(deleteAll: Boolean = true, path: String? = null): Result<PreviewSummary> = runCatching {
        val payload = JSONObject().put("deleteAll", deleteAll)
        path?.takeIf(String::isNotBlank)?.let { payload.put("path", it) }
        val data = BridgeEnvelope.fromJson(rootClient.preview(BridgeRequest("artifacts.cleanup_preview", payload).toJson())).requireData()
        data.toPreviewSummary("Artifact cleanup preview")
    }


    suspend fun stageImportArchive(filename: String, input: ParcelFileDescriptor): Result<String> = runCatching {
        val request = BridgeRequest("transfer.stage_import", JSONObject().put("filename", filename)).toJson()
        val data = BridgeEnvelope.fromJson(rootClient.transferFromDescriptor(request, input)).requireData()
        data.firstString("archive", "path")
    }

    suspend fun copyManagedArtifactToDocument(path: String, output: ParcelFileDescriptor): Result<Long> = runCatching {
        val request = BridgeRequest("transfer.copy_to_document", JSONObject().put("path", path)).toJson()
        val data = BridgeEnvelope.fromJson(rootClient.transferToDescriptor(request, output)).requireData()
        data.optLong("bytes", 0L)
    }


    suspend fun refreshSystemRuntime(): Result<Pair<List<SystemRowSummary>, List<SystemRowSummary>>> = runCatching {
        val runtime = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest("system.runtime").toJson())).requireData()
        val module = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest("system.module_status").toJson())).requireData()
        runtime.toRuntimeRows() to module.toModuleRows()
    }

    suspend fun previewSupportBundle(): Result<PreviewSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(rootClient.preview(BridgeRequest("support.preview").toJson())).requireData()
        data.toPreviewSummary("Support bundle preview")
    }

    suspend fun previewModuleBuild(): Result<PreviewSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(rootClient.preview(BridgeRequest("system.module_build_preview").toJson())).requireData()
        data.toPreviewSummary("Module build preview")
    }

    suspend fun previewRepair(decisions: JSONArray? = null): Result<Pair<PreviewSummary, List<RepairItemSummary>>> = runCatching {
        val payload = JSONObject()
        if (decisions != null) payload.put("decisions", decisions)
        val data = BridgeEnvelope.fromJson(rootClient.preview(BridgeRequest("repair.preview", payload).toJson())).requireData()
        data.toRepairPreviewSummary() to data.toRepairItemSummaries()
    }

    suspend fun previewTempCleanup(): Result<PreviewSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(rootClient.preview(BridgeRequest("cleanup.temp_preview", JSONObject().put("deleteAll", true)).toJson())).requireData()
        data.toPreviewSummary("Temporary cleanup preview")
    }

    suspend fun refreshDebugWorkbench(group: String): Result<Pair<List<DebugProbeSummary>, List<DebugTimelineSummary>>> = runCatching {
        val probes = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest("debug.probes", JSONObject().put("group", group)).toJson())).requireData()
        val timeline = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest("debug.timeline", JSONObject().put("limit", 50)).toJson())).requireData()
        probes.optJSONArray("probes").toJsonObjects().map { it.toDebugProbeSummary() } to timeline.optJSONArray("events").toJsonObjects().map { it.toDebugTimelineSummary() }
    }


    suspend fun previewSmokePlan(): Result<PreviewSummary> = runCatching {
        val payload = JSONObject().put("scope", "real-device").put("includeOptional", true)
        val data = BridgeEnvelope.fromJson(rootClient.preview(BridgeRequest("smoke.preview", payload).toJson())).requireData()
        data.toPreviewSummary("Real-device smoke plan")
    }

    suspend fun refreshSmokeReport(): Result<PreviewSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest("smoke.report").toJson())).requireData()
        data.toPreviewSummary("Real-device smoke report")
    }

    suspend fun refreshSmokeLastResult(): Result<PreviewSummary> = runCatching {
        val data = BridgeEnvelope.fromJson(rootClient.query(BridgeRequest("smoke.last_result").toJson())).requireData()
        data.toPreviewSummary("Last smoke result")
    }

    suspend fun startBridgeOperation(
        operation: String,
        payload: JSONObject,
        requestId: String? = null,
        onEvent: suspend (JSONObject) -> Unit,
    ): Result<String?> = runCatching {
        var operationId: String? = null
        val request = BridgeRequest(operation, payload, requestId = requestId ?: java.util.UUID.randomUUID().toString()).toJson()
        val started = rootClient.streamOperation(request) { line ->
            val event = JSONObject(line)
            recordOperationEvent(event)
            operationId = event.optString("operationId").takeIf(String::isNotBlank) ?: operationId
            onEvent(event)
        }
        val startEnvelope = JSONObject(started)
        check(startEnvelope.optBoolean("ok")) { startEnvelope.optJSONObject("error")?.optString("message") ?: "Operation did not start" }
        refreshHome()
        operationId
    }

    suspend fun findOperationIdByRequestId(requestId: String): Result<String?> = runCatching {
        val rows = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("operations.list", JSONObject().put("limit", 1000)).toJson()),
        ).requireArray().toJsonObjects()
        rows.firstOrNull { row ->
            row.optJSONObject("request")?.optString("requestId") == requestId
        }?.optString("operationId")?.takeIf(String::isNotBlank)
    }

    fun capabilityGroups(capabilities: BridgeCapabilities): List<ToolCapabilityGroup> {
        val grouped = capabilities.operationCapabilities.groupBy { capability ->
            when (capability.name.substringBefore('.')) {
                "system" -> "System"
                "chroots" -> "Chroots"
                "operations" -> "Activity"
                else -> "Bridge"
            }
        }
        return grouped.toSortedMap().map { (title, values) -> ToolCapabilityGroup(title, values.map { it.name }.sorted()) }
    }

    fun close() = rootClient.close()

    private companion object {
        const val HOME_OPERATION_LIMIT = 50
    }
}

private fun HomeSnapshotEntity.toHomeSnapshot(
    chroots: List<ChrootEntity>,
    operations: List<OperationEntity>,
): HomeSnapshot {
    val bridgeInfo = RootBridgeInfo.fromJson(bridgeInfoJson)
    val capabilities = BridgeCapabilities.fromData(JSONObject(capabilitiesJson))
    val activeOperation = operations.firstOrNull { it.state in setOf("queued", "running", "cancelling") }
    val failedOperation = operations.firstOrNull { it.state in setOf("failed", "interrupted", "blocked") }
    val rows = buildList {
        add(ReadinessRow("Root bridge", bridgeInfo.message, if (bridgeInfo.ok) ReadinessState.Ready else ReadinessState.Blocked))
        add(ReadinessRow("Backend", "${bridgeInfo.backend} · protocol ${capabilities.protocolVersion}", ReadinessState.Ready))
        add(ReadinessRow("Chroots", "${chroots.count { !it.stale }} registered", if (chroots.any { it.warningCount > 0 }) ReadinessState.Warning else ReadinessState.Ready))
        add(ReadinessRow("Operations", "${operations.count { !it.stale }} recent", if (failedOperation != null) ReadinessState.Warning else ReadinessState.Ready))
    }
    val action = when {
        !bridgeInfo.ok -> RecommendedAction(
            title = "Repair root bridge",
            body = bridgeInfo.message,
            actionLabel = "Open diagnostics",
        )
        activeOperation != null -> RecommendedAction(
            title = "Review active operation",
            body = activeOperation.progressText,
            actionLabel = "Open activity",
        )
        failedOperation != null -> RecommendedAction(
            title = "Review last failure",
            body = failedOperation.errorMessage ?: failedOperation.progressText,
            actionLabel = "Open activity",
        )
        chroots.none { !it.stale } -> RecommendedAction(
            title = "Create first chroot",
            body = "No registered chroots were returned by the backend.",
            actionLabel = "Start install flow",
        )
        else -> RecommendedAction(
            title = "Refresh environment",
            body = "The app can refresh dashboard, chroot and operation state from the bridge.",
            actionLabel = "Refresh",
        )
    }
    return HomeSnapshot(
        bridgeInfo = bridgeInfo,
        capabilities = capabilities,
        chrootCount = chrootCount,
        operationCount = operationCount,
        warningCount = warningCount,
        readinessRows = rows,
        recommendedAction = action,
        releaseReadiness = JSONObject(dashboardJson).optJSONObject("releaseReadiness").toReleaseReadinessSummary(),
        refreshedAt = lastRefreshAt,
        stale = stale,
    )
}

private fun ChrootEntity.toSummary(): ChrootSummary = ChrootSummary(
    name = name,
    distribution = distribution,
    release = release,
    architecture = architecture,
    path = path,
    status = status,
    mountState = mountState,
    health = health,
    warningCount = warningCount,
    rawJson = rawJson,
    lastRefreshAt = lastRefreshAt,
    stale = stale,
)

private fun CheckResultEntity.toSummary(): CheckSummary = CheckSummary(
    checkId = checkId,
    title = title,
    message = message,
    severity = severity,
)

private fun OperationEntity.toSummary(): OperationSummary = OperationSummary(
    operationId = operationId,
    kind = kind,
    title = title,
    state = state,
    targetName = targetName,
    phase = phase,
    progressPercent = progressPercent,
    progressText = progressText,
    errorCode = errorCode,
    errorMessage = errorMessage,
    createdAt = createdAt,
    stale = stale,
)

private fun OperationEventEntity.toSummary(): OperationEventSummary = OperationEventSummary(
    id = id,
    type = type,
    timestamp = timestamp,
    message = JSONObject(payloadJson).firstString("message", "phase", "state").ifBlank { type },
    payloadJson = payloadJson,
)

private fun JSONObject.toChrootEntity(now: Long): ChrootEntity {
    val name = firstString("name", "id", "target_name", "targetName").ifBlank { "unknown" }
    val warnings = optJSONArray("warnings")?.length() ?: optInt("warningCount", 0)
    return ChrootEntity(
        name = name,
        distribution = firstString("distribution", "distro").takeIf(String::isNotBlank),
        release = firstString("release", "codename", "version").takeIf(String::isNotBlank),
        architecture = firstString("architecture", "arch").takeIf(String::isNotBlank),
        path = firstString("path", "root", "rootfs").takeIf(String::isNotBlank),
        status = firstString("status", "state").ifBlank { "registered" },
        mountState = firstString("mountState", "mount_state", "mounted").takeIf(String::isNotBlank),
        health = firstString("health", "summary").takeIf(String::isNotBlank),
        warningCount = warnings,
        rawJson = toString(),
        lastRefreshAt = now,
        stale = false,
    )
}

private fun JSONObject.toStorageSummary(): StorageSummary = StorageSummary(
    name = firstString("name"),
    rootfsPath = firstString("rootfsPath", "rootfs_path", "path"),
    rootfsExists = optBoolean("rootfsExists", optBoolean("rootfs_exists", false)),
    rootfsBytes = optLong("rootfsBytes", optLong("rootfs_bytes", 0L)),
    cachePath = firstString("cachePath", "cache_path"),
    cacheExists = optBoolean("cacheExists", optBoolean("cache_exists", false)),
    cacheBytes = optLong("cacheBytes", optLong("cache_bytes", 0L)),
    freeBytes = optLong("freeBytes", optLong("free_bytes", 0L)),
    usedBytes = optLong("usedBytes", optLong("used_bytes", 0L)),
    totalBytes = optLong("totalBytes", optLong("total_bytes", 0L)),
    mountState = firstString("mountState", "mount_state").ifBlank { "unknown" },
    mountedCount = optInt("mountedCount", optInt("mounted_count", 0)),
    mountCount = optInt("mountCount", optInt("mount_count", 0)),
    snapshotDirectory = firstString("snapshotDirectory", "snapshot_directory"),
)

private fun JSONObject.toOperationEntity(now: Long, stale: Boolean): OperationEntity = OperationEntity(
    operationId = firstString("operationId", "operation_id", "id").ifBlank { "unknown-$now" },
    kind = firstString("kind", "operation").ifBlank { "unknown" },
    title = firstString("title", "kind", "operation").ifBlank { "Operation" },
    state = firstString("state").ifBlank { "unknown" },
    targetName = firstString("targetName", "target_name", "name").takeIf(String::isNotBlank),
    phase = firstString("phase").takeIf(String::isNotBlank),
    progressPercent = optNullableInt("progressPercent", "progress_percent"),
    progressText = firstString("progressText", "progress_text").ifBlank { firstString("state").ifBlank { "Queued" } },
    createdAt = optEpochMillis("createdAt", "created_at") ?: now,
    startedAt = optEpochMillis("startedAt", "started_at"),
    finishedAt = optEpochMillis("finishedAt", "finished_at"),
    resultJson = opt("resultPayload")?.takeUnless { it == JSONObject.NULL }?.toString(),
    errorCode = firstString("errorCode", "error_code").takeIf(String::isNotBlank),
    errorMessage = firstString("error", "message").takeIf(String::isNotBlank),
    stale = stale,
)

private fun JSONObject.toOperationEntity(existing: OperationEntity?): OperationEntity {
    val payload = optJSONObject("payload") ?: JSONObject()
    val operationId = optString("operationId").takeIf(String::isNotBlank) ?: existing?.operationId ?: "unknown-${System.currentTimeMillis()}"
    val type = optString("type")
    val now = (optDouble("timestamp", System.currentTimeMillis() / 1000.0) * 1000).toLong()
    val state = when (type) {
        "operation_queued" -> "queued"
        "operation_started", "operation_progress" -> "running"
        "operation_cancelling" -> "cancelling"
        "operation_cancelled" -> "cancelled"
        "operation_succeeded" -> "succeeded"
        "operation_failed" -> "failed"
        "operation_blocked" -> "blocked"
        else -> existing?.state ?: "running"
    }
    return OperationEntity(
        operationId = operationId,
        kind = existing?.kind ?: "system.refresh",
        title = existing?.title ?: "Native state refresh",
        state = state,
        targetName = existing?.targetName,
        phase = payload.firstString("phase").takeIf(String::isNotBlank) ?: existing?.phase,
        progressPercent = payload.optNullableInt("percent", "progressPercent") ?: existing?.progressPercent,
        progressText = payload.firstString("message", "state").ifBlank { existing?.progressText ?: state.replaceFirstChar { it.uppercase() } },
        createdAt = existing?.createdAt ?: now,
        startedAt = existing?.startedAt ?: if (state == "running") now else null,
        finishedAt = if (state in setOf("cancelled", "succeeded", "failed", "blocked")) now else existing?.finishedAt,
        resultJson = existing?.resultJson,
        errorCode = payload.firstString("code").takeIf(String::isNotBlank) ?: existing?.errorCode,
        errorMessage = payload.firstString("message").takeIf(String::isNotBlank)?.takeIf { state == "failed" || state == "blocked" } ?: existing?.errorMessage,
        stale = false,
    )
}

private fun JSONObject.toOperationEventEntity(operationId: String): OperationEventEntity {
    val timestampValue: Any? = opt("timestamp").takeUnless { it === JSONObject.NULL }
    val timestamp = when (timestampValue) {
        is Number -> (timestampValue.toDouble() * 1000).toLong()
        is String -> ((timestampValue.toDoubleOrNull() ?: System.currentTimeMillis() / 1000.0) * 1000).toLong()
        else -> System.currentTimeMillis()
    }
    val payload = optJSONObject("payload") ?: this
    val sequence = optLong("sequence", -1L)
    val stableTimestamp = timestampValue?.toString().orEmpty()
    val eventKey = if (sequence >= 0L) {
        "$operationId:$sequence"
    } else {
        // Legacy/recovery events may not carry a backend sequence. Build the
        // fallback identity only from wire data; never include the local receive
        // clock or reconnecting to the same event would create a duplicate row.
        val stableInput = "$operationId\u001f${optString("type", "operation_event")}\u001f$stableTimestamp\u001f${payload}"
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(stableInput.toByteArray(Charsets.UTF_8))
            .joinToString("") { byte -> "%02x".format(byte) }
        "$operationId:legacy:$digest"
    }
    return OperationEventEntity(
        eventKey = eventKey,
        operationId = operationId,
        type = optString("type", "operation_event"),
        timestamp = timestamp,
        payloadJson = payload.toString(),
    )
}

private fun JSONObject.extractChecks(now: Long, scope: String): List<CheckResultEntity> {
    val checks = mutableListOf<CheckResultEntity>()
    for (key in listOf("status_checks", "statusChecks", "doctor_checks", "doctorChecks", "checks")) {
        val array = optJSONArray(key) ?: continue
        array.toJsonObjects().forEachIndexed { index, item ->
            checks += CheckResultEntity(
                checkId = "$scope-$key-$index-${item.firstString("id", "code", "title")}",
                scope = scope,
                title = item.firstString("title", "name", "code").ifBlank { key },
                message = item.firstString("message", "detail", "status").ifBlank { item.toString() },
                severity = item.firstString("severity", "level", "state").ifBlank { "info" },
                rawJson = item.toString(),
                lastRefreshAt = now,
            )
        }
    }
    return checks
}

private fun JSONObject.toSyntheticCheck(name: String, now: Long): CheckResultEntity = CheckResultEntity(
    checkId = "${chrootScope(name)}-${firstString("name", "state", "status").ifBlank { "summary" }}-${hashCode()}",
    scope = chrootScope(name),
    title = firstString("title", "name", "state", "status").ifBlank { "Backend response" },
    message = firstString("message", "detail", "summary").ifBlank { toString() },
    severity = firstString("severity", "level", "state").ifBlank { "info" },
    rawJson = toString(),
    lastRefreshAt = now,
)

private fun JSONObject?.toReleaseReadinessSummary(): ReleaseReadinessSummary {
    if (this == null) {
        return ReleaseReadinessSummary(
            title = "Release readiness",
            body = "Release readiness has not been loaded yet.",
            rows = emptyList(),
        )
    }
    val rows = optJSONArray("checks").toJsonObjects().map { item ->
        val state = when (item.firstString("status").lowercase()) {
            "pass", "ready" -> ReadinessState.Ready
            "fail", "failed", "blocked" -> ReadinessState.Blocked
            else -> ReadinessState.Warning
        }
        ReadinessRow(
            label = item.firstString("label", "id"),
            detail = item.firstString("detail", "message"),
            state = state,
        )
    }
    return ReleaseReadinessSummary(
        title = "Release readiness",
        body = firstString("summary").ifBlank { "Native release readiness checks are available." },
        rows = rows,
    )
}

private fun countWarnings(
    dashboard: JSONObject,
    chroots: List<ChrootEntity>,
    operations: List<OperationEntity>,
): Int = chroots.sumOf { it.warningCount } + operations.count { it.state in setOf("failed", "interrupted", "blocked") } +
    dashboard.extractChecks(System.currentTimeMillis(), "home").count { it.severity.lowercase() in setOf("warn", "warning", "error", "failed", "blocked") }

private fun JSONArray?.toJsonObjects(): List<JSONObject> {
    if (this == null) return emptyList()
    return buildList {
        for (index in 0 until length()) {
            val value = opt(index)
            if (value is JSONObject) add(value)
        }
    }
}

private fun JSONObject.firstString(vararg keys: String): String {
    for (key in keys) {
        if (!has(key) || isNull(key)) continue
        val value = opt(key)
        if (value != null && value != JSONObject.NULL) return value.toString()
    }
    return ""
}

private fun JSONObject.optNullableInt(vararg keys: String): Int? {
    for (key in keys) {
        if (!has(key) || isNull(key)) continue
        val value: Any? = opt(key).takeUnless { it === JSONObject.NULL }
        val parsed = when (value) {
            is Number -> value.toInt()
            is String -> value.toIntOrNull()
            null -> null
            else -> null
        }
        if (parsed != null) return parsed
    }
    return null
}

private fun JSONObject.optEpochMillis(vararg keys: String): Long? {
    for (key in keys) {
        if (!has(key) || isNull(key)) continue
        val value: Any? = opt(key).takeUnless { it === JSONObject.NULL }
        val parsed = when (value) {
            is Number -> value.toDouble()
            is String -> value.toDoubleOrNull()
            null -> null
            else -> null
        } ?: continue
        return if (parsed < 10_000_000_000L) (parsed * 1000).toLong() else parsed.toLong()
    }
    return null
}


private fun InstallDraft.toJsonPayload(): JSONObject = JSONObject()
    .put("distro", distro)
    .put("name", name)
    .put("username", username)
    .put("arch", arch)
    .put("preset", preset)
    .put("profile", profile)
    .put("desktop", desktop)
    .put("release", release.takeIf(String::isNotBlank) ?: JSONObject.NULL)
    .put("version", version.takeIf(String::isNotBlank) ?: JSONObject.NULL)
    .put("mirror", mirror)

private fun JSONObject.toInstallFormSummary(): InstallFormSummary {
    val defaults = optJSONObject("defaults") ?: JSONObject()
    return InstallFormSummary(
        distros = optJSONArray("distros").labelsFromObjects(),
        architectures = optJSONArray("architectures").labelsFromObjects(),
        presets = optJSONArray("presets").labelsFromObjects(),
        profiles = optJSONArray("profiles").labelsFromObjects(),
        desktops = optJSONArray("desktops").labelsFromObjects(),
        mirrors = optJSONArray("mirrors").labelsFromObjects(),
        defaultName = defaults.optString("name", "ubuntu"),
        defaultUsername = defaults.optString("username", ""),
    )
}

private fun JSONObject.toPreviewSummary(title: String): PreviewSummary {
    val blocking = optJSONArray("blocking").messagesFromObjects()
    val warnings = optJSONArray("warnings").toStringListLocal()
    val body = firstString("message", "summary", "kind").ifBlank {
        if (optBoolean("ok", false)) "Preview is ready." else "Preview has blocking issues."
    }
    return PreviewSummary(
        title = title,
        ok = optBoolean("ok", false),
        body = body,
        blocking = blocking,
        warnings = warnings,
        rawJson = toString(),
        previewId = optString("previewId"),
        payloadHash = optString("payloadHash"),
        resourceRevision = optString("resourceRevision"),
        actionOperation = optString("actionOperation"),
        expiresAt = optDouble("expiresAt", 0.0),
    )
}

private fun JSONObject.toSnapshotSummary(): SnapshotSummary = SnapshotSummary(
    name = firstString("name", "snapshot", "snapshotName"),
    chrootName = firstString("chrootName", "chroot_name", "targetName"),
    kind = firstString("kind").ifBlank { "copy" },
    path = firstString("path"),
    createdAt = firstString("createdAt", "created_at"),
    note = firstString("note"),
    sizeBytes = optLong("sizeBytes", optLong("size_bytes", 0L)),
)

private fun JSONObject.toUserSummary(): UserSummary = UserSummary(
    username = firstString("username", "name"),
    uid = firstString("uid"),
    gid = firstString("gid"),
    home = firstString("home"),
    shell = firstString("shell"),
    sudo = optBoolean("sudo", false),
)

private fun JSONObject.toServiceUnitSummary(): ServiceUnitSummary = ServiceUnitSummary(
    service = firstString("service", "name"),
    chrootName = firstString("chroot", "chrootName", "name"),
    status = firstString("status").ifBlank { "unknown" },
    enabled = firstString("enabled").lowercase() in setOf("yes", "true", "enabled", "1"),
    boot = firstString("boot").lowercase() in setOf("yes", "true", "enabled", "1"),
    description = firstString("description"),
)

private fun JSONObject.toServiceUnitDetailSummary(): ServiceUnitSummary {
    val status = optJSONObject("status") ?: JSONObject()
    val journal = optJSONObject("journal") ?: JSONObject()
    return ServiceUnitSummary(
        service = status.firstString("service", "name"),
        chrootName = status.firstString("chroot", "chrootName"),
        status = status.firstString("status").ifBlank { "unknown" },
        enabled = status.optBoolean("enabled", false),
        boot = status.optJSONArray("wanted_by").toStringListLocal().contains("boot.target"),
        description = status.firstString("description"),
        journalText = journal.firstString("text"),
    )
}


private fun JSONObject.toCatalogEntrySummary(): CatalogEntrySummary = CatalogEntrySummary(
    kind = firstString("kind").ifBlank { "tool" },
    name = firstString("name"),
    description = firstString("description"),
    distros = optJSONArray("distros").toStringListLocal(),
    categories = optJSONArray("categories").toStringListLocal(),
)

private fun JSONObject.toPackageInventorySummary(): PackageInventorySummary = PackageInventorySummary(
    name = firstString("name"),
    count = optInt("count", 0),
    packages = optJSONArray("packages").toStringListLocal(),
    truncated = optBoolean("truncated", false),
)

private fun JSONObject.toPackageCompareSummary(): PackageCompareSummary = PackageCompareSummary(
    left = firstString("left"),
    right = firstString("right"),
    leftCount = optInt("left_count", optInt("leftCount", 0)),
    rightCount = optInt("right_count", optInt("rightCount", 0)),
    commonCount = optInt("common_count", optInt("commonCount", 0)),
    onlyLeft = optJSONArray("only_left").toStringListLocal().ifEmpty { optJSONArray("onlyLeft").toStringListLocal() },
    onlyRight = optJSONArray("only_right").toStringListLocal().ifEmpty { optJSONArray("onlyRight").toStringListLocal() },
)

private fun JSONObject.toTransferInspectionSummary(): PreviewSummary {
    val archive = firstString("archive")
    val sourceName = firstString("source_name", "sourceName", "suggested_name", "suggestedName")
    val body = listOfNotNull(
        archive.takeIf(String::isNotBlank),
        sourceName.takeIf(String::isNotBlank),
        firstString("arch").takeIf(String::isNotBlank),
    ).joinToString(" · ").ifBlank { "Archive inspection is ready." }
    return PreviewSummary(
        title = "Import inspection",
        ok = true,
        body = body,
        blocking = emptyList(),
        warnings = if (optBoolean("target_exists", optBoolean("targetExists", false))) listOf("Target already exists; choose a conflict strategy.") else emptyList(),
        rawJson = toString(),
    )
}

private fun JSONObject.toTransferArtifactSummary(): TransferArtifactSummary = TransferArtifactSummary(
    artifactId = firstString("artifactId", "artifact_id"),
    name = firstString("name"),
    path = firstString("path"),
    kind = firstString("kind"),
    sizeBytes = optLong("size_bytes", optLong("sizeBytes", 0L)),
    modifiedAt = firstString("modified_at", "modifiedAt"),
    expiresAt = firstString("expiresAt", "expires_at"),
)

private fun JSONObject.toRuntimeRows(): List<SystemRowSummary> = rowsFromJson(
    preferredArrayKeys = listOf("runtime", "rows", "checks"),
    fallbackPrefix = "runtime",
)

private fun JSONObject.toModuleRows(): List<SystemRowSummary> = rowsFromJson(
    preferredArrayKeys = listOf("module", "rows", "checks"),
    fallbackPrefix = "module",
)

private fun JSONObject.rowsFromJson(
    preferredArrayKeys: List<String>,
    fallbackPrefix: String,
): List<SystemRowSummary> {
    preferredArrayKeys.forEach { key ->
        val rows = optJSONArray(key).toSystemRows()
        if (rows.isNotEmpty()) return rows
    }
    val nestedRows = buildList {
        keys().forEach { key ->
            val value: Any? = opt(key).takeUnless { it === JSONObject.NULL }
            when (value) {
                is JSONObject -> add(
                    SystemRowSummary(
                        label = value.firstString("label", "id", "name").ifBlank { key },
                        value = value.firstString("value", "detail", "message", "status", "state").ifBlank { value.toString() },
                        state = value.firstString("state", "status", "severity").ifBlank { "info" },
                    ),
                )
                is JSONArray -> Unit
                null -> Unit
                else -> add(SystemRowSummary(label = key, value = value.toString(), state = "info"))
            }
        }
    }
    if (nestedRows.isNotEmpty()) return nestedRows
    return listOf(SystemRowSummary(label = fallbackPrefix, value = toString(), state = "info"))
}

private fun JSONArray?.toSystemRows(): List<SystemRowSummary> {
    if (this == null) return emptyList()
    return buildList {
        for (index in 0 until length()) {
            val value = opt(index)
            if (value is JSONObject) {
                add(
                    SystemRowSummary(
                        label = value.firstString("label", "id", "name", "check").ifBlank { "row ${index + 1}" },
                        value = value.firstString("value", "detail", "message", "status", "state").ifBlank { value.toString() },
                        state = value.firstString("state", "status", "severity").ifBlank { "info" },
                    ),
                )
            } else if (value != null && value != JSONObject.NULL) {
                add(SystemRowSummary(label = "row ${index + 1}", value = value.toString(), state = "info"))
            }
        }
    }
}

private fun JSONObject.toRepairPreviewSummary(): PreviewSummary = toPreviewSummary("Registry repair preview")

private fun JSONObject.toRepairItemSummaries(): List<RepairItemSummary> {
    val array = optJSONArray("items") ?: optJSONArray("selected") ?: JSONArray()
    return array.toJsonObjects().map { item ->
        RepairItemSummary(
            itemId = item.firstString("item_id", "itemId", "id"),
            name = item.firstString("name"),
            kind = item.firstString("kind"),
            severity = item.firstString("severity").ifBlank { "warn" },
            action = item.firstString("action").ifBlank { "skip" },
            summary = item.firstString("summary"),
            impact = item.firstString("impact"),
        )
    }.filter { it.itemId.isNotBlank() }
}

private fun JSONObject.toDebugProbeSummary(): DebugProbeSummary = DebugProbeSummary(
    group = firstString("group").ifBlank { "general" },
    code = firstString("code", "id", "name"),
    status = firstString("status", "state").ifBlank { "unknown" },
    detail = firstString("detail", "message", "summary"),
    next = firstString("next", "nextStep", "next_step"),
)

private fun JSONObject.toDebugTimelineSummary(): DebugTimelineSummary = DebugTimelineSummary(
    eventType = firstString("eventType", "event_type", "type").ifBlank { "event" },
    target = firstString("target", "name", "scope"),
    result = firstString("result", "status", "state").ifBlank { "info" },
    message = firstString("message", "detail", "summary").ifBlank { toString() },
)

private fun JSONArray?.labelsFromObjects(): List<String> {
    if (this == null) return emptyList()
    return buildList {
        for (index in 0 until length()) {
            val value = opt(index)
            if (value is JSONObject) {
                add(value.firstString("label", "id", "name").ifBlank { value.toString() })
            } else if (value != null) {
                add(value.toString())
            }
        }
    }
}

private fun JSONArray?.messagesFromObjects(): List<String> {
    if (this == null) return emptyList()
    return buildList {
        for (index in 0 until length()) {
            val value = opt(index)
            if (value is JSONObject) {
                add(value.firstString("message", "code", "title").ifBlank { value.toString() })
            } else if (value != null) {
                add(value.toString())
            }
        }
    }
}

private fun JSONArray?.toStringListLocal(): List<String> {
    if (this == null) return emptyList()
    return buildList {
        for (index in 0 until length()) add(optString(index))
    }
}

private fun chrootScope(name: String): String = "chroot:$name"
