package com.mikeyphw.chrootctl.data

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/**
 * Non-destructive Room migrations. Version 3 gives streamed operation events a
 * backend-stable identity so reconnect/replay can be handled as an idempotent upsert.
 */
val MIGRATION_2_3 = object : Migration(2, 3) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE operation_events ADD COLUMN eventKey TEXT NOT NULL DEFAULT ''")
        db.execSQL("UPDATE operation_events SET eventKey = operationId || ':legacy-db:' || id")
        db.execSQL(
            "CREATE UNIQUE INDEX IF NOT EXISTS index_operation_events_eventKey ON operation_events(eventKey)",
        )
    }
}

/** Version 4 removes the redundant secondary index on the chroots primary key. */
val MIGRATION_3_4 = object : Migration(3, 4) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("DROP INDEX IF EXISTS index_chroots_name")
    }
}
