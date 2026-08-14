package com.mikeyphw.chrootctl.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.focusGroup
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.FlowRowScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mikeyphw.chrootctl.ui.ChrootLayout
import com.mikeyphw.chrootctl.ui.ChrootPathFont
import com.mikeyphw.chrootctl.ui.ChrootSpacing
import com.mikeyphw.chrootctl.ui.sectionHeaderStacks
import com.mikeyphw.chrootctl.ui.ChrootStatusColors

enum class StatusTone {
    Neutral,
    Success,
    Warning,
    Danger,
    Accent,
}

@Composable
fun AppCard(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(ChrootSpacing.lg),
            verticalArrangement = Arrangement.spacedBy(ChrootSpacing.sm),
            content = content,
        )
    }
}

@Composable
fun StatusCard(
    title: String,
    body: String,
    modifier: Modifier = Modifier,
    footer: (@Composable () -> Unit)? = null,
) {
    AppCard(modifier) {
        Text(
            title,
            fontWeight = FontWeight.SemiBold,
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.semantics { heading() },
        )
        Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant)
        footer?.invoke()
    }
}

@Composable
fun MetricCard(label: String, value: String, detail: String, modifier: Modifier = Modifier) {
    AppCard(modifier.heightIn(min = 128.dp)) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelLarge)
        Text(value, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        Text(detail, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
fun EmptyState(title: String, body: String, modifier: Modifier = Modifier) {
    StatusCard(title = title, body = body, modifier = modifier)
}

@Composable
fun LoadingState(label: String, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier.fillMaxWidth().padding(ChrootSpacing.lg),
        horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.sm),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircularProgressIndicator(modifier = Modifier.sizeIn(maxWidth = 28.dp, maxHeight = 28.dp))
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun DashboardLoadingState(
    label: String,
    supportingText: String,
    metrics: List<MetricCardData>,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(ChrootSpacing.md)) {
        AppCard {
            Row(horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.sm), verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(modifier = Modifier.sizeIn(maxWidth = 28.dp, maxHeight = 28.dp))
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xs)) {
                    Text(label, fontWeight = FontWeight.SemiBold)
                    Text(
                        supportingText,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
        ResponsiveMetricCards(cards = metrics)
    }
}

@Composable
fun ProgressRow(label: String, detail: String, percent: Int?, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xs)) {
        Row(horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.xs), verticalAlignment = Alignment.CenterVertically) {
            Text(label, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            if (percent != null) Text(percent.toString() + "%", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Text(detail, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        if (percent != null) LinearProgressIndicator(progress = { percent / 100f }, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
fun PathText(path: String, modifier: Modifier = Modifier) {
    Text(path, modifier = modifier, fontFamily = ChrootPathFont, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
fun ChipRow(labels: List<String>, modifier: Modifier = Modifier) {
    FlowRow(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.xs),
        verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xs),
    ) {
        labels.forEach { label -> StatusPill(label = label, tone = StatusTone.Neutral) }
    }
}

@Composable
fun StatusPill(label: String, tone: StatusTone, modifier: Modifier = Modifier) {
    val foreground = toneColor(tone)
    val background = foreground.copy(alpha = 0.10f)
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = background),
        border = BorderStroke(1.dp, foreground.copy(alpha = 0.28f)),
        shape = MaterialTheme.shapes.extraLarge,
    ) {
        Text(
            text = label,
            color = foreground,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = ChrootSpacing.sm, vertical = ChrootSpacing.xs),
        )
    }
}

fun Modifier.releaseTouchTarget(): Modifier = this.sizeIn(
    minWidth = ChrootLayout.MinimumTouchTarget,
    minHeight = ChrootLayout.MinimumTouchTarget,
)

@Composable
fun ActionFlowRow(
    modifier: Modifier = Modifier,
    contentDescription: String? = null,
    content: @Composable FlowRowScope.() -> Unit,
) {
    val semanticModifier = if (contentDescription == null) {
        modifier
    } else {
        modifier.semantics { this.contentDescription = contentDescription }
    }
    FlowRow(
        modifier = semanticModifier
            .fillMaxWidth()
            .heightIn(min = ChrootLayout.MinimumTouchTarget)
            .focusGroup(),
        horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.xs),
        verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xs),
        content = content,
    )
}

@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    body: String? = null,
    action: (@Composable () -> Unit)? = null,
) {
    BoxWithConstraints(modifier.fillMaxWidth()) {
        val stackHeader = sectionHeaderStacks(maxWidth.value, LocalDensity.current.fontScale)
        if (stackHeader) {
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(ChrootSpacing.sm)) {
                Column(verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xxs)) {
                    Text(
                        title,
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.semantics { heading() },
                    )
                    body?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
                action?.invoke()
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.md),
                verticalAlignment = Alignment.Bottom,
            ) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xxs)) {
                    Text(
                        title,
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.semantics { heading() },
                    )
                    body?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
                action?.invoke()
            }
        }
    }
}

