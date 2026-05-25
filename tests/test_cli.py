from __future__ import annotations

import argparse

import pytest

from chrootctl.cli import build_parser


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
    remove_args = parser.parse_args(["chroots", "remove", "work"])
    rename_args = parser.parse_args(["chroots", "rename", "old", "new"])

    assert show_args.chroot_name == "work"
    assert remove_args.chroot_name == "work"
    assert rename_args.old_name == "old"
    assert rename_args.new_name == "new"


def test_install_parser_supports_recovery_and_profile_flags() -> None:
    parser = build_parser()

    args = parser.parse_args(["install", "ubuntu", "--resume", "--repair", "--profile", "dev"])

    assert args.resume is True
    assert args.repair is True
    assert args.profile == "dev"


def test_completion_parser_supports_zsh() -> None:
    parser = build_parser()

    args = parser.parse_args(["completion", "zsh"])

    assert args.command == "completion"
    assert args.completion_shell == "zsh"
