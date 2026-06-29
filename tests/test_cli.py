from __future__ import annotations

import argparse

import pytest

from chrootctl.cli import apply_start_name_shorthand, build_parser


def test_install_parser_accepts_supported_distros() -> None:
    parser = build_parser()

    ubuntu_args = parser.parse_args(["install", "ubuntu"])
    arch_args = parser.parse_args(["install", "arch"])

    assert ubuntu_args.distro == "ubuntu"
    assert arch_args.distro == "arch"
    assert ubuntu_args.desktop is None
    assert ubuntu_args.username is None
    assert arch_args.username is None


def test_install_parser_rejects_manjaro() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["install", "manjaro"])


def test_install_parser_allows_wizard_without_distro() -> None:
    parser = build_parser()

    args = parser.parse_args(["install", "--wizard"])

    assert args.command == "install"
    assert args.wizard is True
    assert args.distro is None


def test_install_parser_requires_distro_without_wizard() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["install"])


def test_install_parser_rejects_wizard_in_non_interactive_mode() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--non-interactive", "install", "--wizard"])


def test_start_parser_collects_login_flags() -> None:
    parser = build_parser()

    args = parser.parse_args(["start", "--login", "--x11"])

    assert args.command == "start"
    assert args.login is True
    assert args.root_login is False
    assert args.x11 is True


def test_start_parser_defaults_to_interactive_root_shell() -> None:
    parser = build_parser()

    args = parser.parse_args(["start"])

    assert args.login is False
    assert args.root_login is False
    assert args.x11 is False


def test_exec_parser_collects_command_and_root_flag() -> None:
    parser = build_parser()

    args = parser.parse_args(["exec", "--root", "--x11", "--command", "id -u"])

    assert args.command == "exec"
    assert args.root is True
    assert args.x11 is True
    assert args.exec_text == "id -u"


def test_chroots_parser_supports_show_remove_and_rename() -> None:
    parser = build_parser()

    show_args = parser.parse_args(["--name", "work", "chroots", "show"])
    show_missing_args = parser.parse_args(["chroots", "show"])
    remove_args = parser.parse_args(["--name", "work", "chroots", "remove"])
    rename_args = parser.parse_args(["--name", "old", "chroots", "rename", "new"])

    assert show_args.name == "work"
    assert show_missing_args.name is None
    assert remove_args.name == "work"
    assert rename_args.name == "old"
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



def test_completion_parser_supports_zsh() -> None:
    parser = build_parser()

    args = parser.parse_args(["completion", "zsh"])

    assert args.command == "completion"
    assert args.completion_shell == "zsh"


def test_users_parser_supports_lifecycle_commands() -> None:
    parser = build_parser()

    list_args = parser.parse_args(["--name", "work", "users", "list"])
    show_args = parser.parse_args(["users", "show"])
    add_args = parser.parse_args(["users", "add", "mike", "--shell", "/bin/zsh", "--sudo"])
    remove_args = parser.parse_args(["users", "remove", "--delete-home"])
    password_args = parser.parse_args(["users", "password", "mike"])
    shell_args = parser.parse_args(["users", "shell", "mike", "--shell", "/usr/bin/zsh"])
    sudo_args = parser.parse_args(["users", "sudo", "mike", "--enable"])
    show_id_args = parser.parse_args(["users", "show-id", "mike"])
    sync_id_args = parser.parse_args(["users", "sync-id", "mike", "--no-fix-ownership"])

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
    assert show_id_args.username == "mike"
    assert sync_id_args.username == "mike"
    assert sync_id_args.no_fix_ownership is True


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


def test_tools_and_addons_parsers_support_list_show_apply_and_categories() -> None:
    parser = build_parser()

    tools_args = parser.parse_args(["tools", "apply", "sync-uid", "remove-snapd"])
    tools_missing_args = parser.parse_args(["tools", "apply", "--category", "system"])
    addons_args = parser.parse_args(["addons", "list", "--distro", "ubuntu"])
    addon_show_missing_args = parser.parse_args(["addons", "show"])
    tool_show_args = parser.parse_args(["tools", "show", "sync-uid"])
    tool_categories_args = parser.parse_args(["tools", "categories", "--distro", "ubuntu"])
    addon_categories_args = parser.parse_args(["addons", "categories"])

    assert tools_args.command == "tools"
    assert tools_args.tools_command == "apply"
    assert tools_args.tool_names == ["sync-uid", "remove-snapd"]
    assert tools_missing_args.tool_names == []
    assert tools_missing_args.category == "system"
    assert addons_args.command == "addons"
    assert addons_args.addons_command == "list"
    assert addons_args.distro == "ubuntu"
    assert addon_show_missing_args.addon_name is None
    assert tool_show_args.tool_name == "sync-uid"
    assert tool_categories_args.tools_command == "categories"
    assert tool_categories_args.distro == "ubuntu"
    assert addon_categories_args.addons_command == "categories"


