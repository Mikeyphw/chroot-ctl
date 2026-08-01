package com.mikeyphw.chrootctl.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.mikeyphw.chrootctl.model.ChrootDetail
import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.HomeSnapshot
import com.mikeyphw.chrootctl.model.SnapshotPane
import com.mikeyphw.chrootctl.model.PreviewSummary
import com.mikeyphw.chrootctl.model.InstallFormSummary
import com.mikeyphw.chrootctl.model.InstallDraft
import com.mikeyphw.chrootctl.model.Loadable
import com.mikeyphw.chrootctl.model.OperationDetail
import com.mikeyphw.chrootctl.model.OperationSummary
import com.mikeyphw.chrootctl.model.ToolCapabilityGroup
import com.mikeyphw.chrootctl.model.UsersPane
import com.mikeyphw.chrootctl.model.ServicesPane
import com.mikeyphw.chrootctl.repository.BridgeRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
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
    val usersPane: UsersPane = UsersPane(),
    val servicesPane: ServicesPane = ServicesPane(),
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
)

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class MainViewModel(private val repository: BridgeRepository) : ViewModel() {
    private val refreshState = MutableStateFlow<RefreshState>(RefreshState.Idle)
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
    private val usersPane = MutableStateFlow(UsersPane())
    private val servicesPane = MutableStateFlow(ServicesPane())

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
    ) { users, services ->
        ChrootManagementSlice(usersPane = users, servicesPane = services)
    }

    val uiState: StateFlow<MainUiState> = combine(
        primaryUiSlice,
        secondaryUiSlice,
        tertiaryUiSlice,
        chrootManagementSlice,
    ) { primary, secondary, tertiary, management ->
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
            usersPane = management.usersPane,
            servicesPane = management.servicesPane,
            refreshState = secondary.refreshState,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(STOP_TIMEOUT_MS), MainUiState())

    init {
        refresh()
        refreshInstallForm()
    }

    fun refresh() {
        viewModelScope.launch {
            refreshState.value = RefreshState.Refreshing
            repository.refreshHome()
                .onSuccess { snapshot ->
                    toolGroups.value = repository.capabilityGroups(snapshot.capabilities)
                    refreshState.value = RefreshState.Idle
                }
                .onFailure { error ->
                    refreshState.value = RefreshState.Failed(error.message ?: error.javaClass.simpleName)
                }
        }
    }

    fun selectChroot(name: String) {
        selectedChrootName.value = name
        refreshChrootDetail(name)
        refreshUsers(name)
        refreshServices(name)
    }

    fun refreshSelectedChroot() {
        selectedChrootName.value?.let { name ->
            refreshChrootDetail(name)
            refreshUsers(name)
            refreshServices(name)
        }
    }

    fun selectOperation(operationId: String) {
        selectedOperationId.value = operationId
        refreshOperationDetail(operationId)
    }

    fun refreshSelectedOperation() {
        selectedOperationId.value?.let(::refreshOperationDetail)
    }

    private fun refreshChrootDetail(name: String) {
        viewModelScope.launch {
            chrootDetailRefresh.value = RefreshState.Refreshing
            repository.refreshChrootDetail(name)
                .onSuccess { chrootDetailRefresh.value = RefreshState.Idle }
                .onFailure { error -> chrootDetailRefresh.value = RefreshState.Failed(error.message ?: error.javaClass.simpleName) }
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
        installDraft.value = draft
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
        viewModelScope.launch {
            repository.previewInstall(installDraft.value)
                .onSuccess { preview -> installPreview.value = preview }
                .onFailure { error -> installPreview.value = errorPreview("Install preview", error) }
        }
    }

    fun installPayloadJson(): String = installDraft.value.toJsonPayload().toString()

    fun lifecyclePayloadJson(name: String, action: String): String = JSONObject()
        .put("name", name)
        .put("action", action)
        .toString()

    fun removePayloadJson(name: String, confirmation: String): String = JSONObject()
        .put("name", name)
        .put("confirmation", confirmation)
        .toString()

    fun previewLifecycle(name: String, action: String) {
        viewModelScope.launch {
            repository.previewLifecycle(name, action)
                .onSuccess { preview -> lifecyclePreview.value = preview }
                .onFailure { error -> lifecyclePreview.value = errorPreview("Lifecycle preview", error) }
        }
    }

    fun refreshSnapshots(name: String) {
        viewModelScope.launch {
            snapshotPane.value = snapshotPane.value.copy(targetName = name, refreshing = true, errorMessage = null)
            repository.refreshSnapshots(name)
                .onSuccess { rows -> snapshotPane.value = SnapshotPane(targetName = name, snapshots = rows) }
                .onFailure { error ->
                    snapshotPane.value = snapshotPane.value.copy(
                        targetName = name,
                        refreshing = false,
                        errorMessage = error.message ?: error.javaClass.simpleName,
                    )
                }
        }
    }

    fun previewSnapshotCreate(name: String) {
        viewModelScope.launch {
            repository.previewSnapshotCreate(name)
                .onSuccess { preview -> snapshotPane.value = snapshotPane.value.copy(targetName = name, preview = preview) }
                .onFailure { error -> snapshotPane.value = snapshotPane.value.copy(targetName = name, preview = errorPreview("Snapshot preview", error)) }
        }
    }

    fun previewSnapshotAction(name: String, snapshot: String, action: String) {
        viewModelScope.launch {
            repository.previewSnapshotAction(name, snapshot, action)
                .onSuccess { preview -> snapshotPane.value = snapshotPane.value.copy(targetName = name, preview = preview) }
                .onFailure { error -> snapshotPane.value = snapshotPane.value.copy(targetName = name, preview = errorPreview("Snapshot preview", error)) }
        }
    }

    fun snapshotCreatePayloadJson(name: String): String = JSONObject()
        .put("name", name)
        .put("snapshot", "snapshot-${System.currentTimeMillis() / 1000}")
        .toString()

    fun snapshotRestorePayloadJson(name: String, snapshot: String, confirmation: String): String = JSONObject()
        .put("name", name)
        .put("snapshot", snapshot)
        .put("confirmation", confirmation)
        .toString()

    fun snapshotExportPayloadJson(name: String, snapshot: String): String = JSONObject()
        .put("name", name)
        .put("snapshot", snapshot)
        .toString()

    fun refreshUsers(name: String) {
        viewModelScope.launch {
            usersPane.value = usersPane.value.copy(targetName = name, refreshing = true, errorMessage = null)
            repository.refreshUsers(name)
                .onSuccess { rows -> usersPane.value = UsersPane(targetName = name, users = rows) }
                .onFailure { error ->
                    usersPane.value = usersPane.value.copy(
                        targetName = name,
                        refreshing = false,
                        errorMessage = error.message ?: error.javaClass.simpleName,
                    )
                }
        }
    }

    fun previewUserAction(payloadJson: String) {
        viewModelScope.launch {
            val payload = JSONObject(payloadJson)
            repository.previewUserAction(payload)
                .onSuccess { preview -> usersPane.value = usersPane.value.copy(targetName = payload.optString("name"), preview = preview) }
                .onFailure { error -> usersPane.value = usersPane.value.copy(preview = errorPreview("User preview", error)) }
        }
    }

    fun userAddPayloadJson(name: String, username: String, shell: String, sudo: Boolean): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "add")
        .put("shell", shell)
        .put("sudo", sudo)
        .toString()

    fun userRemovePayloadJson(name: String, username: String, confirmation: String, deleteHome: Boolean): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "remove")
        .put("confirmation", confirmation)
        .put("deleteHome", deleteHome)
        .toString()

    fun userSyncPayloadJson(name: String, username: String): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "sync_uid_gid")
        .put("fixOwnership", true)
        .toString()

    fun userShellPayloadJson(name: String, username: String, shell: String): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "set_shell")
        .put("shell", shell)
        .toString()

    fun userSudoPayloadJson(name: String, username: String, enabled: Boolean): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "set_sudo")
        .put("enabled", enabled)
        .toString()

    fun userPasswordPayloadJson(name: String, username: String, password: String, confirmPassword: String, confirmation: String): String = JSONObject()
        .put("name", name)
        .put("username", username)
        .put("action", "set_password")
        .put("password", password)
        .put("confirmPassword", confirmPassword)
        .put("confirmation", confirmation)
        .toString()

    fun refreshServices(name: String) {
        viewModelScope.launch {
            servicesPane.value = servicesPane.value.copy(targetName = name, refreshing = true, errorMessage = null)
            repository.refreshServices(name)
                .onSuccess { rows -> servicesPane.value = ServicesPane(targetName = name, services = rows) }
                .onFailure { error ->
                    servicesPane.value = servicesPane.value.copy(
                        targetName = name,
                        refreshing = false,
                        errorMessage = error.message ?: error.javaClass.simpleName,
                    )
                }
        }
    }

    fun refreshServiceDetail(name: String, service: String) {
        viewModelScope.launch {
            servicesPane.value = servicesPane.value.copy(targetName = name, refreshing = true, errorMessage = null)
            repository.refreshServiceDetail(name, service)
                .onSuccess { row ->
                    val merged = servicesPane.value.services.map { existing -> if (existing.service == row.service) row else existing }
                    servicesPane.value = servicesPane.value.copy(
                        targetName = name,
                        services = if (merged.any { it.service == row.service }) merged else servicesPane.value.services + row,
                        selectedService = row,
                        refreshing = false,
                        errorMessage = null,
                    )
                }
                .onFailure { error ->
                    servicesPane.value = servicesPane.value.copy(
                        targetName = name,
                        refreshing = false,
                        errorMessage = error.message ?: error.javaClass.simpleName,
                    )
                }
        }
    }

    fun previewServiceAction(payloadJson: String) {
        viewModelScope.launch {
            val payload = JSONObject(payloadJson)
            repository.previewServiceAction(payload)
                .onSuccess { preview -> servicesPane.value = servicesPane.value.copy(targetName = payload.optString("name"), preview = preview) }
                .onFailure { error -> servicesPane.value = servicesPane.value.copy(preview = errorPreview("Service preview", error)) }
        }
    }

    fun servicePayloadJson(name: String, service: String, action: String): String = JSONObject()
        .put("name", name)
        .put("service", service)
        .put("action", action)
        .toString()

    override fun onCleared() {
        repository.close()
        super.onCleared()
    }

    private companion object {
        const val STOP_TIMEOUT_MS = 5_000L
    }
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
