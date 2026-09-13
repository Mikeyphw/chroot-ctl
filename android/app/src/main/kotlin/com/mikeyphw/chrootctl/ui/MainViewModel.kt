package com.mikeyphw.chrootctl.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.mikeyphw.chrootctl.model.ChrootDetail
import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.HomeSnapshot
import com.mikeyphw.chrootctl.model.SnapshotPane
import com.mikeyphw.chrootctl.model.StoragePane
import com.mikeyphw.chrootctl.model.LogsPane
import com.mikeyphw.chrootctl.model.PreviewSummary
import com.mikeyphw.chrootctl.model.InstallFormSummary
import com.mikeyphw.chrootctl.model.InstallDraft
import com.mikeyphw.chrootctl.model.Loadable
import com.mikeyphw.chrootctl.model.OperationDetail
import com.mikeyphw.chrootctl.model.OperationSummary
import com.mikeyphw.chrootctl.model.ToolCapabilityGroup
import com.mikeyphw.chrootctl.model.UsersPane
import com.mikeyphw.chrootctl.model.ServicesPane
import com.mikeyphw.chrootctl.model.TransferPane
import com.mikeyphw.chrootctl.model.PackagePane
import com.mikeyphw.chrootctl.model.CatalogPane
import com.mikeyphw.chrootctl.model.DebugPane
import com.mikeyphw.chrootctl.model.SystemSupportPane
import com.mikeyphw.chrootctl.repository.BridgeRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

sealed interface RefreshState {
    data object Idle : RefreshState
    data object Refreshing : RefreshState
    data class Failed(val message: String) : RefreshState
}

data class MainUiState(
    val home: Loadable<HomeSnapshot> = Loadable.Loading,
    val chroots: List<ChrootSummary> = emptyList(),
    val selectedChrootName: String? = null,
    val chrootDetail: ChrootDetail = ChrootDetail(null, emptyList(), refreshing = false, errorMessage = null),
    val operations: List<OperationSummary> = emptyList(),
    val selectedOperationId: String? = null,
    val operationDetail: OperationDetail = OperationDetail(null, emptyList(), refreshing = false, errorMessage = null),
    val toolGroups: List<ToolCapabilityGroup> = emptyList(),
    val installDraft: InstallDraft = InstallDraft(),
    val installForm: InstallFormSummary = InstallFormSummary(),
    val installPreview: PreviewSummary? = null,
    val lifecyclePreview: PreviewSummary? = null,
    val snapshotPane: SnapshotPane = SnapshotPane(),
    val storagePane: StoragePane = StoragePane(),
    val logsPane: LogsPane = LogsPane(),
    val usersPane: UsersPane = UsersPane(),
    val servicesPane: ServicesPane = ServicesPane(),
    val catalogPane: CatalogPane = CatalogPane(),
    val packagePane: PackagePane = PackagePane(),
    val transferPane: TransferPane = TransferPane(),
    val systemSupportPane: SystemSupportPane = SystemSupportPane(),
    val debugPane: DebugPane = DebugPane(),
    val refreshState: RefreshState = RefreshState.Idle,
)

private data class PrimaryUiSlice(
    val home: Loadable<HomeSnapshot>,
    val chroots: List<ChrootSummary>,
    val operations: List<OperationSummary>,
    val selectedChrootName: String?,
    val chrootDetail: ChrootDetail,
)


private data class TertiaryUiSlice(
    val installDraft: InstallDraft,
    val installForm: InstallFormSummary,
    val installPreview: PreviewSummary?,
    val lifecyclePreview: PreviewSummary?,
    val snapshotPane: SnapshotPane,
)

private data class SecondaryUiSlice(
    val selectedOperationId: String?,
    val operationDetail: OperationDetail,
    val toolGroups: List<ToolCapabilityGroup>,
    val refreshState: RefreshState,
)

private data class ChrootManagementSlice(
    val usersPane: UsersPane,
    val servicesPane: ServicesPane,
    val storagePane: StoragePane,
    val logsPane: LogsPane,
)

