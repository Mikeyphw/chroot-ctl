package com.mikeyphw.chrootctl.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.mikeyphw.chrootctl.protocol.BridgeCapabilities
import com.mikeyphw.chrootctl.protocol.RootBridgeInfo
import com.mikeyphw.chrootctl.root.RootServiceClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface BridgeUiState {
    data object Loading : BridgeUiState
    data class Ready(val info: RootBridgeInfo, val capabilities: BridgeCapabilities) : BridgeUiState
    data class Blocked(val message: String) : BridgeUiState
}

class MainViewModel(private val rootClient: RootServiceClient) : ViewModel() {
    private val _bridgeState = MutableStateFlow<BridgeUiState>(BridgeUiState.Loading)
    val bridgeState: StateFlow<BridgeUiState> = _bridgeState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _bridgeState.value = BridgeUiState.Loading
            _bridgeState.value = runCatching {
                val info = RootBridgeInfo.fromJson(rootClient.serviceInfo())
                check(info.ok) { info.message }
                val capabilities = BridgeCapabilities.fromEnvelope(rootClient.capabilities())
                check(!capabilities.arbitraryShell) { "Unsafe arbitrary-shell capability was reported" }
                BridgeUiState.Ready(info, capabilities)
            }.getOrElse { error -> BridgeUiState.Blocked(error.message ?: error.javaClass.simpleName) }
        }
    }

    override fun onCleared() {
        rootClient.close()
        super.onCleared()
    }
}

class MainViewModelFactory(private val rootClient: RootServiceClient) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        require(modelClass.isAssignableFrom(MainViewModel::class.java))
        return MainViewModel(rootClient) as T
    }
}
