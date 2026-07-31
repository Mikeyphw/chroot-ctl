package com.mikeyphw.chrootctl.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface OperationDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(operation: OperationEntity)

    @Insert
    suspend fun append(event: OperationEventEntity)

    @Query("SELECT * FROM operations ORDER BY createdAt DESC LIMIT :limit")
    fun observeRecent(limit: Int = 50): Flow<List<OperationEntity>>

    @Query("SELECT * FROM operation_events WHERE operationId = :operationId ORDER BY timestamp ASC, id ASC")
    fun observeEvents(operationId: String): Flow<List<OperationEventEntity>>
}
