package com.mikeyphw.chrootctl.ui

enum class ToolsWorkspace(val key: String, val title: String, val summary: String) {
    Catalog("catalog", "Catalog", "Tools and add-ons"),
    Packages("packages", "Packages", "Inventory and compare"),
    Transfer("transfer", "Transfer", "Import, export, artifacts"),
    Runtime("runtime", "Runtime", "System, module, support"),
    Logs("logs", "Logs", "Bounded live timeline"),
    Repair("repair", "Repair", "Selective registry fixes"),
    Help("help", "Help", "FAQ and API reference"),
}

fun normalizeToolsWorkspace(key: String?): ToolsWorkspace =
    ToolsWorkspace.entries.firstOrNull { it.key == key } ?: ToolsWorkspace.Catalog
