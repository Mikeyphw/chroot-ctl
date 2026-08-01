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

    @Query("SELECT * FROM chroots ORDER BY name COLLATE NOCASE ASC")
    fun observeAll(): Flow<List<ChrootEntity>>

    @Query("SELECT * FROM chroots WHERE name = :name LIMIT 1")
    fun observeByName(name: String): Flow<ChrootEntity?>

    @Transaction
    suspend fun replaceSnapshot(chroots: List<ChrootEntity>) {
        markAllStale()
        upsertAll(chroots)
    }
}

@Dao
interface CheckDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(checks: List<CheckResultEntity>)

    @Query("DELETE FROM checks WHERE scope = :scope")
    suspend fun deleteScope(scope: String)

    @Query("SELECT * FROM checks ORDER BY severity DESC, title COLLATE NOCASE ASC")
    fun observeAll(): Flow<List<CheckResultEntity>>

    @Query("SELECT * FROM checks WHERE scope = :scope ORDER BY severity DESC, title COLLATE NOCASE ASC")
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

    @Query("SELECT * FROM home_snapshots WHERE id = :id LIMIT 1")
    fun observe(id: String = HOME_SNAPSHOT_ID): Flow<HomeSnapshotEntity?>
}
