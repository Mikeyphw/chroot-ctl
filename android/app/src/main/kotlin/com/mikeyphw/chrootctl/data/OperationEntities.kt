package com.mikeyphw.chrootctl.data

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "operations",
    indices = [Index("state"), Index("targetName"), Index("createdAt")],
)
data class OperationEntity(
    @PrimaryKey val operationId: String,
    val kind: String,
    val title: String,
    val state: String,
    val targetName: String?,
    val phase: String?,
    val progressPercent: Int?,
    val progressText: String,
    val createdAt: Long,
    val startedAt: Long?,
    val finishedAt: Long?,
    val resultJson: String?,
    val errorCode: String?,
    val errorMessage: String?,
    val stale: Boolean,
)

@Entity(
    tableName = "operation_events",
    indices = [
        Index("operationId"),
        Index("timestamp"),
        Index(value = ["eventKey"], unique = true),
    ],
)
data class OperationEventEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(defaultValue = "''") val eventKey: String,
    val operationId: String,
    val type: String,
    val timestamp: Long,
    val payloadJson: String,
)
