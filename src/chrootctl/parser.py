
from __future__ import annotations

import argparse
from pathlib import Path
from textwrap import dedent

INSTALL_PROFILES = ["minimal", "dev", "xfce4", "plasma", "custom"]


class ChrootArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args=args, namespace=namespace)
        _validate_parsed_args(self, parsed)
        return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = ChrootArgumentParser(
        prog="chrootctl",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Manage Termux chroots for Ubuntu and Arch with install, runtime, user, and catalog commands.",
        epilog=_examples(
            """
            examples:
              chrootctl install ubuntu --username mike --profile dev --tool sync-uid
              chrootctl --name work status --details
              chrootctl users add mike --sudo --shell /bin/zsh
            """
        ),
    )
    parser.add_argument("--config", type=Path, default=None, help="Path to a config file. Defaults to the built-in config search path.")
    parser.add_argument("--dry-run", action="store_true", help="Print the actions that would run without changing the host or chroot.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging and richer diagnostic output.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON for supported status and listing commands.")
    parser.add_argument("--no-sudo", action="store_true", help="Do not auto-reexec with sudo for commands that require root.")
    parser.add_argument("--name", default=None, help="Target chroot name. Auto-selects when exactly one installed chroot exists.")
    parser.add_argument("--non-interactive", action="store_true", help="Fail instead of opening prompts or confirmations.")
    subs = parser.add_subparsers(dest="command", required=True, metavar="command")

    _add_runtime_commands(subs)
    _add_install_commands(subs)
    _add_completion_commands(subs)
    _add_chroot_commands(subs)
    _add_transfer_commands(subs)
    _add_events_commands(subs)
    _add_support_commands(subs)
    _add_clipboard_commands(subs)
    _add_user_commands(subs)
    _add_catalog_commands(subs, name="tools", item_label="tool")
    _add_catalog_commands(subs, name="addons", item_label="addon")
    _add_hidden_completion_command(subs)
    _add_magisk_commands(subs)

    return parser



