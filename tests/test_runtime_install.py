from __future__ import annotations

import argparse
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from chrootctl.config import ChrootConfig
from chrootctl.models import CatalogApplyResult, InstallFinalizeResult
from chrootctl.registry import ChrootRegistry
from chrootctl.runtime import install as install_runtime


class Runner:
    dry_run = True


def build_context(tmp_path: Path):
    config = ChrootConfig(
        chroot_root=tmp_path / "chroots",
        database_path=tmp_path / "registry.sqlite3",
        log_file=tmp_path / "chrootctl.log",
        distro_name="ubuntu",
    )
    registry = ChrootRegistry(config.database_path)
    args = argparse.Namespace(
        distro="ubuntu",
        username="mike",
        name=None,
        wizard=False,
        list_versions=False,
        tools=[],
        addons=[],
        select_tools=False,
        select_addons=False,
        phase=None,
        desktop=None,
        version=None,
        release=None,
        force_phase=False,
        resume=False,
        repair=False,
        profile=None,
        command="install",
        json=False,
        non_interactive=False,
    )
    return SimpleNamespace(
        args=args,
        config=config,
        registry=registry,
        runner=Runner(),
        logger=logging.getLogger("test"),
        chroot_users=SimpleNamespace(user_rows=lambda: []),
    )


def test_handle_install_rejects_tool_and_addon_apply_before_finalize(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path)
    context.args.tools = ["tool-a"]
    context.args.addons = ["addon-a"]

    class Installer:
        def list_versions(self):
            return []

        def install(self, **kwargs):
            return [InstallFinalizeResult(installed=False, uid_sync=False, snapshot="")]

    monkeypatch.setattr(install_runtime, "build_installer", lambda *args, **kwargs: Installer())
    monkeypatch.setattr(install_runtime, "progress_call", lambda description, fn: fn())
    monkeypatch.setattr(install_runtime, "install_selection_names", lambda **kwargs: kwargs["explicit_names"])

    with pytest.raises(RuntimeError, match="tools and addons can only be applied after finalize completes"):
        install_runtime.handle_install(context)


def test_handle_install_applies_selected_tools_and_addons_after_finalize(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path)
    context.args.tools = ["tool-a"]
    context.args.addons = ["addon-a"]
    rendered: dict[str, object] = {}
    panels: list[tuple[str, object]] = []
    applied_calls: list[tuple[str, tuple[str, ...]]] = []

    class Installer:
        def list_versions(self):
            return []

        def install(self, **kwargs):
            context.registry.upsert(
                name="ubuntu",
                distro="ubuntu",
                path=str(context.config.chroot_base),
                phase="finalize",
                installed=True,
            )
            return [InstallFinalizeResult(installed=True, uid_sync=True, snapshot="snap-1")]

    def fake_apply_catalog_entries(*, catalog, names, config, runner, registry, logger):
        applied_calls.append((catalog.kind, tuple(names)))
        return [
            CatalogApplyResult(
                kind=catalog.kind,
                name=names[0],
                distro="ubuntu",
                categories=("system",),
                applied=True,
            )
        ]

    monkeypatch.setattr(install_runtime, "build_installer", lambda *args, **kwargs: Installer())
    monkeypatch.setattr(install_runtime, "apply_catalog_entries", fake_apply_catalog_entries)
    monkeypatch.setattr(install_runtime, "progress_call", lambda description, fn: fn())
    monkeypatch.setattr(install_runtime, "install_selection_names", lambda **kwargs: kwargs["explicit_names"])
    monkeypatch.setattr(install_runtime, "emit_table", lambda context, title, rows: rendered.update({"title": title, "rows": rows}))
    monkeypatch.setattr(install_runtime, "emit_panel", lambda context, title, data: panels.append((title, data)))

    install_runtime.handle_install(context)

    assert applied_calls == [("tool", ("tool-a",)), ("addon", ("addon-a",))]
    assert rendered["title"] == "Install Results"
    rows = rendered["rows"]
    assert [type(row).__name__ for row in rows] == [
        "InstallFinalizeResult",
        "CatalogApplyResult",
        "CatalogApplyResult",
    ]
    assert panels == [
        (
            "Next Steps",
            {
                "start": "chrootctl start",
                "sync_id": "chrootctl users sync-id mike",
                "tools_apply": "chrootctl tools apply <tool>",
                "addons_apply": "chrootctl addons apply <addon>",
                "logs": "chrootctl logs --all",
            },
        )
    ]


