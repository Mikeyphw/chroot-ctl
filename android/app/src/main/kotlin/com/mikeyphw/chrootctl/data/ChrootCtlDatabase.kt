package com.mikeyphw.chrootctl.data

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [
        OperationEntity::class,
        OperationEventEntity::class,
        ChrootEntity::class,
        CheckResultEntity::class,
        HomeSnapshotEntity::class,
    ],
    version = 4,
    exportSchema = true,
)
abstract class ChrootCtlDatabase : RoomDatabase() {
    abstract fun operationDao(): OperationDao
    abstract fun chrootDao(): ChrootDao
    abstract fun checkDao(): CheckDao
    abstract fun homeSnapshotDao(): HomeSnapshotDao
}