def _add_clipboard_commands(subs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    clipboard = _add_parser(
        subs,
        "clipboard",
        help="Bridge clipboard access between the chroot and the Termux Android host.",
        description="Manage the host clipboard daemon and send clipboard get/set requests over the shared Unix socket.",
        examples="""
        examples:
          chrootctl clipboard daemon start
          chrootctl clipboard get
          chrootctl clipboard set "hello from host"
        """,
    )
    clipboard_subs = clipboard.add_subparsers(dest="clipboard_command", required=True, metavar="action")

    daemon = _add_parser(
        clipboard_subs,
        "daemon",
        help="Manage the host clipboard socket daemon.",
        description="Start, stop, inspect, or run the clipboard bridge daemon that serves the shared Unix socket.",
    )
    daemon_subs = daemon.add_subparsers(dest="daemon_action", required=True, metavar="daemon-action")
    for action in ("start", "stop", "status", "run"):
        daemon_parser = _add_parser(
            daemon_subs,
            action,
            help=f"{action.capitalize()} the clipboard daemon.",
            description=f"{action.capitalize()} the clipboard daemon.",
        )
        daemon_parser.add_argument("--socket", type=Path, default=None, help="Override the host-side clipboard socket path.")
        daemon_parser.add_argument("--pid-file", type=Path, default=None, help="Override the clipboard daemon PID file.")
        daemon_parser.add_argument("--log-file", type=Path, default=None, help="Override the clipboard daemon log file.")

    set_parser = _add_parser(
        clipboard_subs,
        "set",
        help="Send text to the host clipboard daemon.",
        description="Write clipboard text through the shared Unix socket. Reads stdin when no text arguments are provided.",
    )
    set_parser.add_argument("--socket", type=Path, default=None, help="Override the clipboard socket path.")
    set_parser.add_argument("text", nargs="*", help="Clipboard text. Reads stdin when omitted.")

    get_parser = _add_parser(
        clipboard_subs,
        "get",
        help="Read text from the host clipboard daemon.",
        description="Fetch clipboard text from the shared Unix socket and print it to stdout.",
    )
    get_parser.add_argument("--socket", type=Path, default=None, help="Override the clipboard socket path.")

    doctor_parser = _add_parser(
        clipboard_subs,
        "doctor",
        help="Check clipboard bridge readiness for the host and current chroot.",
        description="Report Termux clipboard commands, daemon/socket state, and whether the current chroot already has clipboard wrapper tools or will auto-adapt on first start.",
    )
    doctor_parser.add_argument("--socket", type=Path, default=None, help="Override the clipboard socket path.")
    doctor_parser.add_argument("--pid-file", type=Path, default=None, help="Override the clipboard daemon PID file.")


def _add_magisk_commands(subs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    magisk = _add_parser(
        subs,
        "magisk",
        help="Render a Magisk split module for boot-time chroot ownership.",
        description="Generate a Magisk module that owns boot-time mounts/startup and a small privileged helper without embedding the Web UI stack.",
        examples="""
        examples:
          chrootctl magisk render --output /tmp/chrootctl-magisk
          chrootctl magisk render --output /tmp/chrootctl-magisk --all-installed
          chrootctl magisk render --output /tmp/chrootctl-magisk --name work --name dev
        """,
    )
    magisk_subs = magisk.add_subparsers(dest="magisk_command", required=True, metavar="magisk-command")
    render = _add_parser(
        magisk_subs,
        "render",
        help="Render a Magisk module tree.",
        description="Write a Magisk module directory with service.sh, post-fs-data.sh, and a privileged helper shim.",
        examples="""
        examples:
          chrootctl magisk render --output /tmp/chrootctl-magisk
          chrootctl magisk render --output /tmp/chrootctl-magisk --all-installed
        """,
    )
    render.add_argument("--output", type=Path, required=True, help="Target directory for the generated Magisk module tree.")
    render.add_argument("--zip", dest="zip_path", type=Path, default=None, help="Also create a flashable Magisk/KSU zip at this path.")
    render.add_argument(
        "--wheelhouse",
        dest="wheelhouse_dir",
        type=Path,
        default=None,
        help="Optional directory of offline wheels to bundle for first-boot dependency bootstrap.",
    )
    render.add_argument(
        "--all-installed",
        action="store_true",
        help="Include every installed chroot in the boot startup target list.",
    )
    render.add_argument(
        "--name",
        dest="magisk_names",
        action="append",
        default=None,
        help="Explicit chroot name to include in the boot startup target list. Repeat as needed.",
    )

def _add_runtime_commands(subs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    status = _add_parser(
        subs,
        "status",
        help="Show current mount and chroot status.",
        description="Show current mount state for the active chroot.",
        examples="""
        examples:
          chrootctl status
          chrootctl status --details
        """,
    )
    status.add_argument("--details", action="store_true", help="Include extra filesystem checks and chroot phase details.")

    _add_parser(
        subs,
        "mount",
        help="Mount the active chroot.",
        description="Mount all required bind and virtual filesystems for the active chroot.",
        examples="""
        examples:
          chrootctl mount
        """,
    )
    _add_parser(
        subs,
        "unmount",
        help="Unmount the active chroot.",
        description="Unmount bind and virtual filesystems for the active chroot.",
        examples="""
        examples:
          chrootctl unmount
        """,
    )
    _add_parser(
        subs,
        "fix-tty",
        help="Repair tty and device permissions inside the chroot.",
        description="Repair tty and related device state required for interactive sessions.",
        examples="""
        examples:
          chrootctl fix-tty
        """,
    )
    _add_parser(
        subs,
        "doctor",
        help="Run diagnostics for the active chroot.",
        description="Inspect host tools, chroot files, root access, mounts, and logging state.",
        examples="""
        examples:
          chrootctl doctor
        """,
    )

    logs = _add_parser(
        subs,
        "logs",
        help="Show recent chrootctl logs.",
        description="Print the current log file, optionally tailing only the most recent lines.",
        examples="""
        examples:
          chrootctl logs
          chrootctl logs --tail 200
          chrootctl logs --all --level ERROR
          chrootctl logs --follow
        """,
    )
    logs_window = logs.add_mutually_exclusive_group()
    logs_window.add_argument("--tail", type=int, default=None, help="Number of recent log lines to show.")
    logs_window.add_argument("--all", action="store_true", help="Show the entire log file instead of just the tail.")
    logs.add_argument("--follow", action="store_true", help="Keep streaming appended log lines until interrupted.")
    logs.add_argument(
        "--level",
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Only include log records at or above this severity.",
    )

    start = _add_parser(
        subs,
        "start",
        help="Start an interactive shell in the chroot.",
        description="Start an interactive chroot session as root or as the configured user.",
        examples="""
        examples:
          chrootctl start
          chrootctl --name work start --login
        """,
    )
    start.add_argument("--login", action="store_true", help="Start a login shell as the configured chroot user.")
    start.add_argument("--root-login", action="store_true", help="Start a login shell as root instead of the configured user.")
    start.add_argument("--x11", action="store_true", help="Prepare Termux:X11 on the host and export DISPLAY/PULSE_SERVER for the session.")

    restart = _add_parser(
        subs,
        "restart",
        help="Restart the interactive chroot session.",
        description="Unmount and then start the target chroot again.",
        examples="""
        examples:
          chrootctl restart
          chrootctl --name work restart --login
        """,
    )
    restart.add_argument("--login", action="store_true", help="Restart into a login shell as the configured chroot user.")
    restart.add_argument("--root-login", action="store_true", help="Restart into a login shell as root.")
    restart.add_argument("--x11", action="store_true", help="Prepare Termux:X11 on the host and export DISPLAY/PULSE_SERVER for the session.")

    exec_parser = _add_parser(
        subs,
        "exec",
        help="Run a command inside the chroot.",
        description="Execute a single non-interactive command inside the active chroot.",
        examples="""
        examples:
          chrootctl exec -- command -v python3
          chrootctl exec --root --command "id -u"
        """,
    )
    exec_parser.add_argument("--root", action="store_true", help="Run the command as root inside the chroot.")
    exec_parser.add_argument("--command", dest="exec_text", default=None, help="Shell command text to execute inside the chroot.")
    exec_parser.add_argument("--x11", action="store_true", help="Prepare Termux:X11 on the host and export DISPLAY/PULSE_SERVER for the command.")
    exec_parser.add_argument("argv", nargs=argparse.REMAINDER, help="Command arguments after '--'.")


def _add_install_commands(subs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    install = _add_parser(
        subs,
        "install",
        help="Install or resume an Ubuntu or Arch chroot.",
        description="Install a supported distro through extract, bootstrap, desktop, and finalize phases.",
        examples="""
        examples:
          chrootctl install --wizard
          chrootctl install ubuntu --username devuser
          chrootctl install ubuntu --resume --username devuser
          chrootctl install arch --phase bootstrap --force-phase --username devuser
          chrootctl install ubuntu --username devuser --profile dev --tool sync-uid --select-addons
        """,
    )
    install.add_argument("distro", nargs="?", choices=["ubuntu", "arch"], help="Distro to install. Prompts in wizard mode when omitted.")
    install.add_argument("--wizard", action="store_true", help="Run a guided interactive install wizard.")
    install.add_argument("--phase", choices=["extract", "bootstrap", "desktop", "finalize"], default=None, help="Start at a specific install phase.")
    install.add_argument("--force-phase", action="store_true", help="Run the requested phase even if the registry says it was already completed.")
    install.add_argument("--resume", action="store_true", help="Resume from the detected or recorded install phase.")
    install.add_argument("--repair", action="store_true", help="Attempt a repair-oriented install pass for an existing chroot.")
    install.add_argument("--list-versions", action="store_true", help="List available distro versions/releases and exit.")
    install.add_argument("--version", default=None, help="Requested version identifier, if the installer supports it.")
    install.add_argument("--release", default=None, help="Requested release name, if the installer supports it.")
    install.add_argument("--mirror", default=None, help="Preferred package or rootfs mirror identifier. Use auto to let the backend choose.")
    install.add_argument("--username", default=None, help="Initial non-root username to create during bootstrap/finalize.")
    install.add_argument("--arch", choices=["arm64", "amd64"], default=None, help="Target rootfs architecture. Use arm64 on amd64 hosts for phone-bound exports.")
    install.add_argument("--preset", choices=["minimal-server", "desktop-xfce", "development", "recovery-debug"], default=None, help="Backend-driven install preset that resolves profile, desktop, and default package selections.")
    install.add_argument("--desktop", choices=["xfce4", "plasma", "none"], default=None, help="Optional desktop environment to configure.")
    install.add_argument("--profile", choices=INSTALL_PROFILES, default=None, help="Install profile to apply during bootstrap/desktop phases.")
    install.add_argument("--tool", dest="tools", action="append", default=[], help="Tool to apply after finalize. May be passed multiple times.")
    install.add_argument("--addon", dest="addons", action="append", default=[], help="Addon to apply after finalize. May be passed multiple times.")
    install.add_argument("--select-tools", action="store_true", help="Interactively choose tool(s) to apply after finalize.")
    install.add_argument("--select-addons", action="store_true", help="Interactively choose addon(s) to apply after finalize.")

    upgrade = _add_parser(
        subs,
        "upgrade",
        help="Upgrade the installed chroot in place.",
        description="Run the distro-specific upgrade flow for the active installed chroot.",
        examples="""
        examples:
          chrootctl upgrade
          chrootctl upgrade --username mike
        """,
    )
    upgrade.add_argument("--username", default=None, help="Username to use for any user-aware upgrade steps.")


def _add_completion_commands(subs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    completion = _add_parser(
        subs,
        "completion",
        help="Generate shell completion scripts.",
        description="Generate completion scripts for supported shells.",
        examples="""
        examples:
          chrootctl completion zsh
        """,
    )
    completion_sub = completion.add_subparsers(dest="completion_shell", required=True, metavar="shell")
    _add_parser(
        completion_sub,
        "zsh",
        help="Generate zsh completion.",
        description="Print the zsh completion script to stdout.",
        examples="""
        examples:
          chrootctl completion zsh > _chrootctl
        """,
    )


def _add_chroot_commands(subs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    chroots = _add_parser(
        subs,
        "chroots",
        help="Inspect and manage installed chroots.",
        description="List, inspect, remove, or rename installed chroots.",
        examples="""
        examples:
          chrootctl chroots list
          chrootctl --name work chroots show
          chrootctl --name old chroots rename new
          chrootctl --name work chroots remove --yes
        """,
    )
    chroots_sub = chroots.add_subparsers(dest="chroots_command", required=True, metavar="action")

    _add_parser(
        chroots_sub,
        "list",
        help="List known chroots.",
        description="Show all registry entries for known chroots.",
        examples="""
        examples:
          chrootctl chroots list
        """,
    )

    _add_parser(
        chroots_sub,
        "show",
        help="Show details for a chroot.",
        description="Show registry and configuration details for the target chroot.",
        examples="""
        examples:
          chrootctl --name work chroots show
          chrootctl chroots show
        """,
    )

    remove = _add_parser(
        chroots_sub,
        "remove",
        help="Remove a chroot.",
        description="Unmount and remove the target chroot directory plus its registry entry.",
        examples="""
        examples:
          chrootctl --name work chroots remove
          chrootctl chroots remove --yes
        """,
    )
    remove.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    rename = _add_parser(
        chroots_sub,
        "rename",
        help="Rename a chroot.",
        description="Rename the target chroot directory and update its registry entry.",
        examples="""
        examples:
          chrootctl --name old chroots rename new
          chrootctl chroots rename new
        """,
    )
    rename.add_argument("new_name", nargs="?", help="New chroot name to assign.")

    export_cmd = _add_parser(
        chroots_sub,
        "export",
        help="Export a chroot to a tar.zst archive.",
        description="Create a tar.zst archive that can be imported on another host or phone.",
        examples="""
        examples:
          chrootctl --name work chroots export
          chrootctl --name work chroots export /tmp/work.tar.zst
        """,
    )
    export_cmd.add_argument("archive", nargs="?", type=Path, help="Destination tar.zst path. Defaults to ./<name>.tar.zst")
    export_cmd.add_argument("--password", default=None, help="Optional password to encrypt the archive with openssl.")

    import_cmd = _add_parser(
        chroots_sub,
        "import",
        help="Import a chroot from a tar.zst archive.",
        description="Extract a previously exported tar.zst archive into the chroot root and register it.",
        examples="""
        examples:
          chrootctl chroots import /tmp/work.tar.zst
          chrootctl chroots import /tmp/work.tar.zst --name phone-work
        """,
    )
    import_cmd.add_argument("archive", type=Path, help="Source tar.zst archive.")
    import_cmd.add_argument("--name", dest="import_name", default=None, help="Optional new chroot name for the imported archive.")
    import_cmd.add_argument("--conflict", choices=("rename", "overwrite"), default="rename", help="How to handle an existing target name.")
    import_cmd.add_argument("--password", default=None, help="Password for encrypted .enc archives.")
    import_cmd.add_argument("--post-import", choices=("register", "validate", "fixups", "shell"), default="register", help="Optional action to run after import registration.")

    diff_cmd = _add_parser(
        chroots_sub,
        "diff",
        help="Compare package sets between two chroots.",
        description="Read package databases from two chroots and show what differs.",
        examples="""
        examples:
          chrootctl chroots diff work dev
        """,
    )
    diff_cmd.add_argument("left_name", help="Left-hand chroot name.")
    diff_cmd.add_argument("right_name", help="Right-hand chroot name.")

    validate_import_cmd = _add_parser(
        chroots_sub,
        "validate-import",
        help="Validate an imported chroot on disk.",
        description="Check an imported chroot for required directories, config layout, and architecture markers.",
        examples="""
        examples:
          chrootctl --name work chroots validate-import
          chrootctl chroots validate-import work
        """,
    )
    validate_import_cmd.add_argument("validate_name", nargs="?", help="Imported chroot name. Defaults to --name or the single installed chroot.")


def _add_transfer_commands(subs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    transfer = _add_parser(
        subs,
        "transfer",
        help="Export or import chroots as tar.zst archives.",
        description="Move chroots between hosts with portable tar.zst archives.",
        examples="""
        examples:
          chrootctl --name work transfer export
          chrootctl transfer inspect /tmp/work.tar.zst
          chrootctl --name work transfer export /tmp/work.tar.zst
          chrootctl transfer import /tmp/work.tar.zst --name phone-work
        """,
    )
    transfer_sub = transfer.add_subparsers(dest="transfer_command", required=True, metavar="action")

    export_cmd = _add_parser(
        transfer_sub,
        "export",
        help="Export a chroot to tar.zst.",
        description="Create a tar.zst archive for transfer to another host or phone.",
        examples="""
        examples:
          chrootctl --name work transfer export
          chrootctl --name work transfer export /tmp/work.tar.zst
        """,
    )
    export_cmd.add_argument("archive", nargs="?", type=Path, help="Destination tar.zst path. Defaults to ./<name>.tar.zst")
    export_cmd.add_argument("--password", default=None, help="Optional password to encrypt the archive with openssl.")

    inspect_cmd = _add_parser(
        transfer_sub,
        "inspect",
        help="Inspect a tar.zst transfer archive.",
        description="Read the embedded export manifest and preview metadata before import.",
        examples="""
        examples:
          chrootctl transfer inspect /tmp/work.tar.zst
        """,
    )
    inspect_cmd.add_argument("archive", type=Path, help="Source tar.zst archive to inspect.")
    inspect_cmd.add_argument("--password", default=None, help="Password for encrypted .enc archives.")

    import_cmd = _add_parser(
        transfer_sub,
        "import",
        help="Import a chroot from tar.zst.",
        description="Extract a previously exported tar.zst archive into the chroot root and register it.",
        examples="""
        examples:
          chrootctl transfer import /tmp/work.tar.zst
          chrootctl transfer import /tmp/work.tar.zst --name phone-work
        """,
    )
    import_cmd.add_argument("archive", type=Path, help="Source tar.zst archive.")
    import_cmd.add_argument("--name", dest="import_name", default=None, help="Optional new chroot name for the imported archive.")
    import_cmd.add_argument("--conflict", choices=("rename", "overwrite"), default="rename", help="How to handle an existing target name.")
    import_cmd.add_argument("--password", default=None, help="Password for encrypted .enc archives.")
    import_cmd.add_argument("--post-import", choices=("register", "validate", "fixups", "shell"), default="register", help="Optional action to run after import registration.")


def _add_user_commands(subs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    users = _add_parser(
        subs,
        "users",
        help="Manage users inside the active chroot.",
        description="List, inspect, and update chroot users and user IDs.",
        examples="""
        examples:
          chrootctl --name work users list
          chrootctl --name work users add mike --sudo
          chrootctl --name work users remove mike --delete-home --yes
          chrootctl --name work users sync-id mike
        """,
    )
    users_sub = users.add_subparsers(dest="users_command", required=True, metavar="action")

    users_list = _add_parser(
        users_sub,
        "list",
        help="List chroot users.",
        description="Show users from the chroot passwd database.",
        examples="""
        examples:
          chrootctl --name work users list
          chrootctl users list
        """,
    )

    users_show = _add_parser(
        users_sub,
        "show",
        help="Show one chroot user.",
        description="Show shell, home, uid/gid, and sudo state for one chroot user.",
        examples="""
        examples:
          chrootctl users show mike
          chrootctl users show
        """,
    )
    users_show.add_argument("username", nargs="?", help="Chroot username. Prompts to choose when omitted.")

    users_add = _add_parser(
        users_sub,
        "add",
        help="Add a chroot user.",
        description="Create a new user inside the active chroot.",
        examples="""
        examples:
          chrootctl users add mike
          chrootctl users add mike --shell /bin/zsh --sudo
        """,
    )
    users_add.add_argument("username", nargs="?", help="Username to create.")
    users_add.add_argument("--shell", default="/bin/bash", help="Login shell to assign to the new user.")
    users_add.add_argument("--sudo", action="store_true", help="Grant passwordless sudo to the new user.")

    users_remove = _add_parser(
        users_sub,
        "remove",
        help="Remove a chroot user.",
        description="Delete a user from the active chroot and optionally delete the home directory.",
        examples="""
        examples:
          chrootctl users remove mike
          chrootctl users remove mike --delete-home --yes
          chrootctl users remove --yes
        """,
    )
    users_remove.add_argument("username", nargs="?", help="Username to remove. Prompts to choose when omitted.")
    users_remove.add_argument("--delete-home", action="store_true", help="Delete the user's home directory.")
    users_remove.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    users_password = _add_parser(
        users_sub,
        "password",
        help="Set a chroot user's password.",
        description="Open an interactive password update flow for one chroot user.",
        examples="""
        examples:
          chrootctl users password mike
          chrootctl users password
        """,
    )
    users_password.add_argument("username", nargs="?", help="Username to update. Prompts to choose when omitted.")

    users_shell = _add_parser(
        users_sub,
        "shell",
        help="Change a chroot user's shell.",
        description="Update the configured login shell for one chroot user.",
        examples="""
        examples:
          chrootctl users shell mike --shell /usr/bin/zsh
        """,
    )
    users_shell.add_argument("username", nargs="?", help="Username to update. Prompts to choose when omitted.")
    users_shell.add_argument("--shell", required=True, help="New login shell path.")

    users_sudo = _add_parser(
        users_sub,
        "sudo",
        help="Enable or disable sudo for a chroot user.",
        description="Update the dedicated sudoers fragment for one chroot user.",
        examples="""
        examples:
          chrootctl users sudo mike --enable
          chrootctl users sudo mike --disable
        """,
    )
    users_sudo.add_argument("username", nargs="?", help="Username to update. Prompts to choose when omitted.")
    sudo_mode = users_sudo.add_mutually_exclusive_group(required=True)
    sudo_mode.add_argument("--enable", action="store_true", help="Enable sudo for the selected user.")
    sudo_mode.add_argument("--disable", action="store_true", help="Disable sudo for the selected user.")

    show_id = _add_parser(
        users_sub,
        "show-id",
        help="Show host/chroot UID and GID mapping.",
        description="Show current Termux host UID/GID and the selected chroot user's UID/GID.",
        examples="""
        examples:
          chrootctl users show-id
          chrootctl users show-id mike
        """,
    )
    show_id.add_argument("username", nargs="?", help="Username to inspect inside the chroot. Prompts to choose when omitted.")

    sync_id = _add_parser(
        users_sub,
        "sync-id",
        help="Sync host UID/GID into the chroot user.",
        description="Update chroot UID/GID values to match the Termux host account.",
        examples="""
        examples:
          chrootctl users sync-id
          chrootctl users sync-id mike --no-fix-ownership
        """,
    )
    sync_id.add_argument("username", nargs="?", help="Username to update inside the chroot. Prompts to choose when omitted.")
    sync_id.add_argument("--no-fix-ownership", action="store_true", help="Do not chown the user's home and related files after syncing IDs.")


def _add_catalog_commands(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    name: str,
    item_label: str,
) -> None:
    parser = _add_parser(
        subs,
        name,
        help=f"Browse and apply {name}.",
        description=f"List, inspect, and apply packaged {name} for installed chroots.",
        examples=f"""
        examples:
          chrootctl {name} list
          chrootctl {name} show
          chrootctl {name} apply sample-name
          chrootctl {name} apply --category system
        """,
    )
    parser_sub = parser.add_subparsers(dest=f"{name}_command", required=True, metavar="action")

    categories = _add_parser(
        parser_sub,
        "categories",
        help=f"List available {name} categories.",
        description=f"Show normalized categories available for {name}.",
        examples=f"""
        examples:
          chrootctl {name} categories
          chrootctl {name} categories --distro ubuntu
        """,
    )
    categories.add_argument("--distro", choices=["ubuntu", "arch"], default=None, help="Only show categories supported by this distro.")

    list_parser = _add_parser(
        parser_sub,
        "list",
        help=f"List available {name}.",
        description=f"Show available {name} with distro, category, and script metadata.",
        examples=f"""
        examples:
          chrootctl {name} list
          chrootctl {name} list --distro ubuntu --category system
        """,
    )
    list_parser.add_argument("--distro", choices=["ubuntu", "arch"], default=None, help="Only list entries supported by this distro.")
    list_parser.add_argument("--category", default=None, help="Only list entries in this category.")

    show = _add_parser(
        parser_sub,
        "show",
        help=f"Show one {item_label}.",
        description=f"Show metadata for one {item_label}.",
        examples=f"""
        examples:
          chrootctl {name} show sample-name
          chrootctl {name} show
        """,
    )
    show.add_argument(f"{item_label}_name", nargs="?", help=f"{item_label.title()} name. Prompts to choose when omitted.")

    apply_parser = _add_parser(
        parser_sub,
        "apply",
        help=f"Apply one or more {name}.",
        description=f"Apply one or more {item_label}s to the active installed chroot.",
        examples=f"""
        examples:
          chrootctl --name work {name} apply sample-name
          chrootctl --name work {name} apply sample-a sample-b
          chrootctl {name} apply
          chrootctl {name} apply --category system
        """,
    )
    apply_parser.add_argument(f"{item_label}_names", nargs="*", help=f"{item_label.title()} names to apply. Prompts to choose when omitted.")
    apply_parser.add_argument("--category", default=None, help="Only offer entries in this category when choosing interactively.")


def _add_hidden_completion_command(subs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    hidden = _add_parser(
        subs,
        "__complete",
        help=argparse.SUPPRESS,
        description="Internal dynamic completion command.",
    )
    hidden.add_argument(
        "topic",
        choices=[
            "chroots",
            "installed-chroots",
            "chroot-details",
            "chroot-preview",
            "users",
            "tools",
            "addons",
            "tool-categories",
            "addon-categories",
            "tool-details",
            "addon-details",
            "tool-preview",
            "addon-preview",
        ],
        help="Completion topic.",
    )
    hidden.add_argument("values", nargs="*", help="Optional completion topic values.")
    subs._choices_actions = [
        action
        for action in subs._choices_actions
        if getattr(action, "dest", None) != "__complete"
    ]


def _validate_parsed_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.command == "install":
        _validate_install_args(parser, args)
    if args.command == "exec":
        _validate_exec_args(parser, args)


def _validate_install_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.wizard and args.non_interactive:
        parser.error("--wizard cannot be used with --non-interactive")
    if not args.wizard and args.distro is None:
        parser.error("install requires DISTRO unless --wizard is used")
    if args.force_phase and args.phase is None:
        parser.error("--force-phase requires --phase")
    if args.resume and args.phase is not None:
        parser.error("--resume cannot be used with --phase")
    if args.wizard and args.list_versions:
        parser.error("--wizard cannot be combined with --list-versions")
    if args.list_versions:
        conflicting_flags = [
            flag
            for flag, enabled in (
                ("--phase", args.phase is not None),
                ("--force-phase", args.force_phase),
                ("--resume", args.resume),
                ("--repair", args.repair),
                ("--version", args.version is not None),
                ("--release", args.release is not None),
                ("--username", args.username is not None),
                ("--desktop", args.desktop is not None),
                ("--profile", args.profile is not None),
                ("--tool", bool(args.tools)),
                ("--addon", bool(args.addons)),
                ("--select-tools", args.select_tools),
                ("--select-addons", args.select_addons),
            )
            if enabled
        ]
        if conflicting_flags:
            parser.error("--list-versions cannot be combined with " + ", ".join(conflicting_flags))


def _validate_exec_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    argv = list(args.argv or [])
    if argv and argv[0] == "--":
        argv = argv[1:]
    has_command_text = bool(args.exec_text)
    has_argv = bool(argv)
    if has_command_text == has_argv:
        parser.error("exec requires exactly one of --command or command arguments after '--'")


def _add_parser(
    subs: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    *,
    help: str | None = None,
    description: str | None = None,
    examples: str | None = None,
) -> argparse.ArgumentParser:
    kwargs: dict[str, object] = {
        "formatter_class": argparse.RawDescriptionHelpFormatter,
        "description": description,
    }
    if help is not None:
        kwargs["help"] = help
    parser = subs.add_parser(name, **kwargs)
    if examples:
        parser.epilog = _examples(examples)
    return parser


def _examples(text: str) -> str:
    return dedent(text).strip()


def _add_events_commands(subs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    events = _add_parser(
        subs,
        "events",
        help="List recent audit events.",
        description="Show recent install, transfer, build, and support-bundle events.",
        examples="""
        examples:
          chrootctl events list
        """,
    )
    events_sub = events.add_subparsers(dest="events_command", required=True, metavar="action")
    list_cmd = _add_parser(events_sub, "list", help="List recent events.", description="Show recent audit events.")
    list_cmd.add_argument("--limit", type=int, default=20, help="Maximum number of events to show.")


def _add_support_commands(subs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    support = _add_parser(
        subs,
        "support-bundle",
        help="Export a sanitized support bundle.",
        description="Bundle logs, doctor output, config, and recent jobs for debugging.",
    )
    support.add_argument("archive", nargs="?", type=Path, help="Destination tar.gz path. Defaults to ./chrootctl-support-bundle.tar.gz")