def test_handle_install_does_not_auto_apply_clipboard_tools_after_finalize(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path)
    rendered: dict[str, object] = {}
    applied_calls: list[tuple[str, tuple[str, ...]]] = []

    class Installer:
        def list_versions(self):
            return []

        def install(self, **kwargs):
            context.registry.upsert(
                name="ubuntu",
                distro="ubuntu",
                path=str(context.config.chroot_base),
                phase="finalize",
                installed=True,
            )
            return [InstallFinalizeResult(installed=True, uid_sync=True, snapshot="snap-1")]

    def fake_apply_catalog_entries(*, catalog, names, config, runner, registry, logger):
        applied_calls.append((catalog.kind, tuple(names)))
        return [
            CatalogApplyResult(
                kind=catalog.kind,
                name=names[0],
                distro="ubuntu",
                categories=("desktop",),
                applied=True,
            )
        ]

    monkeypatch.setattr(install_runtime, "build_installer", lambda *args, **kwargs: Installer())
    monkeypatch.setattr(install_runtime, "apply_catalog_entries", fake_apply_catalog_entries)
    monkeypatch.setattr(install_runtime, "progress_call", lambda description, fn: fn())
    monkeypatch.setattr(install_runtime, "install_selection_names", lambda **kwargs: kwargs["explicit_names"])
    monkeypatch.setattr(install_runtime, "emit_table", lambda context, title, rows: rendered.update({"title": title, "rows": rows}))
    monkeypatch.setattr(install_runtime, "emit_panel", lambda context, title, data: None)

    install_runtime.handle_install(context)

    assert applied_calls == []
    assert rendered["title"] == "Install Results"
    rows = rendered["rows"]
    assert [type(row).__name__ for row in rows] == ["InstallFinalizeResult"]


def test_handle_install_does_not_reapply_setup_clipboard_when_already_recorded(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path)
    applied_calls: list[tuple[str, tuple[str, ...]]] = []

    class Installer:
        def list_versions(self):
            return []

        def install(self, **kwargs):
            context.registry.upsert(
                name="ubuntu",
                distro="ubuntu",
                path=str(context.config.chroot_base),
                phase="finalize",
                installed=True,
                metadata={"tools": "setup-clipboard"},
            )
            return [InstallFinalizeResult(installed=True, uid_sync=True, snapshot="snap-1")]

    monkeypatch.setattr(install_runtime, "build_installer", lambda *args, **kwargs: Installer())
    monkeypatch.setattr(install_runtime, "apply_catalog_entries", lambda **kwargs: applied_calls.append((kwargs["catalog"].kind, tuple(kwargs["names"]))) or [])
    monkeypatch.setattr(install_runtime, "progress_call", lambda description, fn: fn())
    monkeypatch.setattr(install_runtime, "install_selection_names", lambda **kwargs: kwargs["explicit_names"])
    monkeypatch.setattr(install_runtime, "emit_table", lambda context, title, rows: None)
    monkeypatch.setattr(install_runtime, "emit_panel", lambda context, title, data: None)

    install_runtime.handle_install(context)

    assert applied_calls == []


def test_handle_install_shows_resume_next_steps_for_incomplete_install(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path)
    panels: list[tuple[str, object]] = []

    class Installer:
        def list_versions(self):
            return []

        def install(self, **kwargs):
            return [InstallFinalizeResult(installed=False, uid_sync=False, snapshot="snap-1")]

    monkeypatch.setattr(install_runtime, "build_installer", lambda *args, **kwargs: Installer())
    monkeypatch.setattr(install_runtime, "progress_call", lambda description, fn: fn())
    monkeypatch.setattr(install_runtime, "install_selection_names", lambda **kwargs: kwargs["explicit_names"])
    monkeypatch.setattr(install_runtime, "emit_table", lambda context, title, rows: None)
    monkeypatch.setattr(install_runtime, "emit_panel", lambda context, title, data: panels.append((title, data)))

    install_runtime.handle_install(context)

    assert panels == [
        (
            "Next Steps",
            {
                "resume": "chrootctl install ubuntu --resume",
                "logs": "chrootctl logs --all",
            },
        )
    ]


