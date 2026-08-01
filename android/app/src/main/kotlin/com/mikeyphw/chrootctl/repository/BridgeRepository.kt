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
import com.mikeyphw.chrootctl.model.SnapshotSummary
import com.mikeyphw.chrootctl.model.Loadable
import com.mikeyphw.chrootctl.model.OperationEventSummary
import com.mikeyphw.chrootctl.model.OperationSummary
import com.mikeyphw.chrootctl.model.ReadinessRow
import com.mikeyphw.chrootctl.model.ReadinessState
import com.mikeyphw.chrootctl.model.RecommendedAction
import com.mikeyphw.chrootctl.model.ToolCapabilityGroup
import com.mikeyphw.chrootctl.protocol.BridgeCapabilities
import com.mikeyphw.chrootctl.protocol.BridgeEnvelope
import com.mikeyphw.chrootctl.protocol.BridgeRequest
import com.mikeyphw.chrootctl.protocol.RootBridgeInfo
import com.mikeyphw.chrootctl.root.RootServiceClient
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import org.json.JSONArray
import org.json.JSONObject

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
            dashboardJson = state.toString(),
            chrootCount = chrootEntities.size,
            operationCount = operationEntities.size,
            warningCount = warningCount,
            lastRefreshAt = now,
            stale = false,
        )
        database.chrootDao().replaceSnapshot(chrootEntities)
        operationEntities.forEach { operation -> database.operationDao().upsert(operation) }
        database.checkDao().replaceScope("home", state.extractChecks(now, "home"))
        database.homeSnapshotDao().upsert(snapshot)
        snapshot.toHomeSnapshot(chrootEntities, operationEntities)
    }

    suspend fun refreshChrootDetail(name: String): Result<Unit> = runCatching {
        val now = System.currentTimeMillis()
        val chroot = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("chroots.get", JSONObject().put("name", name)).toJson()),
        ).requireData()
        database.chrootDao().upsertAll(listOf(chroot.toChrootEntity(now)))
        val status = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("system.status", JSONObject().put("name", name).put("details", true)).toJson()),
        ).requireData()
        val doctor = BridgeEnvelope.fromJson(
            rootClient.query(BridgeRequest("system.doctor", JSONObject().put("name", name)).toJson()),
        ).requireData()
        val checks = status.extractChecks(now, chrootScope(name)) + doctor.extractChecks(now, chrootScope(name))
        database.checkDao().replaceScope(chrootScope(name), checks.ifEmpty { listOf(status.toSyntheticCheck(name, now), doctor.toSyntheticCheck(name, now)) })
    }

    suspend fun refreshOperationDetail(operationId: String): Result<Unit> = runCatching {
        val raw = rootClient.operationState(operationId)
        val data = BridgeEnvelope.fromJson(raw).requireData()
        database.operationDao().upsert(data.toOperationEntity(System.currentTimeMillis(), stale = false))
        data.optJSONArray("progressEvents")?.toJsonObjects()?.forEach { event ->
            database.operationDao().append(event.toOperationEventEntity(operationId))
        }
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
        database.operationDao().append(event.toOperationEventEntity(operationId))
        val existing = database.operationDao().findById(operationId)
        database.operationDao().upsert(event.toOperationEntity(existing))
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
        ).requireArray()
        data.toJsonObjects().map { item -> item.toSnapshotSummary() }
    }

    suspend fun previewSnapshotCreate(name: String): Result<PreviewSummary> = runCatching {
        val snapshot = "snapshot-${System.currentTimeMillis() / 1000}"
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

    suspend fun startBridgeOperation(
        operation: String,
        payload: JSONObject,
        onEvent: suspend (JSONObject) -> Unit,
    ): Result<String?> = runCatching {
        var operationId: String? = null
        val request = BridgeRequest(operation, payload).toJson()
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
    val timestampValue = opt("timestamp")
    val timestamp = when (timestampValue) {
        is Number -> (timestampValue.toDouble() * 1000).toLong()
        is String -> ((timestampValue.toDoubleOrNull() ?: System.currentTimeMillis() / 1000.0) * 1000).toLong()
        else -> System.currentTimeMillis()
    }
    val payload = optJSONObject("payload") ?: this
    return OperationEventEntity(
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

private fun countWarnings(
    dashboard: JSONObject,
    chroots: List<ChrootEntity>,
    operations: List<OperationEntity>,
): Int = chroots.sumOf { it.warningCount } + operations.count { it.state in setOf("failed", "interrupted", "blocked") } +
    dashboard.extractChecks(System.currentTimeMillis(), "home").count { it.severity.lowercase() in setOf("warn", "warning", "error", "failed", "blocked") }

private fun JSONArray.toJsonObjects(): List<JSONObject> = buildList {
    for (index in 0 until length()) {
        val value = opt(index)
        if (value is JSONObject) add(value)
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
        val value = opt(key)
        val parsed = when (value) {
            is Number -> value.toInt()
            is String -> value.toIntOrNull()
            else -> null
        }
        if (parsed != null) return parsed
    }
    return null
}

private fun JSONObject.optEpochMillis(vararg keys: String): Long? {
    for (key in keys) {
        if (!has(key) || isNull(key)) continue
        val value = opt(key)
        val parsed = when (value) {
            is Number -> value.toDouble()
            is String -> value.toDoubleOrNull()
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
        presets = optJSONArray("presets").labelsFromObjects(),
        profiles = optJSONArray("profiles").labelsFromObjects(),
        desktops = optJSONArray("desktops").labelsFromObjects(),
        mirrors = optJSONArray("mirrors").labelsFromObjects(),
        defaultName = defaults.optString("name", "ubuntu"),
        defaultUsername = defaults.optString("username", "mike"),
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
