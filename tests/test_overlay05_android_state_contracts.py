from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_room_refresh_is_transactional_reconciled_retained_and_replay_safe():
    container = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/AppContainer.kt")
    database = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/data/ChrootCtlDatabase.kt")
    migrations = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/data/DatabaseMigrations.kt")
    entities = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/data/OperationEntities.kt")
    chroots = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/data/ChrootDao.kt")
    operations = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/data/OperationDao.kt")
    repository = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt")
    assert "fallbackToDestructiveMigration" not in container
    assert ".addMigrations(MIGRATION_2_3)" in container
    assert "version = 3" in database
    assert "MIGRATION_2_3" in migrations and "ALTER TABLE operation_events ADD COLUMN eventKey" in migrations
    assert 'Index(value = ["eventKey"], unique = true)' in entities
    assert '@ColumnInfo(defaultValue = "\'\'") val eventKey: String' in entities
    assert "replaceSnapshot" in chroots and "deleteMissing" in chroots
    assert "onConflict = OnConflictStrategy.IGNORE" in operations
    assert "pruneEvents" in operations and "pruneTerminalOperations" in operations
    assert "@Transaction" in operations and "persistOperation" in operations
    assert "database.withTransaction" in repository
    assert "eventKey = if (sequence >= 0L)" in repository
    assert "stableTimestamp = timestampValue?.toString().orEmpty()" in repository
    assert "markAllStale" in repository and "markStale" in repository


def test_target_scoped_state_invalidates_racing_previews_and_requires_exact_contracts():
    view_model = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    models = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt")
    chroots_screen = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt")
    install_screen = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/install/InstallScreen.kt")
    tools_screen = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/tools/ToolsScreen.kt")
    assert "clearTargetScopedState" in view_model
    assert "if (!isCurrentTarget(name)) return@launch" in view_model
    assert "installPreviewRequestPayload" in view_model
    assert "lifecyclePreviewRequestKey" in view_model
    assert "snapshotPreviewRequestKey" in view_model
    assert "transferImportPreviewRequestPayload" in view_model
    assert "transferExportPreviewRequestPayload" in view_model
    assert "catalogRefreshRequestPayload" in view_model and "catalogPreviewRequestPayload" in view_model
    assert "clearUserPreview" in view_model and "userPreviewRequestPayload" in view_model
    assert "clearServicePreview" in view_model and "servicePreviewRequestPayload" in view_model
    assert "fun PreviewSummary?.approvesOperation(operation: String): Boolean" in models
    assert "actionOperation == operation" in models and "resourceRevision.isNotBlank()" in models
    assert 'lifecyclePreview.approvesOperation("chroots.start")' in chroots_screen
    assert 'lifecyclePreview.approvesOperation("chroots.restart")' in chroots_screen
    assert 'lifecyclePreview.approvesOperation("chroots.upgrade")' in chroots_screen
    assert 'preview.approvesOperation("chroots.remove.execute")' in chroots_screen
    assert 'preview.approvesOperation(operation)' in chroots_screen
    assert 'approvesOperation("install.run")' in install_screen
    assert 'approvesOperation("transfer.import")' in tools_screen
    assert 'approvesOperation("transfer.export")' in tools_screen
    assert 'approvesOperation("catalog.apply")' in tools_screen
    assert ".stale" in chroots_screen


def test_one_shot_previews_are_cleared_before_launch_and_late_results_cannot_restore_them():
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    view_model = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    for marker in (
        "clearInstallPreview()",
        "clearLifecyclePreview()",
        "clearSnapshotPreview()",
        "clearUserPreview()",
        "clearServicePreview()",
        "clearCatalogPreview()",
        "clearTransferImportPreview()",
        "clearTransferExportPreview()",
        "clearArtifactCleanupPreview()",
    ):
        assert marker in app
    assert "installPreviewRequestPayload == requestPayload" in view_model
    assert "lifecyclePreviewRequestKey == requestKey" in view_model
    assert "snapshotPreviewRequestKey == requestKey" in view_model
    assert "transferImportPreviewRequestPayload == requestPayload" in view_model
    assert "transferExportPreviewRequestPayload == requestPayload" in view_model
    assert "catalogPreviewRequestPayload == requestPayload" in view_model
    assert "artifactCleanupPreviewRequestPayload == requestPayload" in view_model
    assert 'artifactCleanupPreview.approvesOperation("artifacts.cleanup")' in app


def test_navigation_uses_single_route_registry_and_per_destination_saveable_state():
    shell = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AdaptiveNavigationShell.kt")
    policy = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ReleaseUxPolicy.kt")
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    assert "AppDestination.entries.toList()" in shell
    assert "AppDestination.entries.toList()" in policy
    assert "rememberSaveableStateHolder" in app
    assert "SaveableStateProvider(destination.name)" in app


def test_notification_ui_uses_real_permission_state_and_repeat_deep_links():
    activity = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/MainActivity.kt")
    home = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt")
    app = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/ChrootCtlApp.kt")
    assert "POST_NOTIFICATIONS" in activity
    assert "areNotificationsEnabled()" in activity
    assert "ACTION_APP_NOTIFICATION_SETTINGS" in activity
    assert "notificationOpenNonce" in activity
    assert "openOperationNonce" in app
    assert "LaunchedEffect(openOperationId, openOperationNonce)" in app
    assert "if (!notificationsEnabled)" in home


def test_backup_policy_and_static_metadata_controls_match_no_backup_intent():
    manifest = read("android/app/src/main/AndroidManifest.xml")
    backup = read("android/app/src/main/res/xml/backup_rules.xml")
    extraction = read("android/app/src/main/res/xml/data_extraction_rules.xml")
    cards = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/components/AppCards.kt")
    assert 'android:allowBackup="false"' in manifest
    for domain in ("root", "file", "database", "sharedpref", "external"):
        assert f'domain="{domain}"' in backup
        assert f'domain="{domain}"' in extraction
    assert "StatusPill" in cards
    assert "AssistChip" not in cards
