package com.mikeyphw.chrootctl

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Build
import android.provider.OpenableColumns
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.lifecycleScope
import com.mikeyphw.chrootctl.operations.ChrootOperationService
import com.mikeyphw.chrootctl.operations.OperationNotificationController
import com.mikeyphw.chrootctl.ui.ChrootCtlApp
import com.mikeyphw.chrootctl.ui.MainViewModel
import com.mikeyphw.chrootctl.ui.MainViewModelFactory
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val notificationOperationId = mutableStateOf<String?>(null)
    private val notificationOpenNonce = mutableStateOf(0L)
    private val notificationsEnabled = mutableStateOf(false)

    private val viewModel: MainViewModel by viewModels {
        val app = application as ChrootCtlApplication
        MainViewModelFactory(app.container.bridgeRepository)
    }

    private val pickImportArchive = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let(::stageImportArchive)
    }

    private val createExportDocument = registerForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        uri?.let(::copyManagedArtifactToDocument)
    }

    private val requestNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        refreshNotificationState()
        val message = if (granted && notificationsEnabled.value) R.string.notifications_permission_granted else R.string.notifications_permission_denied
        Toast.makeText(this, getString(message), Toast.LENGTH_SHORT).show()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        notificationOperationId.value = intent?.getStringExtra(OperationNotificationController.EXTRA_OPEN_OPERATION_ID)
        if (!notificationOperationId.value.isNullOrBlank()) notificationOpenNonce.value += 1L
        refreshNotificationState()
        enableEdgeToEdge()
        setContent {
            ChrootCtlApp(
                viewModel = viewModel,
                onStartRefreshOperation = { ChrootOperationService.startRefresh(this) },
                onStartBridgeOperation = { operation, payloadJson ->
                    ChrootOperationService.startBridgeOperation(this, operation, payloadJson)
                },
                onPickImportArchive = {
                    pickImportArchive.launch(
                        arrayOf(
                            "application/octet-stream",
                            "application/gzip",
                            "application/x-tar",
                            "application/zstd",
                        ),
                    )
                },
                onCreateExportDocument = {
                    createExportDocument.launch(defaultExportFileName())
                },
                onRequestNotificationPermission = ::requestNotificationPermission,
                notificationsEnabled = notificationsEnabled.value,
                openOperationId = notificationOperationId.value,
                openOperationNonce = notificationOpenNonce.value,
            )
        }
    }

    override fun onResume() {
        super.onResume()
        refreshNotificationState()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        notificationOperationId.value = intent.getStringExtra(OperationNotificationController.EXTRA_OPEN_OPERATION_ID)
        if (!notificationOperationId.value.isNullOrBlank()) notificationOpenNonce.value += 1L
    }

    private fun refreshNotificationState() {
        val runtimeGranted = Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        notificationsEnabled.value = runtimeGranted && NotificationManagerCompat.from(this).areNotificationsEnabled()
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
            return
        }
        if (!NotificationManagerCompat.from(this).areNotificationsEnabled()) {
            startActivity(
                Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, packageName),
            )
            return
        }
        Toast.makeText(this, getString(R.string.notifications_permission_not_required), Toast.LENGTH_SHORT).show()
    }

    private fun stageImportArchive(uri: Uri) {
        val filename = displayName(uri)
        lifecycleScope.launch {
            val repository = (application as ChrootCtlApplication).container.bridgeRepository
            val descriptor = contentResolver.openFileDescriptor(uri, "r")
            if (descriptor == null) {
                Toast.makeText(this@MainActivity, getString(R.string.transfer_document_open_failed), Toast.LENGTH_SHORT).show()
                return@launch
            }
            descriptor.use { owned ->
                repository.stageImportArchive(filename, owned)
                    .onSuccess { path ->
                        viewModel.updateTransferImportArchive(path)
                        viewModel.inspectTransferImport()
                    }
                    .onFailure { error -> Toast.makeText(this@MainActivity, error.message ?: getString(R.string.transfer_document_open_failed), Toast.LENGTH_SHORT).show() }
            }
        }
    }

    private fun copyManagedArtifactToDocument(uri: Uri) {
        val path = viewModel.uiState.value.transferPane.exportArchive
            .takeIf(String::isNotBlank)
            ?: viewModel.uiState.value.transferPane.artifacts.firstOrNull()?.path.orEmpty()
        if (path.isBlank()) {
            Toast.makeText(this, getString(R.string.transfer_no_export_artifact), Toast.LENGTH_SHORT).show()
            return
        }
        lifecycleScope.launch {
            val repository = (application as ChrootCtlApplication).container.bridgeRepository
            val descriptor = contentResolver.openFileDescriptor(uri, "w")
            if (descriptor == null) {
                Toast.makeText(this@MainActivity, getString(R.string.transfer_document_open_failed), Toast.LENGTH_SHORT).show()
                return@launch
            }
            descriptor.use { owned ->
                repository.copyManagedArtifactToDocument(path, owned)
                    .onSuccess { Toast.makeText(this@MainActivity, getString(R.string.transfer_document_saved), Toast.LENGTH_SHORT).show() }
                    .onFailure { error -> Toast.makeText(this@MainActivity, error.message ?: getString(R.string.transfer_document_open_failed), Toast.LENGTH_SHORT).show() }
            }
        }
    }

    private fun displayName(uri: Uri): String {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index >= 0) return cursor.getString(index)
            }
        }
        return uri.lastPathSegment?.substringAfterLast('/')?.ifBlank { null } ?: getString(R.string.transfer_default_archive_name)
    }

    private fun defaultExportFileName(): String {
        val pane = viewModel.uiState.value.transferPane
        return pane.exportArchive.substringAfterLast('/').ifBlank {
            val target = pane.exportTargetName.ifBlank { getString(R.string.transfer_default_chroot_name) }
            "$target.tar.zst"
        }
    }
}
