package com.mikeyphw.chrootctl.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

@Dao
interface OperationDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(operation: OperationEntity)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun append(event: OperationEventEntity)

    @Query("""
        DELETE FROM operation_events
        WHERE operationId = :operationId AND id NOT IN (
            SELECT id FROM operation_events WHERE operationId = :operationId ORDER BY timestamp DESC, id DESC LIMIT :keep
        )
    """)
    suspend fun pruneEvents(operationId: String, keep: Int = 500)

    @Query("DELETE FROM operation_events WHERE operationId NOT IN (SELECT operationId FROM operations)")
    suspend fun deleteOrphanEvents()

    @Query("""
        DELETE FROM operations WHERE operationId NOT IN (
            SELECT operationId FROM operations ORDER BY createdAt DESC LIMIT :keep
        ) AND state NOT IN ('queued', 'running', 'cancelling')
    """)
    suspend fun pruneTerminalOperations(keep: Int = 250)

    @Query("SELECT * FROM operations ORDER BY createdAt DESC LIMIT :limit")
    fun observeRecent(limit: Int = 50): Flow<List<OperationEntity>>

    @Query("SELECT * FROM operations WHERE operationId = :operationId LIMIT 1")
    fun observeById(operationId: String): Flow<OperationEntity?>

    @Query("SELECT * FROM operations WHERE operationId = :operationId LIMIT 1")
    suspend fun findById(operationId: String): OperationEntity?

    @Query("SELECT * FROM operation_events WHERE operationId = :operationId ORDER BY timestamp ASC, id ASC")
    fun observeEvents(operationId: String): Flow<List<OperationEventEntity>>

    @Transaction
    suspend fun persistOperation(operation: OperationEntity, events: List<OperationEventEntity> = emptyList()) {
        upsert(operation)
        events.forEach { event -> append(event) }
        pruneEvents(operation.operationId)
        pruneTerminalOperations()
        deleteOrphanEvents()
    }
}
