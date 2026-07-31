package com.mikeyphw.chrootctl.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

private enum class Destination(val label: String, val glyph: String) {
    Home("Home", "⌂"),
    Chroots("Chroots", "▣"),
    Activity("Activity", "↻"),
    Tools("Tools", "⌘"),
}

@Composable
fun ChrootCtlApp(viewModel: MainViewModel) {
    val bridgeState by viewModel.bridgeState.collectAsStateWithLifecycle()
    var destination by remember { mutableStateOf(Destination.Home) }

    ChrootCtlTheme {
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val wide = maxWidth >= 720.dp
            if (wide) {
                Row(Modifier.fillMaxSize()) {
                    NavigationRail {
                        Destination.entries.forEach { item ->
                            NavigationRailItem(
                                selected = item == destination,
                                onClick = { destination = item },
                                icon = { Text(item.glyph) },
                                label = { Text(item.label) },
                            )
                        }
                    }
                    AppContent(destination, bridgeState, viewModel::refresh, Modifier.weight(1f))
                }
            } else {
                Scaffold(
                    bottomBar = {
                        NavigationBar {
                            Destination.entries.forEach { item ->
                                NavigationBarItem(
                                    selected = item == destination,
                                    onClick = { destination = item },
                                    icon = { Text(item.glyph) },
                                    label = { Text(item.label) },
                                )
                            }
                        }
                    },
                ) { padding ->
                    AppContent(destination, bridgeState, viewModel::refresh, Modifier.padding(padding))
                }
            }
        }
    }
}

@Composable
private fun AppContent(
    destination: Destination,
    bridgeState: BridgeUiState,
    refresh: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(destination.label, style = MaterialTheme.typography.headlineSmall)
        when (destination) {
            Destination.Home -> HomeScreen(bridgeState, refresh)
            Destination.Chroots -> FoundationScreen("Registered chroots will appear here after the read-only repository phase.")
            Destination.Activity -> FoundationScreen("Persistent operation records and NDJSON timelines are ready for the Activity UI.")
            Destination.Tools -> FoundationScreen("Diagnostics, recovery, transfer and module tools will be added through the same fixed bridge.")
        }
    }
}

@Composable
private fun HomeScreen(state: BridgeUiState, refresh: () -> Unit) {
    when (state) {
        BridgeUiState.Loading -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator()
            Spacer(Modifier.height(12.dp))
            Text("Checking root and chrootctl runtime")
        }
        is BridgeUiState.Blocked -> StatusCard(
            title = "Backend unavailable",
            body = state.message,
            footer = { Button(onClick = refresh) { Text("Retry") } },
        )
        is BridgeUiState.Ready -> {
            StatusCard(
                title = "Root bridge ready",
                body = "UID ${state.info.uid} · ${state.info.backend} · protocol ${state.capabilities.protocolVersion}",
            )
            StatusCard(
                title = "Backend ${state.capabilities.backendVersion}",
                body = "${state.capabilities.operations.size} allowlisted capabilities. Arbitrary shell: disabled.",
                footer = { Button(onClick = refresh) { Text("Refresh") } },
            )
        }
    }
}

@Composable
private fun FoundationScreen(message: String) {
    StatusCard(title = "Foundation phase", body = message)
}

@Composable
private fun StatusCard(
    title: String,
    body: String,
    footer: (@Composable () -> Unit)? = null,
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(title, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.titleMedium)
            Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant)
            footer?.invoke()
        }
    }
}
