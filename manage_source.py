#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DIST = ROOT / "dist"


def _run(args: list[str], *, env: dict[str, str] | None = None) -> None:
    completed = subprocess.run(args, check=False, env=env)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _source_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) if not env.get("PYTHONPATH") else f"{env['PYTHONPATH']}:{SRC}"
    return env


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_checksum(path: Path) -> Path:
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    checksum_path.write_text(f"{_hash_file(path)}  {path.name}\n")
    return checksum_path


def _build_magisk(args: argparse.Namespace) -> None:
    script = f"""
from pathlib import Path
from chrootctl.magisk import MagiskModuleConfig, render_magisk_module, resolve_startup_targets, validate_magisk_module, zip_magisk_module
from chrootctl.services import create_service_container

out_dir = Path({str(args.output_dir)!r})
zip_path = Path({str(args.zip_path)!r})
wheelhouse = Path({str(args.wheelhouse)!r})
services = create_service_container(None, dry_run=False, verbose=False)
wheelhouse_dir = wheelhouse if wheelhouse.exists() and any(wheelhouse.glob("*.whl")) else None
startup_targets = resolve_startup_targets(services, all_installed=True)

render_magisk_module(
    out_dir,
    services=services,
    startup_targets=startup_targets,
    module_config=MagiskModuleConfig(offline_wheelhouse_dir=wheelhouse_dir),
)
validate_magisk_module(out_dir)
zip_magisk_module(out_dir, zip_path)
print(zip_path)
"""
    _run([args.python, "-c", script], env=_source_env())
    if args.checksum:
        print(_write_checksum(args.zip_path))


def _install_editable(args: argparse.Namespace) -> None:
    extras = "[dev]" if args.with_dev else ""
    _run([args.python, "-m", "pip", "install", "-e", f"{ROOT}{extras}"])


def _doctor_cross_arch(args: argparse.Namespace) -> None:
    script = f"""
import json
import logging
from chrootctl.system import SystemRunner

runner = SystemRunner(logging.getLogger("manage_source"))
arches = {args.arches!r}
payload = {{
    "host_arch": runner.host_arch(),
    "checks": [
        {{
            "arch": arch,
            "qemu_binfmt_ready": runner.can_execute_foreign_arch(arch),
        }}
        for arch in arches
    ],
}}
print(json.dumps(payload, indent=2, sort_keys=True))
"""
    _run([args.python, "-c", script], env=_source_env())


def _bootstrap_dev(args: argparse.Namespace) -> None:
    _run([args.python, "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"])
    _run([args.python, "-m", "pip", "install", "-e", f"{ROOT}[dev]"])


def _lint(args: argparse.Namespace) -> None:
    _run([args.python, "-m", "ruff", "check", str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "manage_source.py")])


def _typecheck(args: argparse.Namespace) -> None:
    _run([args.python, "-m", "mypy", str(ROOT / "src")])


def _test(args: argparse.Namespace) -> None:
    cmd = [args.python, "-m", "pytest"]
    cmd.extend(args.pytest_args)
    _run(cmd)


def _source_archive_path(version: str) -> Path:
    DIST.mkdir(parents=True, exist_ok=True)
    return DIST / f"chrootctl-source-{version}.tar.gz"


def _build_source_archive(args: argparse.Namespace) -> None:
    version = args.version
    archive_path = args.output or _source_archive_path(version)
    DIST.mkdir(parents=True, exist_ok=True)
    excludes = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git", "dist", "tmpout", ".venv"}
    with tarfile.open(archive_path, "w:gz") as tar:
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if any(part in excludes for part in rel.parts):
                continue
            tar.add(path, arcname=str(Path(ROOT.name) / rel), recursive=False)
    print(archive_path)
    if args.checksum:
        print(_write_checksum(archive_path))


