from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_archive_import_preflights_paths_links_and_special_members_before_extract():
    safety = read("src/chrootctl/services/storage_safety.py")
    archives = read("src/chrootctl/services/chroot_archives.py")
    assert "safe_basename" in archives
    assert "preflight_tar" in archives
    assert "extract_preflighted_tar" in archives
    assert "member.isdev() or member.isfifo()" in safety
    assert "unsafe archive link target" in safety
    assert "decompressed archive exceeds safe staging capacity" in safety
    assert "require_contained" in safety


def test_import_restore_remove_and_rename_use_staging_unmount_commit_and_recovery_boundaries():
    archives = read("src/chrootctl/services/chroot_archives.py")
    snapshots = read("src/chrootctl/services/snapshots.py")
    controller = read("src/chrootctl/controller.py")
    safety = read("src/chrootctl/services/storage_safety.py")
    context = read("src/chrootctl/services/context.py")
    assert ".chrootctl-stage-" in archives and ".chrootctl-backup-" in archives
    assert ".chrootctl-remove-" in archives
    assert "require_successful_unmount" in archives
    assert "best_effort_mutation_state" in archives and "best_effort_mutation_state" in snapshots
    assert 'imported_metadata["_chrootctl_mutation_id"] = mutation_id' in archives
    assert '"_chrootctl_mutation_id": mutation_id' in snapshots
    assert "os.replace(stage, target)" in snapshots
    assert "_require_restart_unmounted" in controller
    assert "restart_prepare" in controller
    assert "def recover_pending_fs_mutations" in safety
    assert "pending_fs_mutations" in safety
    assert "_quarantine_recovery_path" in safety
    assert "recover_pending_fs_mutations(container)" in context


def test_android_lifecycle_is_noninteractive_but_cli_retains_interactive_path_and_preflights_registry():
    bridge = read("src/chrootctl/bridge/registry.py")
    session = read("src/chrootctl/runtime/session.py")
    chroots = read("src/chrootctl/services/chroots.py")
    assert "interactive=False" in bridge
    assert "restart_interactive" in session
    assert "def _require_runnable_record" in chroots
    assert "registered chroot path" in chroots
    assert "not installed" in chroots


def test_registry_has_fk_wal_busy_timeout_write_lock_recovery_journal_artifacts_and_safe_metadata():
    registry = read("src/chrootctl/registry.py")
    assert "ON UPDATE CASCADE ON DELETE CASCADE" in registry
    assert "PRAGMA foreign_keys = ON" in registry
    assert "PRAGMA journal_mode = WAL" in registry
    assert "PRAGMA busy_timeout = 5000" in registry
    assert "threading.RLock()" in registry
    assert "CREATE TABLE IF NOT EXISTS fs_mutations" in registry
    assert "CREATE TABLE IF NOT EXISTS artifacts" in registry
    assert "def pending_fs_mutations" in registry
    assert "def register_artifact" in registry
    assert "def _safe_json_dict" in registry
    assert '"_corrupt": True' in registry
    assert "SELECT name, distro, path, arch, release_name, version, phase, installed, metadata_json" in registry
    assert "def find_by_path" in registry
    assert "orphan snapshot row(s)" in registry
    assert 'str(row[5]).upper() == "CASCADE"' in registry
    assert 'str(row[6]).upper() == "CASCADE"' in registry


def test_archive_processes_stay_under_operation_runner_and_secrets_stay_off_argv():
    archives = read("src/chrootctl/services/chroot_archives.py")
    safety = read("src/chrootctl/services/storage_safety.py")
    bridge = read("src/chrootctl/bridge/registry.py")
    repository = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt")
    view_model = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt")
    assert "subprocess.Popen" not in archives and "subprocess.run" not in archives
    assert "subprocess.Popen" not in safety and "subprocess.run" not in safety
    assert "runner.run(" in archives and "runner.run(" in safety
    assert '"-pass",\n            "stdin"' in archives
    assert "pass:{password}" not in archives
    assert 'password=_optional_text(payload, "password")' in bridge
    assert 'payload.put("password", password)' in repository
    assert 'payload.put("password", it)' in view_model


def test_package_inventory_uses_registry_path_and_managed_artifacts_have_identity_policy():
    chroots = read("src/chrootctl/services/chroots.py")
    bridge = read("src/chrootctl/bridge/registry.py")
    transfer = read("src/chrootctl/services/transfer.py")
    ui_models = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/model/UiModels.kt")
    assert "_registered_rootfs" in chroots
    assert "registered chroot path" in bridge
    assert "artifactId" in transfer and "expiresAt" in transfer and "retentionPolicy" in transfer
    assert "artifact_id" in transfer and "delete_temp" in transfer
    assert "artifactId" in ui_models and "expiresAt" in ui_models


def test_android_descriptor_staging_is_unique_partial_then_atomically_published():
    service = read("android/app/src/main/kotlin/com/mikeyphw/chrootctl/root/ChrootRootService.kt")
    assert "UUID.randomUUID()" in service
    assert 'val partial = directory.resolve(".$stagingId-$filename.partial")' in service
    assert "destination.fd.sync()" in service
    assert "partial.renameTo(target)" in service
