package com.mikeyphw.chrootctl

import android.content.Context
import androidx.room.Room
import com.mikeyphw.chrootctl.data.ChrootCtlDatabase
import com.mikeyphw.chrootctl.data.MIGRATION_2_3
import com.mikeyphw.chrootctl.data.MIGRATION_3_4
import com.mikeyphw.chrootctl.data.MIGRATION_4_5
import com.mikeyphw.chrootctl.repository.BridgeRepository
import com.mikeyphw.chrootctl.root.RootServiceClient

class AppContainer(context: Context) {
    val database: ChrootCtlDatabase = Room.databaseBuilder(
        context,
        ChrootCtlDatabase::class.java,
        "chrootctl-android.db",
    ).addMigrations(MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5).build()

    val rootServiceClient = RootServiceClient(context.applicationContext)
    val bridgeRepository = BridgeRepository(rootServiceClient, database)
}