def _release(args: argparse.Namespace) -> None:
    version = args.version
    magisk_dir = DIST / f"magisk-{version}"
    magisk_zip = DIST / f"chrootctl-magisk-{version}.zip"
    archive_path = args.source_archive or _source_archive_path(version)
    _lint(args)
    _typecheck(args)
    _test(argparse.Namespace(python=args.python, pytest_args=[]))
    _build_magisk(argparse.Namespace(
        python=args.python,
        output_dir=magisk_dir,
        zip_path=magisk_zip,
        wheelhouse=args.wheelhouse,
        checksum=True,
    ))
    _build_source_archive(argparse.Namespace(version=version, output=archive_path, checksum=True))
    print(f"release-ready: {magisk_zip} {archive_path}")



def _e2e(args: argparse.Namespace) -> None:
    extra_args = list(args.e2e_args)
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]
    cmd = [args.runner]
    cmd.extend(args.runner_args)
    cmd.extend(["playwright", "test"])
    cmd.extend(extra_args)
    env = os.environ.copy()
    env.setdefault("PLAYWRIGHT_HTML_OPEN", "never")
    env.setdefault("PYTHONPATH", str(SRC) if not env.get("PYTHONPATH") else f"{env['PYTHONPATH']}:{SRC}")
    _run(cmd, env=env)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Developer entrypoint for editable installs, checks, builds, and releases.")
    parser.add_argument("--python", default=sys.executable, help="Python interpreter to use.")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-magisk", help="Render and zip the Magisk module.")
    build.add_argument("--output-dir", type=Path, default=ROOT / "out", help="Rendered module directory.")
    build.add_argument("--zip-path", type=Path, default=ROOT / "chrootctl-magisk.zip", help="Flashable zip path.")
    build.add_argument("--wheelhouse", type=Path, default=ROOT / "wheelhouse", help="Optional offline wheelhouse.")
    build.add_argument("--checksum", action="store_true", help="Write a .sha256 file for the ZIP.")
    build.set_defaults(func=_build_magisk)

    source = sub.add_parser("build-source", help="Create a source tarball.")
    source.add_argument("--version", default="dev", help="Version label to embed in the archive name.")
    source.add_argument("--output", type=Path, default=None, help="Optional output tar.gz path.")
    source.add_argument("--checksum", action="store_true", help="Write a .sha256 file for the archive.")
    source.set_defaults(func=_build_source_archive)

    install = sub.add_parser("install-editable", help="Install the CLI into the current Python environment with pip -e.")
    install.add_argument("--with-dev", action="store_true", help="Install developer extras too.")
    install.set_defaults(func=_install_editable)

    bootstrap = sub.add_parser("bootstrap-dev", help="Install editable package plus developer tooling.")
    bootstrap.set_defaults(func=_bootstrap_dev)

    lint = sub.add_parser("lint", help="Run Ruff.")
    lint.set_defaults(func=_lint)

    typing = sub.add_parser("typecheck", help="Run mypy.")
    typing.set_defaults(func=_typecheck)

    tests = sub.add_parser("test", help="Run pytest.")
    tests.add_argument("pytest_args", nargs="*", help="Extra pytest arguments.")
    tests.set_defaults(func=_test)

    doctor = sub.add_parser("doctor-cross-arch", help="Check whether foreign-arch execution can continue past extract on this host.")
    doctor.add_argument("--arch", dest="arches", action="append", default=["arm64"], help="Target architecture to probe. Repeat as needed.")
    doctor.set_defaults(func=_doctor_cross_arch)

    e2e = sub.add_parser("e2e", help="Run the Playwright browser suite.")
    e2e.add_argument("--runner", default="npx", help="Command used to launch Playwright, usually npx.")
    e2e.add_argument("e2e_args", nargs=argparse.REMAINDER, help="Extra arguments forwarded to playwright test after --.")
    e2e.set_defaults(func=_e2e, runner_args=[])

    release = sub.add_parser("release", help="Run lint, typecheck, tests, and build release artifacts with checksums.")
    release.add_argument("--version", default="dev", help="Version label for release artifact names.")
    release.add_argument("--wheelhouse", type=Path, default=ROOT / "wheelhouse", help="Optional offline wheelhouse.")
    release.add_argument("--source-archive", type=Path, default=None, help="Optional source archive output path.")
    release.set_defaults(func=_release)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
