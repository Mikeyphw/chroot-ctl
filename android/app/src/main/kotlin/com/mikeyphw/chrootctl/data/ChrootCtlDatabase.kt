package com.mikeyphw.chrootctl.data

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [OperationEntity::class, OperationEventEntity::class],
    version = 1,
    exportSchema = true,
)
abstract class ChrootCtlDatabase : RoomDatabase() {
    abstract fun operationDao(): OperationDao
}
