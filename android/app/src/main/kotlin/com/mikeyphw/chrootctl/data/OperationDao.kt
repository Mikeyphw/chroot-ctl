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

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(operations: List<OperationEntity>)

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

    @Query("UPDATE operations SET stale = 1")
    suspend fun markAllStale()

    @Query("""
        UPDATE operations
        SET stale = 1,
            state = 'interrupted',
            errorCode = 'MISSING_BACKEND_OPERATION',
            errorMessage = 'The operation was active locally but no longer exists in the backend journal; refresh or retry after reviewing details.',
            progressText = 'Backend operation was not found during reconciliation',
            finishedAt = CASE WHEN finishedAt IS NULL THEN :now ELSE finishedAt END,
            reconciledAt = :now,
            missingInBackend = 1
        WHERE state IN ('queued', 'running', 'cancelling')
          AND operationId NOT IN (:authoritativeIds)
    """)
    suspend fun markActiveMissingFromBackend(authoritativeIds: List<String>, now: Long)

    @Query("""
        UPDATE operations
        SET stale = 1,
            state = 'interrupted',
            errorCode = 'MISSING_BACKEND_OPERATION',
            errorMessage = 'The operation was active locally but no longer exists in the backend journal; refresh or retry after reviewing details.',
            progressText = 'Backend operation was not found during reconciliation',
            finishedAt = CASE WHEN finishedAt IS NULL THEN :now ELSE finishedAt END,
            reconciledAt = :now,
            missingInBackend = 1
        WHERE state IN ('queued', 'running', 'cancelling')
    """)
    suspend fun markAllActiveMissingFromBackend(now: Long)

    @Query("""
        UPDATE operations
        SET detailRefreshAt = :now,
            reconciledAt = :now,
            missingInBackend = 0,
            stale = 0
        WHERE operationId = :operationId
    """)
    suspend fun markDetailRefreshed(operationId: String, now: Long)

    @Query("SELECT * FROM operations ORDER BY createdAt DESC LIMIT :limit")
    fun observeRecent(limit: Int = 50): Flow<List<OperationEntity>>

    @Query("SELECT * FROM operations WHERE operationId = :operationId LIMIT 1")
    fun observeById(operationId: String): Flow<OperationEntity?>

    @Query("SELECT * FROM operations WHERE operationId = :operationId LIMIT 1")
    suspend fun findById(operationId: String): OperationEntity?

    @Query("SELECT * FROM operations WHERE state IN ('queued', 'running', 'cancelling') ORDER BY createdAt ASC")
    suspend fun activeOperations(): List<OperationEntity>

    @Query("SELECT * FROM operation_events WHERE operationId = :operationId ORDER BY timestamp ASC, id ASC")
    fun observeEvents(operationId: String): Flow<List<OperationEventEntity>>

    @Transaction
    suspend fun persistOperation(operation: OperationEntity, events: List<OperationEventEntity> = emptyList(), prune: Boolean = true) {
        upsert(operation)
        events.forEach { event -> append(event) }
        if (prune) {
            pruneEvents(operation.operationId)
            pruneTerminalOperations()
            deleteOrphanEvents()
        }
    }

    @Transaction
    suspend fun replaceAuthoritativeSnapshot(operations: List<OperationEntity>, now: Long) {
        val authoritativeIds = operations.map { it.operationId }.filter { it.isNotBlank() && !it.startsWith("unknown-") }
        if (authoritativeIds.isEmpty()) {
            markAllActiveMissingFromBackend(now)
        } else {
            markActiveMissingFromBackend(authoritativeIds, now)
        }
        upsertAll(operations.map { it.copy(stale = false, missingInBackend = false, reconciledAt = now) })
        pruneTerminalOperations()
        deleteOrphanEvents()
    }
}
