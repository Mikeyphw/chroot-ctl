from __future__ import annotations

import argparse

import pytest

from chrootctl.cli import apply_start_name_shorthand, build_parser
from chrootctl.config import ChrootConfig
from chrootctl.registry import ChrootRegistry


def test_install_parser_accepts_supported_distros() -> None:
    parser = build_parser()

    ubuntu_args = parser.parse_args(["install", "ubuntu"])
    arch_args = parser.parse_args(["install", "arch"])

    assert ubuntu_args.distro == "ubuntu"
    assert arch_args.distro == "arch"
    assert ubuntu_args.desktop is None


def test_install_parser_rejects_manjaro() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["install", "manjaro"])


def test_start_parser_collects_login_and_argv() -> None:
    parser = build_parser()

    args = parser.parse_args(["start", "--login", "--", "echo", "hello"])

    assert args.command == "start"
    assert args.login is True
    assert args.root_login is False
    assert args.argv == ["--", "echo", "hello"]


def test_start_parser_collects_exec_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["start", "--exec-command", "id -u"])

    assert args.exec_command == "id -u"
    assert args.argv == []


def test_exec_parser_collects_command_and_root_flag() -> None:
    parser = build_parser()

    args = parser.parse_args(["exec", "--root", "--command", "id -u"])

    assert args.command == "exec"
    assert args.root is True
    assert args.exec_text == "id -u"


def test_chroots_parser_supports_show_remove_and_rename() -> None:
    parser = build_parser()

    show_args = parser.parse_args(["chroots", "show", "work"])
    show_missing_args = parser.parse_args(["chroots", "show"])
    remove_args = parser.parse_args(["chroots", "remove", "work"])
    rename_args = parser.parse_args(["chroots", "rename", "old", "new"])

    assert show_args.chroot_name == "work"
    assert show_missing_args.chroot_name is None
    assert remove_args.chroot_name == "work"
    assert rename_args.old_name == "old"
    assert rename_args.new_name == "new"


def test_install_parser_supports_recovery_and_profile_flags() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "install",
            "ubuntu",
            "--resume",
            "--repair",
            "--profile",
            "dev",
            "--tool",
            "remove-snapd",
            "--addon",
            "nala",
            "--select-tools",
            "--select-addons",
        ]
    )

    assert args.resume is True
    assert args.repair is True
    assert args.profile == "dev"
    assert args.tools == ["remove-snapd"]
    assert args.addons == ["nala"]
    assert args.select_tools is True
    assert args.select_addons is True


def test_catalog_parser_supports_tools_and_addons() -> None:
    parser = build_parser()

    tools_args = parser.parse_args(["tools", "list", "--distro", "ubuntu", "--category", "system"])
    addons_args = parser.parse_args(["addons", "apply", "nala"])

    assert tools_args.command == "tools"
    assert tools_args.tools_command == "list"
    assert tools_args.category == "system"
    assert addons_args.command == "addons"
    assert addons_args.addons_command == "apply"
    assert addons_args.addon_names == ["nala"]


def test_start_name_shorthand_selects_installed_chroot(tmp_path) -> None:
    parser = build_parser()
    config = ChrootConfig(chroot_root=tmp_path / "chroots", database_path=tmp_path / "registry.sqlite3")
    registry = ChrootRegistry(config.database_path)
    registry.upsert(name="ubuntu", distro="ubuntu", path=str(config.chroot_root / "ubuntu"), phase="finalize", installed=True)

    args = parser.parse_args(["start", "ubuntu"])
    resolved = apply_start_name_shorthand(args, config.for_chroot("default"), registry)

    assert resolved.distro_name == "ubuntu"
    assert args.login is True
    assert args.argv == []


def test_completion_parser_supports_zsh() -> None:
    parser = build_parser()

    args = parser.parse_args(["completion", "zsh"])

    assert args.command == "completion"
    assert args.completion_shell == "zsh"


def test_users_parser_supports_lifecycle_commands() -> None:
    parser = build_parser()

    list_args = parser.parse_args(["users", "list", "--name", "work"])
    show_args = parser.parse_args(["users", "show"])
    add_args = parser.parse_args(["users", "add", "mike", "--shell", "/bin/zsh", "--sudo"])
    remove_args = parser.parse_args(["users", "remove", "--delete-home"])
    password_args = parser.parse_args(["users", "password", "mike"])
    shell_args = parser.parse_args(["users", "shell", "mike", "--shell", "/usr/bin/zsh"])
    sudo_args = parser.parse_args(["users", "sudo", "mike", "--enable"])

    assert list_args.users_command == "list"
    assert list_args.name == "work"
    assert show_args.username is None
    assert add_args.username == "mike"
    assert add_args.shell == "/bin/zsh"
    assert add_args.sudo is True
    assert remove_args.username is None
    assert remove_args.delete_home is True
    assert password_args.username == "mike"
    assert shell_args.shell == "/usr/bin/zsh"
    assert sudo_args.enable is True


def test_install_parser_supports_tool_and_addon_flags() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "install",
            "ubuntu",
            "--tool",
            "sync-uid",
            "--tool",
            "remove-snapd",
            "--addon",
            "nala",
            "--select-tools",
            "--select-addons",
        ]
    )

    assert args.tools == ["sync-uid", "remove-snapd"]
    assert args.addons == ["nala"]
    assert args.select_tools is True
    assert args.select_addons is True


def test_tools_and_addons_parsers_support_list_show_apply_select_and_categories() -> None:
    parser = build_parser()

    tools_args = parser.parse_args(["tools", "apply", "sync-uid", "remove-snapd"])
    tools_missing_args = parser.parse_args(["tools", "apply"])
    addons_args = parser.parse_args(["addons", "list", "--distro", "ubuntu"])
    addon_show_missing_args = parser.parse_args(["addons", "show"])
    tool_show_args = parser.parse_args(["tools", "show", "sync-uid"])
    addon_select_args = parser.parse_args(["addons", "select"])
    tool_categories_args = parser.parse_args(["tools", "categories", "--distro", "ubuntu"])
    addon_categories_args = parser.parse_args(["addons", "categories"])

    assert tools_args.command == "tools"
    assert tools_args.tools_command == "apply"
    assert tools_args.tool_names == ["sync-uid", "remove-snapd"]
    assert tools_missing_args.tool_names == []
    assert addons_args.command == "addons"
    assert addons_args.addons_command == "list"
    assert addons_args.distro == "ubuntu"
    assert addon_show_missing_args.addon_name is None
    assert tool_show_args.tool_name == "sync-uid"
    assert addon_select_args.addons_command == "select"
    assert tool_categories_args.tools_command == "categories"
    assert tool_categories_args.distro == "ubuntu"
    assert addon_categories_args.addons_command == "categories"


def test_tools_and_addons_parser_support_category_filters() -> None:
    parser = build_parser()

    tools_list = parser.parse_args(["tools", "list", "--distro", "ubuntu", "--category", "ssh"])
    tools_select = parser.parse_args(["tools", "select", "--category", "system"])
    addons_list = parser.parse_args(["addons", "list", "--category", "desktop-environment"])
    addons_select = parser.parse_args(["addons", "select", "--category", "browser"])

    assert tools_list.category == "ssh"
    assert tools_select.category == "system"
    assert addons_list.category == "desktop-environment"
    assert addons_select.category == "browser"