def test_handle_install_uses_selected_chroot_name_for_registry_lookup(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path)
    context.args.name = "work"
    rendered: dict[str, object] = {}
    panels: list[tuple[str, object]] = []

    class Installer:
        def list_versions(self):
            return []

        def install(self, **kwargs):
            context.registry.upsert(
                name="work",
                distro="ubuntu",
                path=str(context.config.for_chroot("work").chroot_base),
                phase="finalize",
                installed=True,
            )
            return [InstallFinalizeResult(installed=True, uid_sync=True, snapshot="snap-1")]

    monkeypatch.setattr(install_runtime, "build_installer", lambda *args, **kwargs: Installer())
    monkeypatch.setattr(install_runtime, "apply_catalog_entries", lambda **kwargs: [])
    monkeypatch.setattr(install_runtime, "progress_call", lambda description, fn: fn())
    monkeypatch.setattr(install_runtime, "install_selection_names", lambda **kwargs: kwargs["explicit_names"])
    monkeypatch.setattr(install_runtime, "emit_table", lambda context, title, rows: rendered.update({"title": title, "rows": rows}))
    monkeypatch.setattr(install_runtime, "emit_panel", lambda context, title, data: panels.append((title, data)))

    install_runtime.handle_install(context)

    assert rendered["title"] == "Install Results"
    assert panels == [
        (
            "Next Steps",
            {
                "start": "chrootctl start",
                "sync_id": "chrootctl users sync-id mike",
                "tools_apply": "chrootctl tools apply <tool>",
                "addons_apply": "chrootctl addons apply <addon>",
                "logs": "chrootctl logs --all",
            },
        )
    ]


def test_handle_install_runs_wizard_and_uses_selected_values(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path)
    context.args.distro = None
    context.args.username = None
    context.args.wizard = True
    panels: list[tuple[str, object]] = []
    install_calls: list[dict[str, object]] = []

    class Installer:
        def list_versions(self):
            return []

        def install(self, **kwargs):
            install_calls.append(kwargs)
            context.registry.upsert(
                name="work",
                distro="ubuntu",
                path=str(context.config.for_chroot("work").chroot_base),
                phase="finalize",
                installed=True,
            )
            return [InstallFinalizeResult(installed=True, uid_sync=True, snapshot="snap-1")]

    monkeypatch.setattr(
        install_runtime,
        "_run_install_wizard",
        lambda context: install_runtime.InstallWizardSelection(
            distro="ubuntu",
            name="work",
            username="devuser",
            profile="dev",
            desktop=None,
            release="24.04",
            version=None,
            tools=["tool-a"],
            addons=["addon-a"],
        ),
    )
    monkeypatch.setattr(install_runtime, "build_installer", lambda *args, **kwargs: Installer())
    monkeypatch.setattr(install_runtime, "apply_catalog_entries", lambda **kwargs: [])
    monkeypatch.setattr(install_runtime, "install_selection_names", lambda **kwargs: kwargs["explicit_names"])
    monkeypatch.setattr(install_runtime, "progress_call", lambda description, fn: fn())
    monkeypatch.setattr(install_runtime, "emit_table", lambda context, title, rows: None)
    monkeypatch.setattr(install_runtime, "emit_panel", lambda context, title, data: panels.append((title, data)))

    install_runtime.handle_install(context)

    assert context.args.name == "work"
    assert context.args.username == "devuser"
    assert context.args.tools == ["tool-a"]
    assert context.args.addons == ["addon-a"]
    assert install_calls == [
        {
            "phase": None,
            "username": "devuser",
            "desktop": None,
            "version": None,
            "release": "24.04",
            "force_phase": False,
            "auto": False,
            "resume": False,
            "repair": False,
            "profile": "dev",
        }
    ]
    assert panels[-1] == (
        "Next Steps",
        {
            "start": "chrootctl start",
            "sync_id": "chrootctl users sync-id devuser",
            "tools_apply": "chrootctl tools apply <tool>",
            "addons_apply": "chrootctl addons apply <addon>",
            "logs": "chrootctl logs --all",
        },
    )