private data class ToolsUiSlice(
    val catalogPane: CatalogPane,
    val packagePane: PackagePane,
    val transferPane: TransferPane,
    val systemSupportPane: SystemSupportPane,
    val debugPane: DebugPane,
)

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class MainViewModel(private val repository: BridgeRepository) : ViewModel() {
    private val refreshState = MutableStateFlow<RefreshState>(RefreshState.Idle)
    private val availableWorkspaceOperations = MutableStateFlow<Set<String>?>(null)
    private val toolGroups = MutableStateFlow<List<ToolCapabilityGroup>>(emptyList())
    private val selectedChrootName = MutableStateFlow<String?>(null)
    private val selectedOperationId = MutableStateFlow<String?>(null)
    private val chrootDetailRefresh = MutableStateFlow<RefreshState>(RefreshState.Idle)
    private val operationDetailRefresh = MutableStateFlow<RefreshState>(RefreshState.Idle)
    private val installDraft = MutableStateFlow(InstallDraft())
    private val installForm = MutableStateFlow(InstallFormSummary())
    private val installPreview = MutableStateFlow<PreviewSummary?>(null)
    private val lifecyclePreview = MutableStateFlow<PreviewSummary?>(null)
    private val snapshotPane = MutableStateFlow(SnapshotPane())
    private val storagePane = MutableStateFlow(StoragePane())
    private val logsPane = MutableStateFlow(LogsPane())
    private val usersPane = MutableStateFlow(UsersPane())
    private val servicesPane = MutableStateFlow(ServicesPane())
    private var installPreviewRequestPayload: String? = null
    private var lifecyclePreviewRequestKey: String? = null
    private var snapshotPreviewRequestKey: String? = null
    private var userPreviewRequestPayload: String? = null
    private var servicePreviewRequestPayload: String? = null
    private val catalogPane = MutableStateFlow(CatalogPane())
    private var catalogRefreshRequestPayload: String? = null
    private var catalogPreviewRequestPayload: String? = null
    private val packagePane = MutableStateFlow(PackagePane())
    private val transferPane = MutableStateFlow(TransferPane())
    private var transferImportPreviewRequestPayload: String? = null
    private var transferExportPreviewRequestPayload: String? = null
    private var artifactCleanupPreviewRequestPayload: String? = null
    private val systemSupportPane = MutableStateFlow(SystemSupportPane())
    private val debugPane = MutableStateFlow(DebugPane())

    private val selectedChrootDetail = combine(
        repository.chroots,
        selectedChrootName,
        selectedChrootName.flatMapLatest { name -> repository.chrootChecks(name) },
        chrootDetailRefresh,
    ) { chroots, name, checks, refresh ->
        val selected = name?.let { wanted -> chroots.firstOrNull { it.name == wanted } }
        ChrootDetail(
            chroot = selected,
            checks = checks,
            refreshing = refresh is RefreshState.Refreshing,
            errorMessage = (refresh as? RefreshState.Failed)?.message,
        )
    }

    private val selectedOperationDetail = combine(
        selectedOperationId.flatMapLatest { id -> repository.operation(id) },
        selectedOperationId.flatMapLatest { id -> repository.operationEvents(id) },
        operationDetailRefresh,
    ) { operation, events, refresh ->
        OperationDetail(
            operation = operation,
            events = events,
            refreshing = refresh is RefreshState.Refreshing,
            errorMessage = (refresh as? RefreshState.Failed)?.message,
        )
    }

    private val primaryUiSlice = combine(
        repository.cachedHome,
        repository.chroots,
        repository.operations,
        selectedChrootName.asStateFlow(),
        selectedChrootDetail,
    ) { home, chroots, operations, name, detail ->
        PrimaryUiSlice(
            home = home,
            chroots = chroots,
            operations = operations,
            selectedChrootName = name,
            chrootDetail = detail,
        )
    }

    private val secondaryUiSlice = combine(
        selectedOperationId.asStateFlow(),
        selectedOperationDetail,
        toolGroups.asStateFlow(),
        refreshState.asStateFlow(),
    ) { operationId, detail, groups, state ->
        SecondaryUiSlice(
            selectedOperationId = operationId,
            operationDetail = detail,
            toolGroups = groups,
            refreshState = state,
        )
    }


    private val tertiaryUiSlice = combine(
        installDraft.asStateFlow(),
        installForm.asStateFlow(),
        installPreview.asStateFlow(),
        lifecyclePreview.asStateFlow(),
        snapshotPane.asStateFlow(),
    ) { draft, form, preview, lifecycle, snapshots ->
        TertiaryUiSlice(
            installDraft = draft,
            installForm = form,
            installPreview = preview,
            lifecyclePreview = lifecycle,
            snapshotPane = snapshots,
        )
    }

    private val chrootManagementSlice = combine(
        usersPane.asStateFlow(),
        servicesPane.asStateFlow(),
        storagePane.asStateFlow(),
        logsPane.asStateFlow(),
    ) { users, services, storage, logs ->
        ChrootManagementSlice(
            usersPane = users,
            servicesPane = services,
            storagePane = storage,
            logsPane = logs,
        )
    }

    private val toolsUiSlice = combine(
        catalogPane.asStateFlow(),
        packagePane.asStateFlow(),
        transferPane.asStateFlow(),
        systemSupportPane.asStateFlow(),
        debugPane.asStateFlow(),
    ) { catalog, packages, transfer, systemSupport, debug ->
        ToolsUiSlice(
            catalogPane = catalog,
            packagePane = packages,
            transferPane = transfer,
            systemSupportPane = systemSupport,
            debugPane = debug,
        )
    }

    val uiState: StateFlow<MainUiState> = combine(
        primaryUiSlice,
        secondaryUiSlice,
        tertiaryUiSlice,
        chrootManagementSlice,
        toolsUiSlice,
    ) { primary, secondary, tertiary, management, tools ->
        MainUiState(
            home = primary.home,
            chroots = primary.chroots,
            operations = primary.operations,
            selectedChrootName = primary.selectedChrootName,
            chrootDetail = primary.chrootDetail,
            selectedOperationId = secondary.selectedOperationId,
            operationDetail = secondary.operationDetail,
            toolGroups = secondary.toolGroups,
            installDraft = tertiary.installDraft,
            installForm = tertiary.installForm,
            installPreview = tertiary.installPreview,
            lifecyclePreview = tertiary.lifecyclePreview,
            snapshotPane = tertiary.snapshotPane,
            storagePane = management.storagePane,
            logsPane = management.logsPane,
            usersPane = management.usersPane,
            servicesPane = management.servicesPane,
            catalogPane = tools.catalogPane,
            packagePane = tools.packagePane,
            transferPane = tools.transferPane,
            systemSupportPane = tools.systemSupportPane,
            debugPane = tools.debugPane,
            refreshState = secondary.refreshState,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(STOP_TIMEOUT_MS), MainUiState())

    init {
        viewModelScope.launch {
            repository.chroots.collect { rows ->
                val selected = selectedChrootName.value ?: return@collect
                if (rows.none { it.name == selected && !it.stale }) clearSelectedChroot(selected)
            }
        }
        refresh()
        refreshInstallForm()
        refreshCatalog("tool")
        refreshTransferArtifacts()
        refreshSystemSupport()
        refreshDebugWorkbench()
    }

    fun refresh() {
        viewModelScope.launch {
            refreshState.value = RefreshState.Refreshing
            repository.refreshHome()
                .onSuccess { snapshot ->
                    val operations = snapshot.capabilities.operations.toSet()
                    availableWorkspaceOperations.value = operations
                    toolGroups.value = repository.capabilityGroups(snapshot.capabilities)
                    selectedChrootName.value?.let { name -> refreshCapabilityGatedChrootRooms(name, operations) }
                    refreshState.value = RefreshState.Idle
                }
                .onFailure { error ->
                    refreshState.value = RefreshState.Failed(error.message ?: error.javaClass.simpleName)
                }
        }
    }

    fun selectChroot(name: String) {
        if (selectedChrootName.value != name) clearTargetScopedState()
        selectedChrootName.value = name
        lifecyclePreview.value = null
        refreshChrootDetail(name)
        refreshCapabilityGatedChrootRooms(name, availableWorkspaceOperations.value)
    }

    fun refreshSelectedChroot() {
        selectedChrootName.value?.let { name ->
            refreshChrootDetail(name)
            refreshCapabilityGatedChrootRooms(name, availableWorkspaceOperations.value)
        }
    }

    private fun refreshCapabilityGatedChrootRooms(name: String, operations: Set<String>?) {
        if (workspaceTabSupported(ChrootWorkspaceTab.Users, operations)) refreshUsers(name)
        if (workspaceTabSupported(ChrootWorkspaceTab.Services, operations)) refreshServices(name)
    }

    private fun clearSelectedChroot(expected: String? = null) {
        if (expected != null && selectedChrootName.value != expected) return
        selectedChrootName.value = null
        clearTargetScopedState()
    }

    private fun clearTargetScopedState() {
        lifecyclePreviewRequestKey = null
        snapshotPreviewRequestKey = null
        lifecyclePreview.value = null
        snapshotPane.value = SnapshotPane()
        storagePane.value = StoragePane()
        logsPane.value = LogsPane()
        userPreviewRequestPayload = null
        servicePreviewRequestPayload = null
        catalogRefreshRequestPayload = null
        catalogPreviewRequestPayload = null
        usersPane.value = UsersPane()
        servicesPane.value = ServicesPane()
        packagePane.value = PackagePane()
        catalogPane.value = catalogPane.value.copy(targetName = null, preview = null)
    }

    private fun isCurrentTarget(name: String): Boolean = selectedChrootName.value == name

    fun selectOperation(operationId: String) {
        selectedOperationId.value = operationId
        refreshOperationDetail(operationId)
    }

    fun refreshSelectedOperation() {
        selectedOperationId.value?.let(::refreshOperationDetail)
    }

    fun cancelOperation(operationId: String) {
        viewModelScope.launch {
            operationDetailRefresh.value = RefreshState.Refreshing
            repository.cancelOperation(operationId)
                .onSuccess { operationDetailRefresh.value = RefreshState.Idle }
                .onFailure { error -> operationDetailRefresh.value = RefreshState.Failed(error.message ?: error.javaClass.simpleName) }
        }
    }

    fun retryOperationPayloadJson(operationId: String, repair: Boolean = false): String = JSONObject()
        .put("operationId", operationId)
        .put("mode", if (repair) "repair" else "retry")
        .toString()

    private fun refreshChrootDetail(name: String) {
        viewModelScope.launch {
            chrootDetailRefresh.value = RefreshState.Refreshing
            repository.refreshChrootDetail(name)
                .onSuccess { if (isCurrentTarget(name)) chrootDetailRefresh.value = RefreshState.Idle }
                .onFailure { error -> if (isCurrentTarget(name)) chrootDetailRefresh.value = RefreshState.Failed(error.message ?: error.javaClass.simpleName) }
        }
    }

    private fun refreshOperationDetail(operationId: String) {
        viewModelScope.launch {
            operationDetailRefresh.value = RefreshState.Refreshing
            repository.refreshOperationDetail(operationId)
                .onSuccess { operationDetailRefresh.value = RefreshState.Idle }
                .onFailure { error -> operationDetailRefresh.value = RefreshState.Failed(error.message ?: error.javaClass.simpleName) }
        }
    }


    fun updateInstallDraft(draft: InstallDraft) {
        installPreviewRequestPayload = null
        installDraft.value = draft
        installPreview.value = null
    }

    fun clearInstallPreview() {
        installPreviewRequestPayload = null
        installPreview.value = null
    }

    fun refreshInstallForm() {
        viewModelScope.launch {
            installForm.value = installForm.value.copy(refreshing = true, errorMessage = null)
            repository.refreshInstallForm(installDraft.value)
                .onSuccess { form -> installForm.value = form.copy(refreshing = false, errorMessage = null) }
                .onFailure { error ->
                    installForm.value = installForm.value.copy(
                        refreshing = false,
                        errorMessage = error.message ?: error.javaClass.simpleName,
                    )
                }
        }
    }

    fun previewInstall() {
        val draft = installDraft.value
        val requestPayload = draft.toJsonPayload().toString()
        installPreviewRequestPayload = requestPayload
        installPreview.value = null
        viewModelScope.launch {
            repository.previewInstall(draft)
                .onSuccess { preview ->
                    if (installPreviewRequestPayload == requestPayload && installDraft.value.toJsonPayload().toString() == requestPayload) {
                        installPreview.value = preview
                    }
                }
                .onFailure { error ->
                    if (installPreviewRequestPayload == requestPayload && installDraft.value.toJsonPayload().toString() == requestPayload) {
                        installPreview.value = errorPreview("Install preview", error)
                    }
                }
        }
    }

    fun installPayloadJson(): String = installDraft.value.toJsonPayload()
        .withPreviewContract(installPreview.value, "install.run")
        .toString()

    fun lifecyclePayloadJson(name: String, action: String): String = JSONObject()
        .put("name", name)
        .withPreviewContract(lifecyclePreview.value, "chroots.$action")
        .toString()

    fun removePayloadJson(name: String, confirmation: String): String = JSONObject()
        .put("name", name)
        .put("confirmation", confirmation)
        .withPreviewContract(lifecyclePreview.value, "chroots.remove.execute")
        .toString()

    fun previewLifecycle(name: String, action: String) {
        val requestKey = "$name\u001f${action.trim().lowercase()}"
        lifecyclePreviewRequestKey = requestKey
        viewModelScope.launch {
            lifecyclePreview.value = null
            repository.previewLifecycle(name, action)
                .onSuccess { preview ->
                    if (lifecyclePreviewRequestKey == requestKey && isCurrentTarget(name)) lifecyclePreview.value = preview
                }
                .onFailure { error ->
                    if (lifecyclePreviewRequestKey == requestKey && isCurrentTarget(name)) lifecyclePreview.value = errorPreview("Lifecycle preview", error)
                }
        }
    }

    fun clearLifecyclePreview() {
        lifecyclePreviewRequestKey = null
        lifecyclePreview.value = null
    }

    fun refreshSnapshots(name: String) {
        viewModelScope.launch {
            snapshotPane.value = snapshotPane.value.copy(targetName = name, refreshing = true, errorMessage = null)
            repository.refreshSnapshots(name)
                .onSuccess { rows -> if (isCurrentTarget(name) && snapshotPane.value.targetName == name) snapshotPane.value = SnapshotPane(targetName = name, snapshots = rows) }
                .onFailure { error ->
                    if (isCurrentTarget(name) && snapshotPane.value.targetName == name) {
                        snapshotPane.value = snapshotPane.value.copy(
                            targetName = name,
                            refreshing = false,
                            errorMessage = error.message ?: error.javaClass.simpleName,
                        )
                    }
                }
        }
    }

    fun refreshStorage(name: String) {
        viewModelScope.launch {
            storagePane.value = storagePane.value.copy(targetName = name, refreshing = true, errorMessage = null)
            repository.refreshStorage(name)
                .onSuccess { summary -> if (isCurrentTarget(name) && storagePane.value.targetName == name) storagePane.value = StoragePane(targetName = name, summary = summary) }
                .onFailure { error ->
                    if (isCurrentTarget(name) && storagePane.value.targetName == name) {
                        storagePane.value = storagePane.value.copy(
                            targetName = name,
                            refreshing = false,
                            errorMessage = error.message ?: error.javaClass.simpleName,
                        )
                    }
                }
        }
    }

    fun refreshLogs(name: String, level: String? = null) {
        viewModelScope.launch {
            val normalizedLevel = level?.takeIf(String::isNotBlank)
            logsPane.value = logsPane.value.copy(
                targetName = name,
                level = normalizedLevel.orEmpty(),
                refreshing = true,
                errorMessage = null,
            )
            repository.refreshLogs(name, normalizedLevel)
                .onSuccess { (logFile, entries) ->
                    if (isCurrentTarget(name) && logsPane.value.targetName == name && logsPane.value.level == normalizedLevel.orEmpty()) {
                        logsPane.value = LogsPane(
                            targetName = name,
                            logFile = logFile,
                            level = normalizedLevel.orEmpty(),
                            entries = entries,
                        )
                    }
                }
                .onFailure { error ->
                    if (isCurrentTarget(name) && logsPane.value.targetName == name) {
                        logsPane.value = logsPane.value.copy(
                            targetName = name,
                            refreshing = false,
                            errorMessage = error.message ?: error.javaClass.simpleName,
                        )
                    }
                }
        }
    }

    fun previewSnapshotCreate(name: String, snapshot: String) {
        val requestKey = "$name\u001fcreate\u001f$snapshot"
        snapshotPreviewRequestKey = requestKey
        viewModelScope.launch {
            if (!isCurrentTarget(name)) return@launch
            snapshotPane.value = snapshotPane.value.copy(preview = null, previewAction = "", previewSnapshot = "")
            repository.previewSnapshotCreate(name, snapshot)
                .onSuccess { preview ->
                    if (snapshotPreviewRequestKey == requestKey && isCurrentTarget(name) && snapshotPane.value.targetName == name) {
                        snapshotPane.value = snapshotPane.value.copy(
                            targetName = name,
                            preview = preview,
                            previewAction = "create",
                            previewSnapshot = snapshot,
                        )
                    }
                }
                .onFailure { error ->
                    if (snapshotPreviewRequestKey == requestKey && isCurrentTarget(name) && snapshotPane.value.targetName == name) {
                        snapshotPane.value = snapshotPane.value.copy(
                            targetName = name,
                            preview = errorPreview("Snapshot preview", error),
                            previewAction = "create",
                            previewSnapshot = snapshot,
                        )
                    }
                }
        }
    }

    fun previewSnapshotAction(name: String, snapshot: String, action: String) {
        val normalizedAction = action.trim().lowercase()
        val requestKey = "$name\u001f$normalizedAction\u001f$snapshot"
        snapshotPreviewRequestKey = requestKey
        viewModelScope.launch {
            if (!isCurrentTarget(name)) return@launch
            snapshotPane.value = snapshotPane.value.copy(preview = null, previewAction = "", previewSnapshot = "")
            repository.previewSnapshotAction(name, snapshot, normalizedAction)
                .onSuccess { preview ->
                    if (snapshotPreviewRequestKey == requestKey && isCurrentTarget(name) && snapshotPane.value.targetName == name) {
                        snapshotPane.value = snapshotPane.value.copy(
                            targetName = name,
                            preview = preview,
                            previewAction = normalizedAction,
                            previewSnapshot = snapshot,
                        )
                    }
                }
                .onFailure { error ->
                    if (snapshotPreviewRequestKey == requestKey && isCurrentTarget(name) && snapshotPane.value.targetName == name) {
                        snapshotPane.value = snapshotPane.value.copy(
                            targetName = name,
                            preview = errorPreview("Snapshot preview", error),
                            previewAction = normalizedAction,
                            previewSnapshot = snapshot,
                        )
                    }
                }
        }
    }

    fun clearSnapshotPreview() {
        snapshotPreviewRequestKey = null
        snapshotPane.value = snapshotPane.value.copy(preview = null, previewAction = "", previewSnapshot = "")
    }

    fun snapshotCreatePayloadJson(name: String, snapshot: String): String = JSONObject()
        .put("name", name)
        .put("snapshot", snapshot)
        .withPreviewContract(snapshotPane.value.preview, "snapshots.create")
        .toString()

    fun snapshotRestorePayloadJson(name: String, snapshot: String, confirmation: String): String = JSONObject()
        .put("name", name)
        .put("snapshot", snapshot)
        .put("confirmation", confirmation)
        .withPreviewContract(snapshotPane.value.preview, "snapshots.restore")
        .toString()

    fun snapshotExportPayloadJson(name: String, snapshot: String): String = JSONObject()
        .put("name", name)
        .put("snapshot", snapshot)
        .withPreviewContract(snapshotPane.value.preview, "snapshots.export")
        .toString()

    fun refreshUsers(name: String) {
        viewModelScope.launch {
            usersPane.value = usersPane.value.copy(targetName = name, refreshing = true, errorMessage = null)
            repository.refreshUsers(name)
                .onSuccess { rows -> if (isCurrentTarget(name) && usersPane.value.targetName == name) usersPane.value = UsersPane(targetName = name, users = rows) }
                .onFailure { error ->
                    if (isCurrentTarget(name) && usersPane.value.targetName == name) {
                        usersPane.value = usersPane.value.copy(
                            targetName = name,
                            refreshing = false,
                            errorMessage = error.message ?: error.javaClass.simpleName,
                        )
                    }
                }
        }
    }

    fun clearUserPreview() {
        userPreviewRequestPayload = null
        usersPane.value = usersPane.value.copy(preview = null)
    }

    fun previewUserAction(payloadJson: String) {
        userPreviewRequestPayload = payloadJson
        viewModelScope.launch {
            val payload = JSONObject(payloadJson)
            val name = payload.optString("name")
            if (!isCurrentTarget(name) || usersPane.value.targetName != name) return@launch
            usersPane.value = usersPane.value.copy(preview = null)
            repository.previewUserAction(payload)
                .onSuccess { preview ->
                    if (userPreviewRequestPayload == payloadJson && isCurrentTarget(name) && usersPane.value.targetName == name) {
                        usersPane.value = usersPane.value.copy(preview = preview)
                    }
                }
                .onFailure { error ->
                    if (userPreviewRequestPayload == payloadJson && isCurrentTarget(name) && usersPane.value.targetName == name) {
                        usersPane.value = usersPane.value.copy(preview = errorPreview("User preview", error))
                    }
                }
        }
    }

    fun userAddPayloadJson(name: String, username: String, shell: String, sudo: Boolean): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "add")
        .put("shell", shell)
        .put("sudo", sudo)
        .withPreviewContract(usersPane.value.preview, "users.add")
        .toString()

    fun userRemovePayloadJson(name: String, username: String, confirmation: String, deleteHome: Boolean): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "remove")
        .put("confirmation", confirmation)
        .put("deleteHome", deleteHome)
        .withPreviewContract(usersPane.value.preview, "users.remove")
        .toString()

    fun userSyncPayloadJson(name: String, username: String): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "sync_uid_gid")
        .put("fixOwnership", true)
        .withPreviewContract(usersPane.value.preview, "users.sync_uid_gid")
        .toString()

    fun userShellPayloadJson(name: String, username: String, shell: String): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "set_shell")
        .put("shell", shell)
        .withPreviewContract(usersPane.value.preview, "users.set_shell")
        .toString()

    fun userSudoPayloadJson(name: String, username: String, enabled: Boolean): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "set_sudo")
        .put("enabled", enabled)
        .withPreviewContract(usersPane.value.preview, "users.set_sudo")
        .toString()

    fun userPasswordPayloadJson(name: String, username: String, password: String, confirmPassword: String, confirmation: String): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "set_password")
        .put("password", password)
        .put("confirmPassword", confirmPassword)
        .put("confirmation", confirmation)
        .withPreviewContract(usersPane.value.preview, "users.set_password")
        .toString()

    fun userOperationPayloadJson(operation: String, payloadJson: String): String = JSONObject(payloadJson)
        .withPreviewContract(usersPane.value.preview, operation)
        .toString()

    fun refreshServices(name: String) {
        viewModelScope.launch {
            servicesPane.value = servicesPane.value.copy(targetName = name, refreshing = true, errorMessage = null)
            repository.refreshServices(name)
                .onSuccess { rows -> if (isCurrentTarget(name) && servicesPane.value.targetName == name) servicesPane.value = ServicesPane(targetName = name, services = rows) }
                .onFailure { error ->
                    if (isCurrentTarget(name) && servicesPane.value.targetName == name) {
                        servicesPane.value = servicesPane.value.copy(
                            targetName = name,
                            refreshing = false,
                            errorMessage = error.message ?: error.javaClass.simpleName,
                        )
                    }
                }
        }
    }

    fun refreshServiceDetail(name: String, service: String) {
        viewModelScope.launch {
            servicesPane.value = servicesPane.value.copy(targetName = name, refreshing = true, errorMessage = null)
            repository.refreshServiceDetail(name, service)
                .onSuccess { row ->
                    if (isCurrentTarget(name) && servicesPane.value.targetName == name) {
                        val merged = servicesPane.value.services.map { existing -> if (existing.service == row.service) row else existing }
                        servicesPane.value = servicesPane.value.copy(
                            targetName = name,
                            services = if (merged.any { it.service == row.service }) merged else servicesPane.value.services + row,
                            selectedService = row,
                            refreshing = false,
                            errorMessage = null,
                        )
                    }
                }
                .onFailure { error ->
                    if (isCurrentTarget(name) && servicesPane.value.targetName == name) {
                        servicesPane.value = servicesPane.value.copy(
                            targetName = name,
                            refreshing = false,
                            errorMessage = error.message ?: error.javaClass.simpleName,
                        )
                    }
                }
        }
    }

    fun clearServicePreview() {
        servicePreviewRequestPayload = null
        servicesPane.value = servicesPane.value.copy(preview = null)
    }

    fun previewServiceAction(payloadJson: String) {
        servicePreviewRequestPayload = payloadJson
        viewModelScope.launch {
            val payload = JSONObject(payloadJson)
            val name = payload.optString("name")
            if (!isCurrentTarget(name) || servicesPane.value.targetName != name) return@launch
            servicesPane.value = servicesPane.value.copy(preview = null)
            repository.previewServiceAction(payload)
                .onSuccess { preview ->
                    if (servicePreviewRequestPayload == payloadJson && isCurrentTarget(name) && servicesPane.value.targetName == name) {
                        servicesPane.value = servicesPane.value.copy(preview = preview)
                    }
                }
                .onFailure { error ->
                    if (servicePreviewRequestPayload == payloadJson && isCurrentTarget(name) && servicesPane.value.targetName == name) {
                        servicesPane.value = servicesPane.value.copy(preview = errorPreview("Service preview", error))
                    }
                }
        }
    }

    fun servicePayloadJson(name: String, service: String, action: String): String = JSONObject()
        .put("name", name)
        .put("service", service)
        .put("action", action)
        .withPreviewContract(servicesPane.value.preview, "services.$action")
        .toString()

    fun serviceOperationPayloadJson(operation: String, payloadJson: String): String = JSONObject(payloadJson)
        .withPreviewContract(servicesPane.value.preview, operation)
        .toString()



    fun refreshCatalog(kind: String = catalogPane.value.kind) {
        val request = catalogPane.value.copy(kind = kind)
        val requestPayload = catalogRefreshIdentity(request)
        catalogRefreshRequestPayload = requestPayload
        viewModelScope.launch {
            catalogPane.value = catalogPane.value.copy(kind = kind, refreshing = true, errorMessage = null)
            repository.refreshCatalog(kind, request.targetName, request.query, request.category)
                .onSuccess { (entries, categories) ->
                    if (catalogRefreshRequestPayload == requestPayload && catalogRefreshIdentity(catalogPane.value) == requestPayload) {
                        val latest = catalogPane.value
                        val selected = latest.entries.filter { it.selected }.map { it.name }.toSet()
                        catalogPane.value = latest.copy(
                            entries = entries.map { entry -> entry.copy(selected = entry.name in selected) },
                            categories = categories,
                            refreshing = false,
                            errorMessage = null,
                        )
                    }
                }
                .onFailure { error ->
                    if (catalogRefreshRequestPayload == requestPayload && catalogRefreshIdentity(catalogPane.value) == requestPayload) {
                        catalogPane.value = catalogPane.value.copy(refreshing = false, errorMessage = error.message ?: error.javaClass.simpleName)
                    }
                }
        }
    }

    fun setCatalogTarget(name: String) {
        catalogRefreshRequestPayload = null
        catalogPreviewRequestPayload = null
        catalogPane.value = catalogPane.value.copy(targetName = name, preview = null, entries = emptyList())
        refreshCatalog()
    }

    fun setCatalogQuery(query: String) {
        catalogPreviewRequestPayload = null
        catalogPane.value = catalogPane.value.copy(query = query, preview = null, refreshing = false)
    }

    fun setCatalogCategory(category: String) {
        catalogRefreshRequestPayload = null
        catalogPreviewRequestPayload = null
        catalogPane.value = catalogPane.value.copy(category = category, preview = null)
        refreshCatalog()
    }

    fun toggleCatalogEntry(entryName: String) {
        catalogPreviewRequestPayload = null
        catalogPane.value = catalogPane.value.copy(
            entries = catalogPane.value.entries.map { entry -> if (entry.name == entryName) entry.copy(selected = !entry.selected) else entry },
            preview = null,
        )
    }

    fun previewCatalogApply() {
        val request = catalogPane.value
        val requestPayload = catalogPreviewIdentity(request)
        catalogPreviewRequestPayload = requestPayload
        viewModelScope.launch {
            val target = request.targetName.orEmpty()
            val names = request.entries.filter { it.selected }.map { it.name }
            repository.previewCatalog(request.kind, target, names)
                .onSuccess { preview ->
                    if (catalogPreviewRequestPayload == requestPayload && catalogPreviewIdentity(catalogPane.value) == requestPayload) {
                        catalogPane.value = catalogPane.value.copy(preview = preview)
                    }
                }
                .onFailure { error ->
                    if (catalogPreviewRequestPayload == requestPayload && catalogPreviewIdentity(catalogPane.value) == requestPayload) {
                        catalogPane.value = catalogPane.value.copy(preview = errorPreview("Catalog preview", error))
                    }
                }
        }
    }

    fun clearCatalogPreview() {
        catalogPreviewRequestPayload = null
        catalogPane.value = catalogPane.value.copy(preview = null)
    }

    fun catalogApplyPayloadJson(): String {
        val current = catalogPane.value
        return JSONObject()
            .put("kind", current.kind)
            .put("name", current.targetName.orEmpty())
            .put("names", org.json.JSONArray(current.entries.filter { it.selected }.map { it.name }))
            .withPreviewContract(current.preview, "catalog.apply")
            .toString()
    }

    fun refreshPackageInventory(name: String) {
        viewModelScope.launch {
            packagePane.value = packagePane.value.copy(leftName = name, refreshing = true, errorMessage = null)
            repository.refreshPackageInventory(name)
                .onSuccess { inventory -> packagePane.value = packagePane.value.copy(leftName = name, inventory = inventory, refreshing = false, errorMessage = null) }
                .onFailure { error -> packagePane.value = packagePane.value.copy(refreshing = false, errorMessage = error.message ?: error.javaClass.simpleName) }
        }
    }

    fun updatePackageCompare(left: String, right: String) {
        packagePane.value = packagePane.value.copy(leftName = left, rightName = right)
    }

    fun comparePackages() {
        viewModelScope.launch {
            val current = packagePane.value.copy(refreshing = true, errorMessage = null)
            packagePane.value = current
            repository.comparePackages(current.leftName, current.rightName)
                .onSuccess { comparison -> packagePane.value = current.copy(comparison = comparison, refreshing = false, errorMessage = null) }
                .onFailure { error -> packagePane.value = current.copy(refreshing = false, errorMessage = error.message ?: error.javaClass.simpleName) }
        }
    }

    fun updateTransferImportArchive(path: String) {
        transferImportPreviewRequestPayload = null
        transferPane.value = transferPane.value.copy(importArchive = path, importInspection = null, refreshing = false, errorMessage = null)
    }

    fun updateTransferImportTarget(name: String) {
        transferImportPreviewRequestPayload = null
        transferPane.value = transferPane.value.copy(importTargetName = name, importInspection = null, refreshing = false, errorMessage = null)
    }

    fun updateTransferImportPassword(password: String) {
        transferImportPreviewRequestPayload = null
        transferPane.value = transferPane.value.copy(importPassword = password, importInspection = null, refreshing = false, errorMessage = null)
    }

    fun updateTransferExportTarget(name: String) {
        transferExportPreviewRequestPayload = null
        transferPane.value = transferPane.value.copy(exportTargetName = name, exportPreview = null, refreshing = false, errorMessage = null)
    }

    fun updateTransferExportArchive(path: String) {
        transferExportPreviewRequestPayload = null
        transferPane.value = transferPane.value.copy(exportArchive = path, exportPreview = null, refreshing = false, errorMessage = null)
    }

    fun adoptSnapshotExport(path: String) {
        if (path.isBlank()) return
        transferExportPreviewRequestPayload = null
        transferPane.value = transferPane.value.copy(exportArchive = path, exportPreview = null, errorMessage = null)
        refreshTransferArtifacts()
    }

    fun inspectTransferImport() {
        val request = transferPane.value
        val requestPayload = transferImportPreviewIdentity(request)
        transferImportPreviewRequestPayload = requestPayload
        viewModelScope.launch {
            transferPane.value = transferPane.value.copy(refreshing = true, errorMessage = null)
            repository.inspectTransferImport(request.importArchive, request.importTargetName, request.conflict, request.importPassword)
                .onSuccess { preview ->
                    if (transferImportPreviewRequestPayload == requestPayload && transferImportPreviewIdentity(transferPane.value) == requestPayload) {
                        transferPane.value = transferPane.value.copy(importInspection = preview, refreshing = false, errorMessage = null)
                    }
                }
                .onFailure { error ->
                    if (transferImportPreviewRequestPayload == requestPayload && transferImportPreviewIdentity(transferPane.value) == requestPayload) {
                        transferPane.value = transferPane.value.copy(refreshing = false, errorMessage = error.message ?: error.javaClass.simpleName)
                    }
                }
        }
    }

    fun previewTransferExport() {
        val request = transferPane.value
        val requestPayload = transferExportPreviewIdentity(request)
        transferExportPreviewRequestPayload = requestPayload
        viewModelScope.launch {
            transferPane.value = transferPane.value.copy(refreshing = true, errorMessage = null)
            repository.previewTransferExport(request.exportTargetName, request.exportArchive)
                .onSuccess { preview ->
                    if (transferExportPreviewRequestPayload == requestPayload && transferExportPreviewIdentity(transferPane.value) == requestPayload) {
                        transferPane.value = transferPane.value.copy(exportPreview = preview, refreshing = false, errorMessage = null)
                    }
                }
                .onFailure { error ->
                    if (transferExportPreviewRequestPayload == requestPayload && transferExportPreviewIdentity(transferPane.value) == requestPayload) {
                        transferPane.value = transferPane.value.copy(refreshing = false, errorMessage = error.message ?: error.javaClass.simpleName)
                    }
                }
        }
    }

    fun clearTransferImportPreview() {
        transferImportPreviewRequestPayload = null
        transferPane.value = transferPane.value.copy(importInspection = null)
    }

    fun clearTransferExportPreview() {
        transferExportPreviewRequestPayload = null
        transferPane.value = transferPane.value.copy(exportPreview = null)
    }

    fun refreshTransferArtifacts() {
        artifactCleanupPreviewRequestPayload = null
        viewModelScope.launch {
            val current = transferPane.value.copy(refreshing = true, errorMessage = null)
            transferPane.value = current
            repository.refreshTransferArtifacts()
                .onSuccess { artifacts -> transferPane.value = transferPane.value.copy(artifacts = artifacts, artifactCleanupPreview = null, refreshing = false, errorMessage = null) }
                .onFailure { error -> transferPane.value = transferPane.value.copy(refreshing = false, errorMessage = error.message ?: error.javaClass.simpleName) }
        }
    }

    fun transferImportPayloadJson(): String {
        val current = transferPane.value
        val payload = JSONObject().put("archive", current.importArchive).put("conflict", current.conflict)
        current.importTargetName.takeIf(String::isNotBlank)?.let { payload.put("name", it) }
        current.importPassword.takeIf(String::isNotBlank)?.let { payload.put("password", it) }
        return payload.withPreviewContract(current.importInspection, "transfer.import").toString()
    }

    fun transferExportPayloadJson(): String = JSONObject()
        .put("name", transferPane.value.exportTargetName)
        .put("archive", transferPane.value.exportArchive.takeIf(String::isNotBlank) ?: JSONObject.NULL)
        .withPreviewContract(transferPane.value.exportPreview, "transfer.export")
        .toString()

    fun previewArtifactCleanup(path: String? = null, deleteAll: Boolean = true) {
        val requestPayload = JSONObject()
            .put("deleteAll", deleteAll)
            .apply { path?.takeIf(String::isNotBlank)?.let { put("path", it) } }
            .toString()
        artifactCleanupPreviewRequestPayload = requestPayload
        transferPane.value = transferPane.value.copy(artifactCleanupPreview = null)
        viewModelScope.launch {
            repository.previewArtifactCleanup(deleteAll = deleteAll, path = path)
                .onSuccess { preview ->
                    if (artifactCleanupPreviewRequestPayload == requestPayload) {
                        transferPane.value = transferPane.value.copy(artifactCleanupPreview = preview)
                    }
                }
                .onFailure { error ->
                    if (artifactCleanupPreviewRequestPayload == requestPayload) {
                        transferPane.value = transferPane.value.copy(artifactCleanupPreview = errorPreview("Artifact cleanup preview", error))
                    }
                }
        }
    }

    fun clearArtifactCleanupPreview() {
        artifactCleanupPreviewRequestPayload = null
        transferPane.value = transferPane.value.copy(artifactCleanupPreview = null)
    }

    fun artifactCleanupPayloadJson(path: String? = null, deleteAll: Boolean = false): String {
        val payload = JSONObject().put("deleteAll", deleteAll)
        path?.takeIf(String::isNotBlank)?.let { payload.put("path", it) }
        return payload.withPreviewContract(transferPane.value.artifactCleanupPreview, "artifacts.cleanup").toString()
    }



    fun refreshSystemSupport() {
        viewModelScope.launch {
            val current = systemSupportPane.value.copy(refreshing = true, errorMessage = null)
            systemSupportPane.value = current
            repository.refreshSystemRuntime()
                .onSuccess { (runtimeRows, moduleRows) ->
                    systemSupportPane.value = current.copy(
                        runtimeRows = runtimeRows,
                        moduleRows = moduleRows,
                        refreshing = false,
                        errorMessage = null,
                    )
                }
                .onFailure { error -> systemSupportPane.value = current.copy(refreshing = false, errorMessage = error.message ?: error.javaClass.simpleName) }
        }
    }

    fun previewSupportBundle() {
        viewModelScope.launch {
            repository.previewSupportBundle()
                .onSuccess { preview -> systemSupportPane.value = systemSupportPane.value.copy(supportPreview = preview) }
                .onFailure { error -> systemSupportPane.value = systemSupportPane.value.copy(supportPreview = errorPreview("Support bundle preview", error)) }
        }
    }

    fun previewModuleBuild() {
        viewModelScope.launch {
            repository.previewModuleBuild()
                .onSuccess { preview -> systemSupportPane.value = systemSupportPane.value.copy(moduleBuildPreview = preview) }
                .onFailure { error -> systemSupportPane.value = systemSupportPane.value.copy(moduleBuildPreview = errorPreview("Module build preview", error)) }
        }
    }

    fun previewRepair() {
        viewModelScope.launch {
            val current = systemSupportPane.value
            val decisions = if (current.repairItems.isEmpty()) null else repairDecisionsJson(current)
            repository.previewRepair(decisions)
                .onSuccess { (preview, items) ->
                    val validIds = items.map { it.itemId }.toSet()
                    systemSupportPane.value = current.copy(
                        repairPreview = preview,
                        repairItems = items,
                        selectedRepairItemIds = current.selectedRepairItemIds.intersect(validIds),
                    )
                }
                .onFailure { error -> systemSupportPane.value = current.copy(repairPreview = errorPreview("Registry repair preview", error)) }
        }
    }

    fun toggleRepairItem(itemId: String) {
        val current = systemSupportPane.value
        val next = current.selectedRepairItemIds.toMutableSet()
        if (!next.add(itemId)) next.remove(itemId)
        systemSupportPane.value = current.copy(selectedRepairItemIds = next, repairPreview = null)
    }

    fun previewTempCleanup() {
        viewModelScope.launch {
            repository.previewTempCleanup()
                .onSuccess { preview -> systemSupportPane.value = systemSupportPane.value.copy(cleanupPreview = preview) }
                .onFailure { error -> systemSupportPane.value = systemSupportPane.value.copy(cleanupPreview = errorPreview("Temporary cleanup preview", error)) }
        }
    }

    fun refreshDebugWorkbench(group: String = debugPane.value.selectedGroup) {
        viewModelScope.launch {
            val current = debugPane.value.copy(selectedGroup = group, refreshing = true, errorMessage = null)
            debugPane.value = current
            repository.refreshDebugWorkbench(group)
                .onSuccess { (probes, timeline) -> debugPane.value = current.copy(probes = probes, timeline = timeline, refreshing = false, errorMessage = null) }
                .onFailure { error -> debugPane.value = current.copy(refreshing = false, errorMessage = error.message ?: error.javaClass.simpleName) }
        }
    }

    fun supportBundlePayloadJson(): String = JSONObject()
        .withPreviewContract(systemSupportPane.value.supportPreview, "support.bundle")
        .toString()

    fun moduleBuildPayloadJson(): String = JSONObject()
        .put("allInstalled", true)
        .withPreviewContract(systemSupportPane.value.moduleBuildPreview, "system.module_build")
        .toString()

    fun repairApplyPayloadJson(): String = JSONObject()
        .put("decisions", repairDecisionsJson(systemSupportPane.value))
        .withPreviewContract(systemSupportPane.value.repairPreview, "repair.apply")
        .toString()

    fun cleanupTempPayloadJson(): String = JSONObject()
        .put("deleteAll", true)
        .withPreviewContract(systemSupportPane.value.cleanupPreview, "cleanup.temp")
        .toString()

    fun debugExportPayloadJson(): String = JSONObject().put("group", debugPane.value.selectedGroup).toString()

    fun previewSmokePlan() {
        viewModelScope.launch {
            debugPane.value = debugPane.value.copy(refreshing = true, errorMessage = null)
            repository.previewSmokePlan()
                .onSuccess { preview -> debugPane.value = debugPane.value.copy(smokePlan = preview, refreshing = false, errorMessage = null) }
                .onFailure { error -> debugPane.value = debugPane.value.copy(smokePlan = errorPreview("Smoke plan", error), refreshing = false, errorMessage = error.message ?: error.javaClass.simpleName) }
        }
    }

    fun smokeRunPayloadJson(): String = JSONObject()
        .put("scope", "real-device")
        .put("includeOptional", true)
        .withPreviewContract(debugPane.value.smokePlan, "smoke.run")
        .toString()

    fun refreshSmokeReport() {
        viewModelScope.launch {
            debugPane.value = debugPane.value.copy(refreshing = true, errorMessage = null)
            repository.refreshSmokeReport()
                .onSuccess { preview -> debugPane.value = debugPane.value.copy(smokeReport = preview, refreshing = false, errorMessage = null) }
                .onFailure { error -> debugPane.value = debugPane.value.copy(smokeReport = errorPreview("Smoke report", error), refreshing = false, errorMessage = error.message ?: error.javaClass.simpleName) }
        }
    }

    fun refreshSmokeLastResult() {
        viewModelScope.launch {
            debugPane.value = debugPane.value.copy(refreshing = true, errorMessage = null)
            repository.refreshSmokeLastResult()
                .onSuccess { preview -> debugPane.value = debugPane.value.copy(smokeLastResult = preview, refreshing = false, errorMessage = null) }
                .onFailure { error -> debugPane.value = debugPane.value.copy(smokeLastResult = errorPreview("Last smoke result", error), refreshing = false, errorMessage = error.message ?: error.javaClass.simpleName) }
        }
    }

    fun smokeResultPersistPayloadJson(): String = JSONObject().put("format", "json").toString()

    fun smokeResultExportPayloadJson(): String = JSONObject().put("format", "json").toString()

    fun smokeFailureBundlePayloadJson(): String = JSONObject().put("includeSmokeEvidence", true).toString()

    override fun onCleared() {
        // RootServiceClient is application-scoped and is also used by the
        // foreground ChrootOperationService. Activity/ViewModel teardown must
        // not unbind a connection owned by the process.
        super.onCleared()
    }

    private companion object {
        const val STOP_TIMEOUT_MS = 5_000L
    }
}