@Composable
fun PageHeader(
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
    statusLabel: String? = null,
    statusTone: StatusTone = StatusTone.Neutral,
) {
    BoxWithConstraints(modifier.fillMaxWidth()) {
        val stackHeader = sectionHeaderStacks(maxWidth.value, LocalDensity.current.fontScale)
        if (stackHeader) {
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(ChrootSpacing.sm)) {
                PageTitleBlock(title = title, subtitle = subtitle)
                statusLabel?.let { StatusPill(label = it, tone = statusTone) }
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.md),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                PageTitleBlock(title = title, subtitle = subtitle, modifier = Modifier.weight(1f))
                statusLabel?.let { StatusPill(label = it, tone = statusTone) }
            }
        }
    }
}

@Composable
private fun PageTitleBlock(
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xxs)) {
        Text(
            title,
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.semantics { heading() },
        )
        Text(subtitle, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun RefreshFailureBanner(
    title: String,
    body: String,
    technicalDetails: String,
    retryLabel: String,
    showDetailsLabel: String,
    hideDetailsLabel: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var detailsVisible by rememberSaveable(technicalDetails) { mutableStateOf(false) }
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.62f)),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.error.copy(alpha = 0.38f)),
    ) {
        Column(
            Modifier.fillMaxWidth().padding(ChrootSpacing.md),
            verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xs),
        ) {
            Text(title, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onErrorContainer)
            Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant)
            ActionFlowRow {
                Button(onClick = onRetry, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(retryLabel) }
                TextButton(
                    onClick = { detailsVisible = !detailsVisible },
                    modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
                ) {
                    Text(if (detailsVisible) hideDetailsLabel else showDetailsLabel)
                }
            }
            AnimatedVisibility(detailsVisible) {
                Column(verticalArrangement = Arrangement.spacedBy(ChrootSpacing.xs)) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    PathText(technicalDetails.take(1200), modifier = Modifier.fillMaxWidth())
                }
            }
        }
    }
}

@Composable
fun RecoverableErrorState(
    title: String,
    body: String,
    technicalDetails: String,
    attentionLabel: String,
    retryLabel: String,
    showDetailsLabel: String,
    hideDetailsLabel: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AppCard(modifier) {
        StatusPill(label = attentionLabel, tone = StatusTone.Danger)
        Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
        Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant)
        ActionFlowRow {
            Button(onClick = onRetry, modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget)) { Text(retryLabel) }
        }
        var detailsVisible by rememberSaveable(technicalDetails) { mutableStateOf(false) }
        OutlinedButton(
            onClick = { detailsVisible = !detailsVisible },
            modifier = Modifier.heightIn(min = ChrootLayout.MinimumTouchTarget),
        ) {
            Text(if (detailsVisible) hideDetailsLabel else showDetailsLabel)
        }
        AnimatedVisibility(detailsVisible) {
            PathText(technicalDetails.take(1200), modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
fun ResponsiveMetricCards(
    cards: List<MetricCardData>,
    modifier: Modifier = Modifier,
) {
    BoxWithConstraints(modifier.fillMaxWidth()) {
        if (maxWidth >= ChrootLayout.ExpandedMetricBreakpoint) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(ChrootSpacing.md)) {
                cards.forEach { item ->
                    MetricCard(item.label, item.value, item.detail, Modifier.weight(1f))
                }
            }
        } else {
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(ChrootSpacing.md)) {
                cards.forEach { item -> MetricCard(item.label, item.value, item.detail) }
            }
        }
    }
}

data class MetricCardData(val label: String, val value: String, val detail: String)

@Composable
private fun toneColor(tone: StatusTone): Color = when (tone) {
    StatusTone.Neutral -> MaterialTheme.colorScheme.onSurfaceVariant
    StatusTone.Success -> ChrootStatusColors.Success
    StatusTone.Warning -> ChrootStatusColors.Warning
    StatusTone.Danger -> ChrootStatusColors.Danger
    StatusTone.Accent -> MaterialTheme.colorScheme.primary
}
