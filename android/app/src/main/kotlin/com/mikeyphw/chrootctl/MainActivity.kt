package com.mikeyphw.chrootctl

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import com.mikeyphw.chrootctl.ui.ChrootCtlApp
import com.mikeyphw.chrootctl.ui.MainViewModel
import com.mikeyphw.chrootctl.ui.MainViewModelFactory

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels {
        val app = application as ChrootCtlApplication
        MainViewModelFactory(app.container.rootServiceClient)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { ChrootCtlApp(viewModel) }
    }
}
