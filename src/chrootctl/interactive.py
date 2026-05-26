from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Sequence

from .output import effective_width, wrap_text


@dataclass(frozen=True, slots=True)
class Choice:
    value: str
    label: str
    description: str = ""


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


def _fzf_available() -> bool:
    import shutil

    return shutil.which("fzf") is not None


def _select_with_fzf(choices: Sequence[Choice], *, prompt: str, multi: bool) -> list[str]:
    lines = "\n".join(
        "\t".join([choice.value, choice.label, choice.description])
        for choice in choices
    )
    cmd = ["fzf", "--height=40%", "--layout=reverse", "--prompt", f"{prompt}>", "--with-nth=1,2,3"]
    if multi:
        cmd.insert(1, "--multi")
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
    raw = input("Select number" + ("s" if multi else "") + ": ").strip()
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
