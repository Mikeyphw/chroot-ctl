package com.mikeyphw.chrootctl.ui.components

import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.ui.AppDestination
import com.mikeyphw.chrootctl.ui.ChrootLayout
import com.mikeyphw.chrootctl.ui.ChrootSpacing
import com.mikeyphw.chrootctl.ui.PrimaryNavigationType
import com.mikeyphw.chrootctl.ui.primaryNavigationType
import com.mikeyphw.chrootctl.ui.compactNavigationShowsVisualLabels

@Composable
fun AdaptiveNavigationShell(
    destination: AppDestination,
    onDestinationSelected: (AppDestination) -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable (Modifier) -> Unit,
) {
    BoxWithConstraints(modifier.fillMaxSize()) {
        val showCompactVisualLabels = compactNavigationShowsVisualLabels(LocalDensity.current.fontScale)
        if (primaryNavigationType(maxWidth.value) == PrimaryNavigationType.Rail) {
            Row(Modifier.fillMaxSize().safeDrawingPadding()) {
                val appName = stringResource(R.string.app_name)
                NavigationRail(
                    modifier = Modifier
                        .width(ChrootLayout.NavigationRailWidth)
                        .fillMaxHeight(),
                    header = {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Card(
                                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primary),
                                shape = MaterialTheme.shapes.large,
                            ) {
                                Text(
                                    text = stringResource(R.string.brand_mark),
                                    color = MaterialTheme.colorScheme.onPrimary,
                                    fontWeight = FontWeight.Black,
                                    style = MaterialTheme.typography.titleLarge,
                                    modifier = Modifier
                                        .semantics {
                                            contentDescription = appName
                                            heading()
                                        }
                                        .padding(ChrootSpacing.md),
                                )
                            }
                            Spacer(Modifier.height(ChrootSpacing.sm))
                        }
                    },
                ) {
                    primaryDestinations.forEach { item ->
                        val label = stringResource(item.labelRes)
                        NavigationRailItem(
                            selected = item == destination,
                            onClick = { onDestinationSelected(item) },
                            modifier = Modifier
                                .heightIn(min = ChrootLayout.MinimumTouchTarget)
                                .semantics { contentDescription = label },
                            icon = { Text(stringResource(item.glyphRes)) },
                            label = { Text(label) },
                        )
                    }
                }
                content(Modifier.weight(1f))
            }
        } else {
            Scaffold(
                bottomBar = {
                    NavigationBar {
                        primaryDestinations.forEach { item ->
                            val label = stringResource(item.labelRes)
                            NavigationBarItem(
                                selected = item == destination,
                                onClick = { onDestinationSelected(item) },
                                modifier = Modifier
                                    .heightIn(min = ChrootLayout.MinimumTouchTarget)
                                    .semantics { contentDescription = label },
                                icon = { Text(stringResource(item.glyphRes)) },
                                label = if (showCompactVisualLabels) ({ Text(label) }) else null,
                                alwaysShowLabel = showCompactVisualLabels,
                            )
                        }
                    }
                },
            ) { paddingValues ->
                content(Modifier.padding(paddingValues))
            }
        }
    }
}

private val primaryDestinations: List<AppDestination> = AppDestination.entries.toList()