def test_initial_wizard_state_uses_existing_install_defaults(tmp_path: Path) -> None:
    context = build_context(tmp_path)
    context.args.distro = None
    context.args.name = None
    context.args.username = None
    context.registry.upsert(
        name="work",
        distro="ubuntu",
        path=str(context.config.for_chroot("work").chroot_base),
        phase="desktop",
        installed=False,
        release_name="24.04",
        version="24.04",
        metadata={"username": "devuser", "profile": "dev", "desktop": "xfce4"},
    )

    state = install_runtime._initial_wizard_state(context)

    assert state.distro == "ubuntu"
    assert state.name == "work"
    assert state.username == "devuser"
    assert state.profile == "dev"
    assert state.desktop == "xfce4"
    assert state.release == "24.04"


def test_maybe_run_post_install_actions_syncs_and_starts(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path)
    context.args.wizard = True
    context.registry.upsert(
        name="ubuntu",
        distro="ubuntu",
        path=str(context.config.chroot_base),
        phase="finalize",
        installed=True,
    )
    sync_calls: list[tuple[str, bool]] = []
    start_calls: list[tuple[bool, bool]] = []
    panels: list[tuple[str, object]] = []

    class FakeUserSync:
        def sync_id(self, *, username: str, fix_ownership: bool):
            sync_calls.append((username, fix_ownership))
            return {"username": username, "ownership_fixed": fix_ownership}

    class FakeController:
        def start(self, *, login: bool, root_login: bool):
            start_calls.append((login, root_login))
            return 0

    monkeypatch.setattr(install_runtime.os, "isatty", lambda fd: True)
    monkeypatch.setattr(install_runtime, "_choose_post_install_action", lambda username: "sync-and-start")
    monkeypatch.setattr(install_runtime, "_build_user_sync", lambda context, config: FakeUserSync())
    monkeypatch.setattr(install_runtime, "_build_controller", lambda context, config: FakeController())
    monkeypatch.setattr(install_runtime, "progress_call", lambda description, fn, interactive=False: fn())
    monkeypatch.setattr(install_runtime, "emit_panel", lambda context, title, data: panels.append((title, data)))

    install_runtime._maybe_run_post_install_actions(
        context,
        context.config.with_overrides(username="devuser"),
        "devuser",
        [InstallFinalizeResult(installed=True, uid_sync=True, snapshot="snap-1")],
    )

    assert sync_calls == [("devuser", True)]
    assert start_calls == [(True, False)]
    assert panels == [("User Sync", {"username": "devuser", "ownership_fixed": True})]


def test_handle_install_allows_fresh_install_with_explicit_username(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path)
    context.args.username = "devuser"
    install_calls: list[dict[str, object]] = []

    class Installer:
        def list_versions(self):
            return []

        def install(self, **kwargs):
            install_calls.append(kwargs)
            return [InstallFinalizeResult(installed=True, uid_sync=True, snapshot="snap-1")]

    monkeypatch.setattr(install_runtime, "build_installer", lambda *args, **kwargs: Installer())
    monkeypatch.setattr(install_runtime, "progress_call", lambda description, fn: fn())
    monkeypatch.setattr(install_runtime, "install_selection_names", lambda **kwargs: kwargs["explicit_names"])
    monkeypatch.setattr(install_runtime, "emit_table", lambda context, title, rows: None)
    monkeypatch.setattr(install_runtime, "emit_panel", lambda context, title, data: None)

    install_runtime.handle_install(context)

    assert install_calls[0]["username"] == "devuser"


def test_handle_install_requires_explicit_or_discoverable_username_for_fresh_install(monkeypatch, tmp_path: Path) -> None:
    context = build_context(tmp_path)
    context.args.username = None
    context.config = context.config.with_overrides(username=None)
    install_calls: list[dict[str, object]] = []

    class Installer:
        def list_versions(self):
            return []

        def install(self, **kwargs):
            install_calls.append(kwargs)
            return [InstallFinalizeResult(installed=True, uid_sync=True, snapshot="snap-1")]

    monkeypatch.setattr(install_runtime, "build_installer", lambda *args, **kwargs: Installer())
    monkeypatch.setattr(install_runtime, "progress_call", lambda description, fn: fn())
    monkeypatch.setattr(install_runtime, "install_selection_names", lambda **kwargs: kwargs["explicit_names"])
    monkeypatch.setattr(install_runtime, "emit_table", lambda context, title, rows: None)
    monkeypatch.setattr(install_runtime, "emit_panel", lambda context, title, data: None)

    with pytest.raises(RuntimeError, match="install requires --username"):
        install_runtime.handle_install(context)

    assert install_calls == []
