package com.mikeyphw.chrootctl

import android.content.Context
import androidx.room.Room
import com.mikeyphw.chrootctl.data.ChrootCtlDatabase
import com.mikeyphw.chrootctl.repository.BridgeRepository
import com.mikeyphw.chrootctl.root.RootServiceClient

class AppContainer(context: Context) {
    val database: ChrootCtlDatabase = Room.databaseBuilder(
        context,
        ChrootCtlDatabase::class.java,
        "chrootctl-android.db",
    ).fallbackToDestructiveMigration().build()

    val rootServiceClient = RootServiceClient(context.applicationContext)
    val bridgeRepository = BridgeRepository(rootServiceClient, database)
}
