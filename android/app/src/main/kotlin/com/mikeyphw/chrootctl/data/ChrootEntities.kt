package com.mikeyphw.chrootctl.data

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "chroots",
    indices = [Index("name"), Index("status"), Index("lastRefreshAt")],
)
data class ChrootEntity(
    @PrimaryKey val name: String,
    val distribution: String?,
    val release: String?,
    val architecture: String?,
    val path: String?,
    val status: String,
    val mountState: String?,
    val health: String?,
    val warningCount: Int,
    val rawJson: String,
    val lastRefreshAt: Long,
    val stale: Boolean,
)

@Entity(
    tableName = "checks",
    indices = [Index("scope"), Index("severity"), Index("lastRefreshAt")],
)
data class CheckResultEntity(
    @PrimaryKey val checkId: String,
    val scope: String,
    val title: String,
    val message: String,
    val severity: String,
    val rawJson: String,
    val lastRefreshAt: Long,
)

@Entity(
    tableName = "home_snapshots",
)
data class HomeSnapshotEntity(
    @PrimaryKey val id: String = HOME_SNAPSHOT_ID,
    val bridgeInfoJson: String,
    val capabilitiesJson: String,
    val dashboardJson: String,
    val chrootCount: Int,
    val operationCount: Int,
    val warningCount: Int,
    val lastRefreshAt: Long,
    val stale: Boolean,
)

const val HOME_SNAPSHOT_ID = "home"
