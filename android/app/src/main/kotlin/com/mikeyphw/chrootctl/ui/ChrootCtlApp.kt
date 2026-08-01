package com.mikeyphw.chrootctl.ui

import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mikeyphw.chrootctl.ui.activity.ActivityScreen
import com.mikeyphw.chrootctl.ui.chroots.ChrootsScreen
import com.mikeyphw.chrootctl.ui.home.HomeScreen
import com.mikeyphw.chrootctl.ui.tools.ToolsScreen

@Composable
fun ChrootCtlApp(viewModel: MainViewModel, onStartRefreshOperation: () -> Unit) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var destination by remember { mutableStateOf(AppDestination.Home) }

    ChrootCtlTheme {
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val wide = maxWidth >= 720.dp
            if (wide) {
                Row(Modifier.fillMaxSize()) {
                    NavigationRail {
                        AppDestination.entries.forEach { item ->
                            NavigationRailItem(
                                selected = item == destination,
                                onClick = { destination = item },
                                icon = { Text(stringResource(item.glyphRes)) },
                                label = { Text(stringResource(item.labelRes)) },
                            )
                        }
                    }
                    AppContent(
                        destination = destination,
                        state = uiState,
                        refresh = viewModel::refresh,
                        startRefreshOperation = onStartRefreshOperation,
                        openActivity = { destination = AppDestination.Activity },
                        selectChroot = viewModel::selectChroot,
                        refreshSelectedChroot = viewModel::refreshSelectedChroot,
                        selectOperation = viewModel::selectOperation,
                        refreshSelectedOperation = viewModel::refreshSelectedOperation,
                        modifier = Modifier.weight(1f),
                    )
                }
            } else {
                Scaffold(
                    bottomBar = {
                        NavigationBar {
                            AppDestination.entries.forEach { item ->
                                NavigationBarItem(
                                    selected = item == destination,
                                    onClick = { destination = item },
                                    icon = { Text(stringResource(item.glyphRes)) },
                                    label = { Text(stringResource(item.labelRes)) },
                                )
                            }
                        }
                    },
                ) { padding ->
                    AppContent(
                        destination = destination,
                        state = uiState,
                        refresh = viewModel::refresh,
                        startRefreshOperation = onStartRefreshOperation,
                        openActivity = { destination = AppDestination.Activity },
                        selectChroot = viewModel::selectChroot,
                        refreshSelectedChroot = viewModel::refreshSelectedChroot,
                        selectOperation = viewModel::selectOperation,
                        refreshSelectedOperation = viewModel::refreshSelectedOperation,
                        modifier = Modifier.padding(padding),
                    )
                }
            }
        }
    }
}

@Composable
private fun AppContent(
    destination: AppDestination,
    state: MainUiState,
    refresh: () -> Unit,
    startRefreshOperation: () -> Unit,
    openActivity: () -> Unit,
    selectChroot: (String) -> Unit,
    refreshSelectedChroot: () -> Unit,
    selectOperation: (String) -> Unit,
    refreshSelectedOperation: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
    ) {
        Text(stringResource(destination.labelRes), style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.height(16.dp))
        when (destination) {
            AppDestination.Home -> HomeScreen(
                state = state.home,
                refreshState = state.refreshState,
                onRefresh = refresh,
                onStartRefreshOperation = startRefreshOperation,
                onOpenActivity = openActivity,
            )
            AppDestination.Chroots -> ChrootsScreen(
                chroots = state.chroots,
                selectedName = state.selectedChrootName,
                detail = state.chrootDetail,
                onSelect = selectChroot,
                onRefreshDetail = refreshSelectedChroot,
            )
            AppDestination.Activity -> ActivityScreen(
                operations = state.operations,
                selectedOperationId = state.selectedOperationId,
                detail = state.operationDetail,
                onSelect = selectOperation,
                onRefreshDetail = refreshSelectedOperation,
            )
            AppDestination.Tools -> ToolsScreen(state.toolGroups)
        }
    }
}
