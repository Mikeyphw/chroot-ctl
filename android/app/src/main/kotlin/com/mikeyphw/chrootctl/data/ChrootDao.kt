package com.mikeyphw.chrootctl.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

@Dao
interface ChrootDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(chroots: List<ChrootEntity>)

    @Query("UPDATE chroots SET stale = 1")
    suspend fun markAllStale()

    @Query("DELETE FROM chroots")
    suspend fun deleteAll()

    @Query("DELETE FROM chroots WHERE name NOT IN (:names)")
    suspend fun deleteMissing(names: List<String>)

    @Query("SELECT * FROM chroots ORDER BY name COLLATE NOCASE ASC")
    fun observeAll(): Flow<List<ChrootEntity>>

    @Query("SELECT * FROM chroots WHERE name = :name LIMIT 1")
    fun observeByName(name: String): Flow<ChrootEntity?>

    @Transaction
    suspend fun replaceSnapshot(chroots: List<ChrootEntity>) {
        if (chroots.isEmpty()) {
            deleteAll()
            return
        }
        upsertAll(chroots)
        deleteMissing(chroots.map { it.name })
    }
}

@Dao
interface CheckDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(checks: List<CheckResultEntity>)

    @Query("DELETE FROM checks WHERE scope = :scope")
    suspend fun deleteScope(scope: String)

    @Query("""
        SELECT * FROM checks
        ORDER BY CASE LOWER(severity)
            WHEN 'critical' THEN 5
            WHEN 'error' THEN 4
            WHEN 'high' THEN 4
            WHEN 'warning' THEN 3
            WHEN 'warn' THEN 3
            WHEN 'medium' THEN 2
            WHEN 'info' THEN 1
            WHEN 'low' THEN 1
            ELSE 0
        END DESC, title COLLATE NOCASE ASC
    """)
    fun observeAll(): Flow<List<CheckResultEntity>>

    @Query("""
        SELECT * FROM checks WHERE scope = :scope
        ORDER BY CASE LOWER(severity)
            WHEN 'critical' THEN 5
            WHEN 'error' THEN 4
            WHEN 'high' THEN 4
            WHEN 'warning' THEN 3
            WHEN 'warn' THEN 3
            WHEN 'medium' THEN 2
            WHEN 'info' THEN 1
            WHEN 'low' THEN 1
            ELSE 0
        END DESC, title COLLATE NOCASE ASC
    """)
    fun observeScope(scope: String): Flow<List<CheckResultEntity>>

    @Transaction
    suspend fun replaceScope(scope: String, checks: List<CheckResultEntity>) {
        deleteScope(scope)
        upsertAll(checks)
    }
}

@Dao
interface HomeSnapshotDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(snapshot: HomeSnapshotEntity)

    @Query("UPDATE home_snapshots SET stale = 1 WHERE id = :id")
    suspend fun markStale(id: String = HOME_SNAPSHOT_ID)

    @Query("SELECT * FROM home_snapshots WHERE id = :id LIMIT 1")
    fun observe(id: String = HOME_SNAPSHOT_ID): Flow<HomeSnapshotEntity?>
}
