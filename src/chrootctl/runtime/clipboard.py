from __future__ import annotations

from pathlib import Path
import sys

from ..host_clipboard import chroot_socket_path, clipboard_doctor, daemon_status, default_paths, run_daemon, socket_get, socket_set, start_daemon, stop_daemon
from .common import console


def handle_clipboard(context) -> None:
    args = context.args
    defaults = default_paths(context.config)
    if args.clipboard_command == "daemon":
        socket_path = args.socket or defaults.socket_path
        pid_file = args.pid_file or defaults.pid_file
        log_file = args.log_file or defaults.log_file
        if args.daemon_action == "start":
            payload = start_daemon(context.config, socket_path=socket_path, pid_file=pid_file, log_file=log_file)
            console.print(f"clipboard daemon running pid={payload['pid']} socket={payload['socket']} log={payload['log_file']}")
            return
        if args.daemon_action == "run":
            run_daemon(context.config, socket_path=socket_path, pid_file=pid_file)
            return
        if args.daemon_action == "stop":
            payload = stop_daemon(pid_file)
            if payload.get("stopped"):
                console.print(f"clipboard daemon stopped pid={payload.get('pid')}")
            else:
                console.print("clipboard daemon is not running")
            return
        if args.daemon_action == "status":
            payload = daemon_status(pid_file)
            state = "running" if payload["running"] else "stopped"
            console.print(f"clipboard daemon {state} pid={payload.get('pid')} socket={socket_path}")
            return
        raise RuntimeError(f"unsupported clipboard daemon action: {args.daemon_action}")

    if args.clipboard_command == "doctor":
        payload = clipboard_doctor(
            context.config,
            pid_file=args.pid_file or defaults.pid_file,
            socket_path=args.socket or defaults.socket_path,
            registry_record=context.registry.get(context.config.distro_name) if getattr(context, "registry", None) is not None else None,
        )
        checks = [
            ("termux-clipboard-set", payload["termux_clipboard_set"]),
            ("termux-clipboard-get", payload["termux_clipboard_get"]),
            ("Termux:API app", payload["termux_api_package"]),
            ("clipboard daemon", payload["daemon_running"]),
            ("daemon runs as Termux user", payload.get("daemon_termux_user", False)),
            ("clipboard socket", payload["socket_exists"]),
            ("termux-clip wrapper", payload["wrappers"].get("termux-clip", False)),
            ("chrootctl-xsel wrapper", payload["wrappers"].get("chrootctl-xsel", False)),
            ("chrootctl-xclip wrapper", payload["wrappers"].get("chrootctl-xclip", False)),
            ("setup-clipboard recorded", payload["setup_clipboard_registered"]),
        ]
        for label, ok in checks:
            status = "OK" if ok else "MISSING"
            console.print(f"{status:<7} {label}")
        console.print(f"socket: {payload['socket_path']} -> {payload['chroot_socket_path']}")
        return

    socket_path = args.socket or Path(chroot_socket_path())
    if args.clipboard_command == "set":
        text = " ".join(args.text) if args.text else sys.stdin.read()
        payload = socket_set(socket_path, text)
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("error", "clipboard set failed")))
        return
    if args.clipboard_command == "get":
        payload = socket_get(socket_path)
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("error", "clipboard get failed")))
        print(str(payload.get("text", "")), end="")
        return
    raise RuntimeError(f"unsupported clipboard command: {args.clipboard_command}")
