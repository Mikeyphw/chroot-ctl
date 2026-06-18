from __future__ import annotations

from dataclasses import dataclass

import pytest

from chrootctl.interactive import Choice
from chrootctl.runtime import resolution


@dataclass(frozen=True)
class UserRow:
    username: str
    uid: str
    gid: str
    shell: str


class UserManager:
    def user_rows(self) -> list[UserRow]:
        return [UserRow(username="mike", uid="2000", gid="2000", shell="/bin/bash")]


@dataclass(frozen=True)
class Entry:
    name: str
    description: str
    categories: tuple[str, ...]


class Catalog:
    def __init__(self) -> None:
        self.kind = "tool"

    def list_entries(self, *, distro: str | None, category: str | None):
        return [
            Entry(name="alpha", description="first", categories=("system",)),
            Entry(name="beta", description="second", categories=("system",)),
        ]


class Registry:
    def list(self):
        return [{"name": "ubuntu", "distro": "ubuntu", "phase": "finalize", "installed": 1}]


def test_resolve_chroot_name_uses_explicit_value_without_selection(monkeypatch) -> None:
    called = False

    def fake_select_one(choices, *, prompt: str) -> str:
        nonlocal called
        called = True
        return "ignored"

    monkeypatch.setattr(resolution, "select_one", fake_select_one)

    value = resolution.resolve_chroot_name("ubuntu", Registry(), prompt="Choose chroot")

    assert value == "ubuntu"
    assert called is False


def test_resolve_username_falls_back_to_selection(monkeypatch) -> None:
    monkeypatch.setattr(resolution, "select_one", lambda choices, *, prompt: "mike")

    value = resolution.resolve_username(None, UserManager(), prompt="Choose user")

    assert value == "mike"


def test_resolve_catalog_names_merges_explicit_and_selected_without_duplicates(monkeypatch) -> None:
    monkeypatch.setattr(resolution, "select_many", lambda choices, *, prompt, multi: ["beta", "alpha", "beta"])

    names = resolution.resolve_catalog_names(
        catalog=Catalog(),
        distro="ubuntu",
        category=None,
        prompt="Choose tools",
        explicit_names=["alpha"],
        select_flag=True,
    )

    assert names == ["alpha", "beta"]


def test_catalog_choices_include_categories_and_description() -> None:
    choices = resolution.catalog_choices(Catalog(), distro="ubuntu", category=None)

    assert [Choice(value=item.value, label=item.label, description=item.description) for item in choices] == [
        Choice(value="alpha", label="alpha", description="system - first"),
        Choice(value="beta", label="beta", description="system - second"),
    ]
    assert "name: alpha" in choices[0].preview
    assert "categories: system" in choices[0].preview


def test_resolve_chroot_name_rejects_unknown_explicit_value() -> None:
    with pytest.raises(RuntimeError, match="unknown chroot: debian"):
        resolution.resolve_chroot_name("debian", Registry(), prompt="Choose chroot")


def test_resolve_catalog_names_rejects_unknown_explicit_values() -> None:
    with pytest.raises(RuntimeError, match="unknown tool: gamma"):
        resolution.resolve_catalog_names(
            catalog=Catalog(),
            distro="ubuntu",
            category=None,
            prompt="Choose tools",
            explicit_names=["gamma"],
            select_flag=False,
        )


def test_resolve_catalog_names_wraps_interactive_selection_errors(monkeypatch) -> None:
    def fake_select_many(choices, *, prompt, multi):
        raise RuntimeError("fzf is not available and interactive selection requires a tty")

    monkeypatch.setattr(resolution, "select_many", fake_select_many)

    with pytest.raises(RuntimeError, match="Choose tools: fzf is not available and interactive selection requires a tty"):
        resolution.resolve_catalog_names(
            catalog=Catalog(),
            distro="ubuntu",
            category=None,
            prompt="Choose tools",
            explicit_names=[],
            select_flag=True,
        )


def test_resolve_chroot_name_auto_selects_single_choice(monkeypatch) -> None:
    called = False

    def fake_select_one(choices, *, prompt: str) -> str:
        nonlocal called
        called = True
        return "ignored"

    monkeypatch.setattr(resolution, "select_one", fake_select_one)

    value = resolution.resolve_chroot_name(None, Registry(), prompt="Choose chroot", auto_select_single=True)

    assert value == "ubuntu"
    assert called is False


def test_resolve_runtime_chroot_name_uses_install_distro_by_default() -> None:
    args = type("Args", (), {"command": "install", "name": None, "distro": "arch"})()

    value = resolution.resolve_runtime_chroot_name(args, None, Registry())

    assert value == "arch"


def test_resolve_runtime_chroot_name_uses_single_installed_chroot_for_status() -> None:
    args = type("Args", (), {"command": "status", "name": None})()

    value = resolution.resolve_runtime_chroot_name(args, None, Registry())

    assert value == "ubuntu"


def test_resolve_username_fails_in_non_interactive_mode_when_multiple_choices(monkeypatch) -> None:
    class MultiUserManager:
        def user_rows(self):
            return [
                UserRow(username="mike", uid="2000", gid="2000", shell="/bin/bash"),
                UserRow(username="jane", uid="2001", gid="2001", shell="/bin/zsh"),
            ]

    with pytest.raises(RuntimeError, match="Choose user: selection required in non-interactive mode"):
        resolution.resolve_username(None, MultiUserManager(), prompt="Choose user", non_interactive=True)


def test_resolve_user_reference_auto_selects_single_non_root_user() -> None:
    value = resolution.resolve_user_reference(None, UserManager(), prompt="Choose user")

    assert value == "mike"


def test_resolve_user_reference_requires_username_when_no_non_root_users() -> None:
    class RootOnlyManager:
        def user_rows(self):
            return [UserRow(username="root", uid="0", gid="0", shell="/bin/bash")]

    with pytest.raises(RuntimeError, match="no non-root users available; pass --username"):
        resolution.resolve_user_reference(None, RootOnlyManager(), prompt="Choose user")
