
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .output import effective_width, wrap_text


@dataclass(frozen=True, slots=True)
class Choice:
    value: str
    label: str
    description: str = ""
    preview: str = ""


def select_one(choices: Sequence[Choice], *, prompt: str) -> str:
    if not choices:
        raise RuntimeError(f"no choices available for {prompt}")
    selected = select_many(choices, prompt=prompt, multi=False)
    if not selected:
        raise RuntimeError(f"no selection made for {prompt}")
    return selected[0]


def select_many(choices: Sequence[Choice], *, prompt: str, multi: bool = True) -> list[str]:
    if not choices:
        return []
    if _fzf_available():
        return _select_with_fzf(choices, prompt=prompt, multi=multi)
    if not os.isatty(0):
        raise RuntimeError("fzf is not available and interactive selection requires a tty")
    return _select_with_prompt(choices, multi=multi)


def prompt_text(
    prompt: str,
    *,
    default: str | None = None,
    validator: Callable[[str], str] | None = None,
    allow_back: bool = False,
    allow_skip: bool = False,
) -> str:
    if not os.isatty(0):
        raise RuntimeError(f"{prompt}: interactive input requires a tty")
    prompt_suffix = f" [{default}]" if default else ""
    hints: list[str] = []
    if allow_back:
        hints.append(":back")
    if allow_skip:
        hints.append(":skip")
    hint_suffix = f" ({', '.join(hints)})" if hints else ""
    raw = input(f"{prompt}{prompt_suffix}{hint_suffix}: ").strip()
    if allow_back and raw == ":back":
        return raw
    if allow_skip and raw == ":skip":
        return raw
    value = raw or default
    if value is None:
        raise RuntimeError(f"{prompt}: value is required")
    if validator is None:
        return value
    try:
        return validator(value)
    except (RuntimeError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc


def confirm(prompt: str, *, details: str | None = None, default: bool = True) -> bool:
    if details:
        print(details)
    if _fzf_available():
        answer = select_one(
            [
                Choice("yes", "yes", "Proceed with the selected action."),
                Choice("no", "no", "Cancel without making changes."),
            ],
            prompt=prompt,
        )
        return answer == "yes"
    if not os.isatty(0):
        raise RuntimeError(f"{prompt}: confirmation requires a tty")
    suffix = " [Y/n]: " if default else " [y/N]: "
    raw = input(f"{prompt}{suffix}").strip().lower()
    if not raw:
        return default
    if raw in {"y", "yes"}:
        return True
    if raw in {"n", "no"}:
        return False
    raise RuntimeError(f"{prompt}: expected yes or no")


def _fzf_available() -> bool:
    import shutil

    return shutil.which("fzf") is not None


def _bat_available() -> bool:
    import shutil

    return shutil.which("bat") is not None or shutil.which("batcat") is not None


def _select_with_fzf(choices: Sequence[Choice], *, prompt: str, multi: bool) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="chrootctl-fzf-") as temp_dir:
        preview_paths = _write_preview_files(choices, Path(temp_dir))
        lines = "\n".join(
            "\t".join([choice.value, choice.label, choice.description, preview_paths[choice.value]])
            for choice in choices
        )
        cmd = [
            "fzf",
            "--height=40%",
            "--layout=reverse",
            "--prompt",
            f"{prompt}>",
            "--delimiter=\t",
            "--with-nth=1,2,3",
        ]
        if multi:
            cmd.insert(1, "--multi")
        if any(choice.preview for choice in choices):
            cmd.extend(
                [
                    "--preview-window=right:60%:wrap",
                    "--preview",
                    _preview_command(),
                ]
            )
        completed = subprocess.run(
            cmd,
            input=lines,
            text=True,
            capture_output=True,
            check=False,
        )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(completed.stderr.strip() or "fzf selection failed")
    return [line.split("\t", 1)[0] for line in completed.stdout.splitlines() if line.strip()]


def _write_preview_files(choices: Sequence[Choice], directory: Path) -> dict[str, str]:
    paths: dict[str, str] = {}
    for index, choice in enumerate(choices, start=1):
        preview_file = directory / f"choice-{index}.txt"
        preview_file.write_text(choice.preview, encoding="utf-8")
        paths[choice.value] = str(preview_file)
    return paths


def _preview_command() -> str:
    viewer = "batcat" if _command_exists("batcat") else "bat" if _command_exists("bat") else "cat"
    return (
        "bash -lc 'path=$(printf \"%s\" \"$1\" | cut -f4-); "
        "if [ -n \"$path\" ] && [ -f \"$path\" ]; then "
        f"{viewer} --paging=never --style=plain \"$path\" 2>/dev/null || cat \"$path\"; "
        "fi' _ {}"
    )


def _command_exists(name: str) -> bool:
    import shutil

    return shutil.which(name) is not None


def _select_with_prompt(choices: Sequence[Choice], *, multi: bool) -> list[str]:
    width = effective_width()
    for index, choice in enumerate(choices, start=1):
        prefix = f"{index}. "
        label = wrap_text(
            choice.label,
            width=width,
            initial_indent=prefix,
            subsequent_indent=" " * len(prefix),
        )
        print(label)
        if choice.description:
            description_indent = " " * 4
            print(
                wrap_text(
                    choice.description,
                    width=width,
                    initial_indent=description_indent,
                    subsequent_indent=description_indent,
                )
            )
    raw = input("Choose number" + ("s" if multi else "") + ": ").strip()
    if not raw:
        return []
    separators = raw.replace(",", " ").split()
    selected: list[str] = []
    for part in separators:
        if not part.isdigit():
            raise RuntimeError(f"invalid selection: {part}")
        index = int(part)
        if index < 1 or index > len(choices):
            raise RuntimeError(f"selection out of range: {index}")
        selected.append(choices[index - 1].value)
        if not multi:
            break
    return list(dict.fromkeys(selected))
