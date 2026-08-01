package com.mikeyphw.chrootctl.ui.tools

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.R
import com.mikeyphw.chrootctl.model.ToolCapabilityGroup
import com.mikeyphw.chrootctl.ui.components.ChipRow
import com.mikeyphw.chrootctl.ui.components.EmptyState

@Composable
fun ToolsScreen(groups: List<ToolCapabilityGroup>, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (groups.isEmpty()) {
            EmptyState(
                title = stringResource(R.string.tools_empty_title),
                body = stringResource(R.string.tools_empty_body),
            )
        } else {
            groups.forEach { group -> ToolGroupCard(group) }
        }
    }
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
