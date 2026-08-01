package com.mikeyphw.chrootctl.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.mikeyphw.chrootctl.model.ChrootDetail
import com.mikeyphw.chrootctl.model.ChrootSummary
import com.mikeyphw.chrootctl.model.HomeSnapshot
import com.mikeyphw.chrootctl.model.Loadable
import com.mikeyphw.chrootctl.model.OperationDetail
import com.mikeyphw.chrootctl.model.OperationSummary
import com.mikeyphw.chrootctl.model.ToolCapabilityGroup
import com.mikeyphw.chrootctl.repository.BridgeRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

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
    val refreshState: RefreshState = RefreshState.Idle,
)

private data class PrimaryUiSlice(
    val home: Loadable<HomeSnapshot>,
    val chroots: List<ChrootSummary>,
    val operations: List<OperationSummary>,
    val selectedChrootName: String?,
    val chrootDetail: ChrootDetail,
)

private data class SecondaryUiSlice(
    val selectedOperationId: String?,
    val operationDetail: OperationDetail,
    val toolGroups: List<ToolCapabilityGroup>,
    val refreshState: RefreshState,
)

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class MainViewModel(private val repository: BridgeRepository) : ViewModel() {
    private val refreshState = MutableStateFlow<RefreshState>(RefreshState.Idle)
    private val toolGroups = MutableStateFlow<List<ToolCapabilityGroup>>(emptyList())
    private val selectedChrootName = MutableStateFlow<String?>(null)
    private val selectedOperationId = MutableStateFlow<String?>(null)
    private val chrootDetailRefresh = MutableStateFlow<RefreshState>(RefreshState.Idle)
    private val operationDetailRefresh = MutableStateFlow<RefreshState>(RefreshState.Idle)

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

    val uiState: StateFlow<MainUiState> = combine(
        primaryUiSlice,
        secondaryUiSlice,
    ) { primary, secondary ->
        MainUiState(
            home = primary.home,
            chroots = primary.chroots,
            operations = primary.operations,
            selectedChrootName = primary.selectedChrootName,
            chrootDetail = primary.chrootDetail,
            selectedOperationId = secondary.selectedOperationId,
            operationDetail = secondary.operationDetail,
            toolGroups = secondary.toolGroups,
            refreshState = secondary.refreshState,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(STOP_TIMEOUT_MS), MainUiState())

    init {
        refresh()
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
    }

    fun refreshSelectedChroot() {
        selectedChrootName.value?.let(::refreshChrootDetail)
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

    override fun onCleared() {
        repository.close()
        super.onCleared()
    }

    private companion object {
        const val STOP_TIMEOUT_MS = 5_000L
    }
}

class MainViewModelFactory(private val repository: BridgeRepository) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        require(modelClass.isAssignableFrom(MainViewModel::class.java))
        return MainViewModel(repository) as T
    }
}
