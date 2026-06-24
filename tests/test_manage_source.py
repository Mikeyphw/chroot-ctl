from __future__ import annotations

from pathlib import Path

import manage_source


def test_manage_source_parser_supports_milestone7_commands() -> None:
    parser = manage_source.build_parser()
    for command in ("bootstrap-dev", "lint", "typecheck", "test", "release", "build-source"):
        args = parser.parse_args([command])
        assert args.command == command


def test_manage_source_install_editable_with_dev_flag() -> None:
    parser = manage_source.build_parser()
    args = parser.parse_args(["install-editable", "--with-dev"])
    assert args.with_dev is True


def test_write_checksum(tmp_path: Path) -> None:
    target = tmp_path / "artifact.bin"
    target.write_bytes(b"payload")
    checksum = manage_source._write_checksum(target)
    assert checksum.exists()
    assert target.name in checksum.read_text()


def test_manage_source_parser_supports_e2e_command() -> None:
    parser = manage_source.build_parser()
    args = parser.parse_args(["e2e", "--runner", "npx", "--", "--grep", "transfer"])
    assert args.command == "e2e"
    assert args.runner == "npx"
    assert args.e2e_args[-2:] == ["--grep", "transfer"]
