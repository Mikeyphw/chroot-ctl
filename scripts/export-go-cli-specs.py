#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "migration/contracts/v1/cli.json"
OUTPUT = ROOT / "internal/cli/specs_generated.go"


def q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def go_any(value: object) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return q(value)
    if isinstance(value, list):
        return "[]any{" + ",".join(go_any(item) for item in value) + "}"
    raise TypeError(f"unsupported generated value: {value!r}")


def argument(value: dict[str, object]) -> str:
    options = "[]string{" + ",".join(q(str(item)) for item in value["optionStrings"]) + "}"
    choices = "[]string{" + ",".join(q(str(item)) for item in (value.get("choices") or [])) + "}"
    return "{" + ",".join(
        [
            "Dest:" + q(str(value["dest"])),
            "Options:" + options,
            "Action:" + q(str(value["action"])),
            "NArgs:" + go_any(value.get("nargs")),
            "Default:" + go_any(value.get("default")),
            "Choices:" + choices,
            "Type:" + q(str(value.get("type") or "")),
            "Required:" + ("true" if value.get("required") else "false"),
            "Help:" + q(str(value.get("help") or "")),
        ]
    ) + "}"


def render() -> bytes:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if payload.get("contractSchemaVersion") != 1 or payload.get("commandNodeCount") != 66:
        raise SystemExit("unexpected frozen CLI contract identity")
    lines = [
        "// Code generated from migration/contracts/v1/cli.json; DO NOT EDIT.",
        "package cli",
        "",
        "var GlobalArguments = []ArgumentSpec{",
    ]
    for item in payload["globalArguments"]:
        lines.append("\t" + argument(item) + ",")
    lines += ["}", "", "var CommandSpecs = []CommandSpec{"]
    for item in payload["commandNodes"]:
        path = "[]string{" + ",".join(q(str(x)) for x in item["path"]) + "}"
        args = "[]ArgumentSpec{" + ",".join(argument(x) for x in item["arguments"]) + "}"
        lines.append(
            "\t{" + ",".join(
                [
                    "Command:" + q(str(item["command"])),
                    "Path:" + path,
                    "Description:" + q(str(item.get("description") or "")),
                    "Epilog:" + q(str(item.get("epilog") or "")),
                    "Arguments:" + args,
                ]
            ) + "},"
        )
    lines += ["}", ""]
    raw = "\n".join(lines).encode()
    with tempfile.NamedTemporaryFile(suffix=".go") as temp:
        temp.write(raw)
        temp.flush()
        proc = subprocess.run(["gofmt", temp.name], check=True, stdout=subprocess.PIPE)
        return proc.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        actual = OUTPUT.read_bytes() if OUTPUT.exists() else b""
        if actual != expected:
            print(f"Go CLI specs are stale: {OUTPUT.relative_to(ROOT)}")
            return 1
        print("Go CLI specs match the frozen 66-node contract.")
        return 0
    OUTPUT.write_bytes(expected)
    print(OUTPUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
