from __future__ import annotations

import io
import sys
from pathlib import Path

from chrootctl.cli import main
from chrootctl.completion import (
    completion_chroot_details,
    completion_chroot_names,
    completion_chroot_preview,
    generate_zsh_completion,
)
from chrootctl.registry import ChrootRegistry


def sample_records() -> list[dict[str, object]]:
    return [
        {
            "name": "work",
            "distro": "ubuntu",
            "phase": "desktop",
            "version": "24.04",
            "release_name": "noble",
            "installed": 1,
            "path": "/data/local/chroot/work",
            "metadata": {"desktop": "xfce4"},
        },
        {
            "name": "lab",
            "distro": "arch",
            "phase": "bootstrap",
            "version": "latest",
            "release_name": "rolling",
            "installed": 0,
            "path": "/data/local/chroot/lab",
            "metadata": {},
        },
    ]


def test_generate_zsh_completion_contains_expected_sections() -> None:
    script = generate_zsh_completion()

    assert "#compdef chrootctl" in script
    assert "compdef _chrootctl chrootctl" in script
    assert "__complete chroots" in script
    assert "fzf" in script
    assert "bat --style=plain" in script
    assert "lsd --color=always" in script
    assert "completion)" in script
    assert "chroots)" in script
    assert "users)" in script
    assert "users_subcommands = \"list show add remove password shell sudo show-id sync-id\"" not in script
    assert "password)" in script
    assert "__complete users" in script
    assert "__complete tools" in script
    assert "__complete addons" in script


def test_completion_helpers_render_registry_data() -> None:
    records = sample_records()

    assert completion_chroot_names(records) == "lab\nwork"
    assert "work\tubuntu\tdesktop" in completion_chroot_details(records)
    preview = completion_chroot_preview(records[0])
    assert "name: work" in preview
    assert "metadata.desktop: xfce4" in preview


def test_completion_command_smoke(monkeypatch) -> None:
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "argv", ["chrootctl", "completion", "zsh"])
    monkeypatch.setattr(sys, "stdout", stdout)

    main()

    output = stdout.getvalue()
    assert output
    assert "#compdef chrootctl" in output
    assert "[red]" not in output


def test_hidden_completion_uses_registry(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "share" / "chrootctl" / "chroots.sqlite3"
    registry = ChrootRegistry(db_path)
    registry.upsert(name="work", distro="ubuntu", path="/data/local/chroot/work", phase="desktop", installed=True)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        f'{{"database_path": "{db_path}"}}',
        encoding="utf-8",
    )
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "argv", ["chrootctl", "--config", str(config_path), "__complete", "chroots"])
    monkeypatch.setattr(sys, "stdout", stdout)

    main()

    assert stdout.getvalue().strip() == "work"


def test_hidden_completion_lists_users_and_catalog_items(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "share" / "chrootctl" / "chroots.sqlite3"
    chroot_root = tmp_path / "chroots"
    passwd_path = chroot_root / "work" / "etc" / "passwd"
    passwd_path.parent.mkdir(parents=True)
    passwd_path.write_text("mike:x:2000:2000::/home/mike:/bin/bash\n", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        f'{{"database_path": "{db_path}", "chroot_root": "{chroot_root}"}}',
        encoding="utf-8",
    )

    stdout = io.StringIO()
    monkeypatch.setattr(sys, "argv", ["chrootctl", "--config", str(config_path), "--name", "work", "__complete", "users"])
    monkeypatch.setattr(sys, "stdout", stdout)
    main()
    assert stdout.getvalue().strip() == "mike"

    stdout = io.StringIO()
    monkeypatch.setattr(sys, "argv", ["chrootctl", "--config", str(config_path), "__complete", "addons", "ubuntu"])
    monkeypatch.setattr(sys, "stdout", stdout)
    main()
    assert "nala" in stdout.getvalue().splitlines()