def test_tools_and_addons_parser_support_category_filters() -> None:
    parser = build_parser()

    tools_list = parser.parse_args(["tools", "list", "--distro", "ubuntu", "--category", "ssh"])
    tools_apply = parser.parse_args(["tools", "apply", "--category", "system"])
    addons_list = parser.parse_args(["addons", "list", "--category", "desktop-environment"])
    addons_apply = parser.parse_args(["addons", "apply", "--category", "browser"])

    assert tools_list.category == "ssh"
    assert tools_apply.category == "system"
    assert addons_list.category == "desktop-environment"
    assert addons_apply.category == "browser"


def test_main_delegates_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    from chrootctl import cli

    captured: dict[str, object] = {}

    def fake_execute_cli(args: argparse.Namespace, *, prog: str, apply_start_name_shorthand_fn) -> None:
        captured["args"] = args
        captured["prog"] = prog
        captured["resolver"] = apply_start_name_shorthand_fn

    monkeypatch.setattr(cli.cli_runtime, "execute_cli", fake_execute_cli)
    monkeypatch.setattr("sys.argv", ["chrootctl", "status"])

    cli.main()

    assert isinstance(captured["args"], argparse.Namespace)
    assert captured["args"].command == "status"
    assert captured["prog"] == "chrootctl"
    assert captured["resolver"] is cli.apply_start_name_shorthand


def test_hidden_completion_command_is_omitted_from_help(capsys) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])

    output = capsys.readouterr().out

    assert "__complete" not in output
    assert "Manage Termux chroots" in output
    assert "install ubuntu --username mike --profile dev" in output


def test_remove_commands_support_yes_confirmation_flag() -> None:
    parser = build_parser()

    chroot_args = parser.parse_args(["--name", "work", "chroots", "remove", "--yes"])
    user_args = parser.parse_args(["users", "remove", "mike", "--yes"])

    assert chroot_args.yes is True
    assert user_args.yes is True


def test_status_help_includes_examples(capsys) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["status", "--help"])

    output = capsys.readouterr().out

    assert "Show current mount state for the active chroot." in output
    assert "chrootctl status --details" in output


def test_logs_parser_rejects_all_and_tail_together() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["logs", "--all", "--tail", "50"])


def test_global_name_defaults_to_none() -> None:
    parser = build_parser()

    args = parser.parse_args(["status"])

    assert args.name is None


def test_exec_parser_rejects_missing_command_source() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["exec"])


def test_exec_parser_rejects_both_command_styles() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["exec", "--command", "id -u", "--", "id", "-u"])


def test_install_parser_rejects_force_phase_without_phase() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["install", "ubuntu", "--force-phase"])


def test_install_parser_rejects_resume_with_phase() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["install", "ubuntu", "--resume", "--phase", "bootstrap"])


def test_install_parser_rejects_list_versions_with_mutating_flags() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["install", "ubuntu", "--list-versions", "--repair"])


def test_upgrade_parser_username_defaults_to_none() -> None:
    parser = build_parser()

    args = parser.parse_args(["upgrade"])

    assert args.username is None


def test_catalog_select_subcommand_is_removed() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["tools", "select"])


def test_non_interactive_global_flag_parses() -> None:
    parser = build_parser()

    args = parser.parse_args(["--non-interactive", "status"])

    assert args.non_interactive is True


def test_clipboard_parser_supports_daemon_and_io_commands() -> None:
    parser = build_parser()

    daemon_args = parser.parse_args(["clipboard", "daemon", "start"])
    set_args = parser.parse_args(["clipboard", "set", "hello"])
    get_args = parser.parse_args(["clipboard", "get"])

    assert daemon_args.command == "clipboard"
    assert daemon_args.clipboard_command == "daemon"
    assert daemon_args.daemon_action == "start"
    assert set_args.clipboard_command == "set"
    assert set_args.text == ["hello"]
    assert get_args.clipboard_command == "get"


def test_clipboard_doctor_parser_accepts_overrides() -> None:
    parser = build_parser()

    args = parser.parse_args(["clipboard", "doctor", "--socket", "/tmp/clip.sock", "--pid-file", "/tmp/clip.pid"])

    assert args.command == "clipboard"
    assert args.clipboard_command == "doctor"
    assert str(args.socket) == "/tmp/clip.sock"
    assert str(args.pid_file) == "/tmp/clip.pid"
