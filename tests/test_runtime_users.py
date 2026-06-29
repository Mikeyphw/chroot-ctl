from __future__ import annotations

import argparse
from types import SimpleNamespace

from chrootctl.runtime import users


class UserRow:
    def __init__(self, username: str):
        self.username = username
        self.uid = 1000
        self.gid = 1000
        self.shell = "/bin/bash"


class UserManager:
    def user_rows(self):
        return [UserRow("mike")]

    def set_password(self, username: str):
        assert username == "mike"
        return {"updated": True}


def test_handle_users_password_skips_spinner_for_interactive_prompt(monkeypatch) -> None:
    context = SimpleNamespace(
        args=argparse.Namespace(users_command="password", username="mike", non_interactive=False),
        chroot_users=UserManager(),
    )
    calls: list[tuple[str, bool]] = []

    def fake_progress_call(description, fn, *, interactive=False):
        calls.append((description, interactive))
        return fn()

    monkeypatch.setattr(users, "progress_call", fake_progress_call)

    rendered_panels: list[tuple[str, object]] = []
    monkeypatch.setattr(users, "emit_panel", lambda context, title, data: rendered_panels.append((title, data)))

    users.handle_users(context)

    assert calls == [("Updating user password", True)]
    assert rendered_panels == [("Chroot User Password", {"updated": True})]
