from pathlib import Path


def test_overlay08_high_risk_features_contracts():
    root = Path(__file__).parents[1]
    users = (root / "src/chrootctl/chroot_users.py").read_text()
    sync = (root / "src/chrootctl/user_sync.py").read_text()
    units = (root / "src/chrootctl/runtime/units.py").read_text()
    catalog = (root / "src/chrootctl/catalog.py").read_text()
    clip = (root / "src/chrootctl/host_clipboard.py").read_text()
    session = (root / "src/chrootctl/runtime/session.py").read_text()
    setup = (root / "src/chrootctl/resources/tool-scripts/setup-clipboard.sh").read_text()
    sudo_script = (root / "src/chrootctl/resources/tool-scripts/setup-sudo-user.sh").read_text()
    sync_script = (root / "src/chrootctl/resources/tool-scripts/sync-uid.sh").read_text()
    assert 'def _validate_password_value' in users and 'visudo' in users and 'os.replace(temp_path, sudoers)' in users
    assert 'cannot sync UID' in sync and 'chown -R {host_uid}:{host_gid}' in sync and '_restore_shared_directory_modes' in sync
    assert 'chown -R /tmp' not in sync and 'chown -R /var/cache' not in sync
    assert '/run/chrootctl/services/' in units and 'process_identity_matches' in units and 'invalid boolean value' in units
    assert 'fcntl.flock' in units and 'LOCK_EX' in units and 'kill-pending' in units
    assert '_chroot_user_gid' in units and '0o710' in units and '0o550' in units
    assert 'catalog_state' in catalog and 'script_sha256' in catalog and 'risks' in catalog and 'rollback' in catalog
    assert 'SO_PEERCRED' in clip and '0o600' in clip and 'ThreadPoolExecutor' in clip and 'timeout=5.0' in clip
    assert 'preexec_fn=' not in clip and 'extra_groups=()' in clip
    assert 'verified clipboard daemon could not be terminated' in clip
    assert 'os.chown(runtime_dir' in clip and 'os.chown(token_path' in clip and '_atomic_private_text(pid_file' in clip
    assert '_ensure_existing_chroot_clipboard_tools' not in session
    assert '/usr/local/bin/chrootctl-xsel' in setup and '/usr/local/bin/xsel <<' not in setup
    assert 'visudo -cf "$tmp"' in sudo_script and 'mktemp "$sudoers_dir/' in sudo_script
    assert 'host-managed by chrootctl' in sync_script and 'groupmod -g' not in sync_script and 'usermod -u' not in sync_script