private fun repairDecisionsJson(pane: SystemSupportPane): JSONArray {
    val selected = pane.selectedRepairItemIds
    return JSONArray(
        pane.repairItems.map { item ->
            JSONObject()
                .put("item_id", item.itemId)
                .put("action", if (item.itemId in selected) item.action else "skip")
        },
    )
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

private fun transferImportPreviewIdentity(pane: TransferPane): String = JSONObject()
    .put("archive", pane.importArchive)
    .put("name", pane.importTargetName)
    .put("conflict", pane.conflict)
    .put("password", pane.importPassword)
    .toString()

private fun transferExportPreviewIdentity(pane: TransferPane): String = JSONObject()
    .put("name", pane.exportTargetName)
    .put("archive", pane.exportArchive)
    .toString()

private fun catalogRefreshIdentity(pane: CatalogPane): String = JSONObject()
    .put("kind", pane.kind)
    .put("name", pane.targetName.orEmpty())
    .put("query", pane.query)
    .put("category", pane.category)
    .toString()

private fun catalogPreviewIdentity(pane: CatalogPane): String = JSONObject()
    .put("kind", pane.kind)
    .put("name", pane.targetName.orEmpty())
    .put("names", JSONArray(pane.entries.filter { it.selected }.map { it.name }.sorted()))
    .toString()

private fun JSONObject.withPreviewContract(preview: PreviewSummary?, operation: String): JSONObject {
    if (preview == null || preview.actionOperation != operation) return this
    if (preview.previewId.isBlank() || preview.payloadHash.isBlank() || preview.resourceRevision.isBlank()) return this
    put("previewId", preview.previewId)
    put("payloadHash", preview.payloadHash)
    put("resourceRevision", preview.resourceRevision)
    return this
}

private fun errorPreview(title: String, error: Throwable): PreviewSummary = PreviewSummary(
    title = title,
    ok = false,
    body = error.message ?: error.javaClass.simpleName,
    blocking = listOf(error.message ?: error.javaClass.simpleName),
    warnings = emptyList(),
    rawJson = "{}",
)

class MainViewModelFactory(private val repository: BridgeRepository) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        require(modelClass.isAssignableFrom(MainViewModel::class.java))
        return MainViewModel(repository) as T
    }
}
