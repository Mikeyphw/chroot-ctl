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


/**
 * Version 5 makes Android operation state replay-safe and reconciliation-safe.
 * It keeps backend request/retry metadata, explicit recovery eligibility, and
 * missing-backend tombstones so Room can distinguish stale cache from a live
 * operation that disappeared from the authoritative journal.
 */
val MIGRATION_4_5 = object : Migration(4, 5) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE operations ADD COLUMN parentOperationId TEXT")
        db.execSQL("ALTER TABLE operations ADD COLUMN requestJson TEXT")
        db.execSQL("ALTER TABLE operations ADD COLUMN retryJson TEXT")
        db.execSQL("ALTER TABLE operations ADD COLUMN warningsJson TEXT NOT NULL DEFAULT '[]'")
        db.execSQL("ALTER TABLE operations ADD COLUMN nextStepsJson TEXT NOT NULL DEFAULT '[]'")
        db.execSQL("ALTER TABLE operations ADD COLUMN retryable INTEGER NOT NULL DEFAULT 0")
        db.execSQL("ALTER TABLE operations ADD COLUMN retryWithFixes INTEGER NOT NULL DEFAULT 0")
        db.execSQL("ALTER TABLE operations ADD COLUMN recoveryActionsJson TEXT NOT NULL DEFAULT '[]'")
        db.execSQL("ALTER TABLE operations ADD COLUMN detailRefreshAt INTEGER")
        db.execSQL("ALTER TABLE operations ADD COLUMN reconciledAt INTEGER")
        db.execSQL("ALTER TABLE operations ADD COLUMN missingInBackend INTEGER NOT NULL DEFAULT 0")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_operations_parentOperationId ON operations(parentOperationId)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_operations_missingInBackend ON operations(missingInBackend)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_operations_reconciledAt ON operations(reconciledAt)")
    }
}
