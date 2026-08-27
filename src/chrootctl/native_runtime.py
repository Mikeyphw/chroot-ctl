from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version as distribution_version
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

NATIVE_RUNTIME_SCHEMA_VERSION = 1
NATIVE_RUNTIME_KIND = "nuitka-standalone"
NATIVE_RUNTIME_PLATFORM = "android"
DEFAULT_NATIVE_RUNTIME_ABI = "arm64-v8a"
DEFAULT_NATIVE_RUNTIME_ENTRYPOINT = "chrootctl.dist/chrootctl-native-entry"
DEFAULT_NATIVE_RUNTIME_BUILD_ROOT = Path("out/native-runtime")
DEFAULT_NATIVE_ONEFILE_EXPERIMENT_ROOT = Path("out/native-runtime-onefile")
DEFAULT_NATIVE_ONEFILE_EXPERIMENT_NAME = "chrootctl-onefile"
NUITKA_STANDALONE_OUTPUT_NAME = "chrootctl-native-entry"
SUPPORTED_ANDROID_MACHINES = {
    "aarch64": "arm64-v8a",
    "arm64": "arm64-v8a",
}
TERMUX_PREFIX = Path("/data/data/com.termux/files/usr")
REQUIRED_TERMUX_TOOLS = ("clang", "patchelf", "ccache", "ld", "ldd", "termux-elf-cleaner")
MAX_NATIVE_RUNTIME_FILE_BYTES = 96 * 1024 * 1024
MAX_NATIVE_RUNTIME_TOTAL_BYTES = 384 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class NativeRuntimeBuildResult:
    artifact_dir: Path
    distribution_dir: Path
    entrypoint: Path
    manifest: Path
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NativeOnefileExperimentPlan:
    output_root: Path
    output_binary: Path
    command: tuple[str, ...]
    warning: str = (
        "Nuitka onefile is experimental for Magisk/KSU because it extracts an internal runtime before execution; "
        "do not package it until it has an equivalent integrity seal to the standalone runtime manifest."
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(path: Path, root: Path) -> Path:
    relative = path.relative_to(root)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"unsafe native runtime path: {relative}")
    return relative


def detect_android_abi(*, machine: str | None = None) -> str:
    value = (machine or platform.machine()).strip().lower()
    try:
        return SUPPORTED_ANDROID_MACHINES[value]
    except KeyError as exc:
        raise RuntimeError(f"unsupported Android host architecture for native chrootctl runtime: {value or 'unknown'}") from exc


def is_native_termux_environment(*, environ: Mapping[str, str] | None = None, machine: str | None = None) -> bool:
    env = os.environ if environ is None else environ
    prefix = Path(env.get("PREFIX", "")).expanduser()
    machine_value = (machine or platform.machine()).strip().lower()
    return prefix == TERMUX_PREFIX and machine_value in SUPPORTED_ANDROID_MACHINES


def assert_native_termux_build_host(*, environ: Mapping[str, str] | None = None, machine: str | None = None) -> str:
    if not is_native_termux_environment(environ=environ, machine=machine):
        raise RuntimeError(
            "native Android runtime builds must run under native Termux on Android; "
            "building inside a glibc chroot would produce an incompatible runtime"
        )
    return detect_android_abi(machine=machine)


def nuitka_command(
    *,
    repo_root: Path,
    output_dir: Path,
    jobs: int = 2,
    python_executable: str | None = None,
) -> tuple[str, ...]:
    repo_root = repo_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    entry_script = repo_root / "scripts/chrootctl-native-entry.py"
    if not entry_script.is_file() or entry_script.is_symlink():
        raise FileNotFoundError(f"missing safe native runtime entry script: {entry_script}")
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    python = python_executable or sys.executable
    return (
        python,
        "-m",
        "nuitka",
        "--mode=standalone",
        "--clang",
        f"--jobs={jobs}",
        "--remove-output",
        "--noinclude-dlls=[vdso]",
        "--noinclude-dlls=linux-vdso*",
        "--noinclude-dlls=*vdso*",
        "--include-package=chrootctl",
        "--include-package-data=chrootctl",
        f"--output-filename={NUITKA_STANDALONE_OUTPUT_NAME}",
        f"--output-dir={output_dir}",
        str(entry_script),
    )


def nuitka_onefile_experiment_command(
    *,
    repo_root: Path,
    output_dir: Path,
    jobs: int = 2,
    python_executable: str | None = None,
) -> tuple[str, ...]:
    repo_root = repo_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    entry_script = repo_root / "scripts/chrootctl-native-entry.py"
    if not entry_script.is_file() or entry_script.is_symlink():
        raise FileNotFoundError(f"missing safe native runtime entry script: {entry_script}")
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    python = python_executable or sys.executable
    return (
        python,
        "-m",
        "nuitka",
        "--mode=onefile",
        "--clang",
        f"--jobs={jobs}",
        "--remove-output",
        "--noinclude-dlls=[vdso]",
        "--noinclude-dlls=linux-vdso*",
        "--noinclude-dlls=*vdso*",
        "--include-package=chrootctl",
        "--include-package-data=chrootctl",
        f"--output-filename={DEFAULT_NATIVE_ONEFILE_EXPERIMENT_NAME}",
        f"--output-dir={output_dir}",
        str(entry_script),
    )


def native_onefile_experiment_plan(
    repo_root: Path,
    *,
    output_root: Path | None = None,
    jobs: int = 2,
    python_executable: str | None = None,
) -> NativeOnefileExperimentPlan:
    repo_root = repo_root.expanduser().resolve()
    expanded_root = (output_root or (repo_root / DEFAULT_NATIVE_ONEFILE_EXPERIMENT_ROOT)).expanduser()
    if expanded_root.is_symlink():
        raise ValueError("native onefile experiment output root must not be symlinked")
    output_root = expanded_root.resolve()
    command = nuitka_onefile_experiment_command(
        repo_root=repo_root,
        output_dir=output_root,
        jobs=jobs,
        python_executable=python_executable,
    )
    return NativeOnefileExperimentPlan(
        output_root=output_root,
        output_binary=output_root / DEFAULT_NATIVE_ONEFILE_EXPERIMENT_NAME,
        command=command,
    )


def _find_nuitka_distribution(stage_root: Path) -> Path:
    candidates = sorted(path for path in stage_root.glob("*.dist") if path.is_dir() and not path.is_symlink())
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one Nuitka standalone distribution, found {len(candidates)}")
    return candidates[0]


def _normalize_entrypoint(distribution_dir: Path) -> Path:
    exact = distribution_dir / NUITKA_STANDALONE_OUTPUT_NAME
    candidates: list[Path] = []

    if exact.is_file() and not exact.is_symlink():
        candidates.append(exact)

    candidates.extend(
        path
        for path in sorted(distribution_dir.iterdir())
        if path.is_file()
        and not path.is_symlink()
        and path.name in {
            NUITKA_STANDALONE_OUTPUT_NAME,
            f"{NUITKA_STANDALONE_OUTPUT_NAME}.bin",
        }
    )

    deduped = list(dict.fromkeys(candidates))
    if len(deduped) != 1:
        raise RuntimeError("unable to identify a unique Nuitka chrootctl entrypoint")

    source = deduped[0]
    if source != exact:
        if exact.exists():
            raise RuntimeError(f"refusing to replace unexpected native entrypoint: {exact}")
        source.rename(exact)

    exact.chmod(exact.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return exact

def _normalize_runtime_permissions(artifact_dir: Path) -> None:
    entrypoint = artifact_dir / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
    for path in sorted(artifact_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlinks are not allowed in native runtime artifacts: {path}")
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o755 if path == entrypoint else 0o644)
        else:
            raise ValueError(f"non-regular native runtime entry: {path}")


def _runtime_file_inventory(artifact_dir: Path) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    total = 0
    for path in sorted(artifact_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlinks are not allowed in native runtime artifacts: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"non-regular native runtime entry: {path}")
        relative = _safe_relative(path, artifact_dir).as_posix()
        if relative == "runtime-manifest.json":
            continue
        size = path.stat().st_size
        if size > MAX_NATIVE_RUNTIME_FILE_BYTES:
            raise ValueError(f"native runtime file exceeds size limit: {relative}")
        total += size
        if total > MAX_NATIVE_RUNTIME_TOTAL_BYTES:
            raise ValueError("native runtime exceeds total size limit")
        files.append(
            {
                "path": relative,
                "size": size,
                "sha256": _sha256(path),
                "executable": bool(path.stat().st_mode & 0o111),
            }
        )
    return files


def write_native_runtime_manifest(
    artifact_dir: Path,
    *,
    abi: str,
    package_version: str,
    bridge_protocol_version: int,
    nuitka_version: str,
) -> Path:
    expanded_artifact_dir = artifact_dir.expanduser()
    if expanded_artifact_dir.is_symlink():
        raise ValueError(f"native runtime artifact directory must not be symlinked: {expanded_artifact_dir}")
    artifact_dir = expanded_artifact_dir.resolve()
    entrypoint = artifact_dir / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
    if not entrypoint.is_file() or entrypoint.is_symlink():
        raise FileNotFoundError(f"native runtime entrypoint is missing or unsafe: {entrypoint}")
    if entrypoint.read_bytes()[:4] != b"\x7fELF":
        raise ValueError("native runtime entrypoint is not an ELF executable")
    _normalize_runtime_permissions(artifact_dir)
    payload = {
        "schemaVersion": NATIVE_RUNTIME_SCHEMA_VERSION,
        "runtimeKind": NATIVE_RUNTIME_KIND,
        "platform": NATIVE_RUNTIME_PLATFORM,
        "abi": abi,
        "entrypoint": DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
        "pythonPackageVersion": package_version,
        "bridgeProtocolVersion": bridge_protocol_version,
        "compiler": {"name": "Nuitka", "version": nuitka_version},
        "files": _runtime_file_inventory(artifact_dir),
    }
    manifest = artifact_dir / "runtime-manifest.json"
    fd, tmp_name = tempfile.mkstemp(prefix=".runtime-manifest.", suffix=".json", dir=str(artifact_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, manifest)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return manifest


def validate_native_runtime_artifact(
    artifact_dir: Path,
    *,
    expected_abi: str = DEFAULT_NATIVE_RUNTIME_ABI,
    package_version: str | None = None,
    bridge_protocol_version: int | None = None,
) -> dict[str, object]:
    expanded_artifact_dir = artifact_dir.expanduser()
    if expanded_artifact_dir.is_symlink() or not expanded_artifact_dir.is_dir():
        raise NotADirectoryError(f"native runtime artifact must be a real directory: {expanded_artifact_dir}")
    artifact_dir = expanded_artifact_dir.resolve()
    manifest_path = artifact_dir / "runtime-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise FileNotFoundError(f"native runtime manifest is missing or unsafe: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("native runtime manifest must be a JSON object")
    expected_pairs = {
        "schemaVersion": NATIVE_RUNTIME_SCHEMA_VERSION,
        "runtimeKind": NATIVE_RUNTIME_KIND,
        "platform": NATIVE_RUNTIME_PLATFORM,
        "abi": expected_abi,
        "entrypoint": DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
    }
    for key, expected in expected_pairs.items():
        if payload.get(key) != expected:
            raise ValueError(f"native runtime manifest {key} mismatch: expected {expected!r}")
    if package_version is not None and payload.get("pythonPackageVersion") != package_version:
        raise ValueError("native runtime package version does not match this chrootctl release")
    if bridge_protocol_version is not None and payload.get("bridgeProtocolVersion") != bridge_protocol_version:
        raise ValueError("native runtime bridge protocol does not match this chrootctl release")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("native runtime manifest file inventory is missing")
    expected_entries: dict[str, dict[str, object]] = {}
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ValueError("native runtime manifest contains an invalid file entry")
        relative = Path(str(raw.get("path") or ""))
        if relative.as_posix() == "runtime-manifest.json":
            raise ValueError("native runtime manifest must not inventory itself")
        _safe_relative(artifact_dir / relative, artifact_dir)
        key = relative.as_posix()
        if key in expected_entries:
            raise ValueError(f"native runtime manifest contains duplicate file entry: {key}")
        expected_entries[key] = raw
    actual_entries = {entry["path"]: entry for entry in _runtime_file_inventory(artifact_dir)}
    if set(actual_entries) != set(expected_entries):
        missing = sorted(set(expected_entries) - set(actual_entries))
        extra = sorted(set(actual_entries) - set(expected_entries))
        raise ValueError(f"native runtime file inventory mismatch; missing={missing}, extra={extra}")
    for relative, expected in expected_entries.items():
        actual = actual_entries[relative]
        for key in ("size", "sha256", "executable"):
            if expected.get(key) != actual.get(key):
                raise ValueError(f"native runtime integrity mismatch for {relative}: {key}")
    entrypoint = artifact_dir / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
    if not entrypoint.is_file() or entrypoint.is_symlink() or entrypoint.stat().st_mode & 0o111 == 0:
        raise PermissionError("native runtime entrypoint must be a regular executable")
    if entrypoint.read_bytes()[:4] != b"\x7fELF":
        raise ValueError("native runtime entrypoint is not an ELF executable")
    return payload


def build_native_android_runtime(
    repo_root: Path,
    *,
    output_root: Path | None = None,
    jobs: int = 2,
    python_executable: str | None = None,
    environ: Mapping[str, str] | None = None,
    machine: str | None = None,
) -> NativeRuntimeBuildResult:
    repo_root = repo_root.expanduser().resolve()
    abi = assert_native_termux_build_host(environ=environ, machine=machine)
    env = dict(os.environ if environ is None else environ)
    missing_tools = [name for name in REQUIRED_TERMUX_TOOLS if shutil.which(name, path=env.get("PATH")) is None]
    if missing_tools:
        raise RuntimeError("missing native Termux build tools: " + ", ".join(missing_tools))
    try:
        nuitka_version = distribution_version("Nuitka")
    except PackageNotFoundError as exc:
        raise RuntimeError("Nuitka is required; install it in the active Python environment before building") from exc

    expanded_root = (output_root or (repo_root / DEFAULT_NATIVE_RUNTIME_BUILD_ROOT)).expanduser()
    if expanded_root.is_symlink():
        raise ValueError("native runtime output root must not be symlinked")
    root = expanded_root.resolve()
    final_dir = root / abi
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chrootctl-nuitka-", dir=str(root)) as tmp:
        stage_root = Path(tmp)
        command = nuitka_command(repo_root=repo_root, output_dir=stage_root, jobs=jobs, python_executable=python_executable)
        build_env = env.copy()
        source_root = str(repo_root / "src")
        build_env["PYTHONPATH"] = source_root if not build_env.get("PYTHONPATH") else f"{source_root}:{build_env['PYTHONPATH']}"
        completed = subprocess.run(command, cwd=repo_root, env=build_env, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"Nuitka native runtime build failed with exit {completed.returncode}")
        distribution = _find_nuitka_distribution(stage_root)
        normalized = stage_root / "chrootctl.dist"
        distribution.rename(normalized)
        _normalize_entrypoint(normalized)
        artifact_stage = stage_root / abi
        artifact_stage.mkdir()
        normalized.rename(artifact_stage / normalized.name)
        manifest = write_native_runtime_manifest(
            artifact_stage,
            abi=abi,
            package_version=_package_version(repo_root),
            bridge_protocol_version=_bridge_protocol_version(repo_root),
            nuitka_version=nuitka_version,
        )
        validate_native_runtime_artifact(
            artifact_stage,
            expected_abi=abi,
            package_version=_package_version(repo_root),
            bridge_protocol_version=_bridge_protocol_version(repo_root),
        )
        if final_dir.exists():
            if final_dir.is_symlink() or not final_dir.is_dir():
                raise ValueError(f"refusing unsafe existing native runtime destination: {final_dir}")
            shutil.rmtree(final_dir)
        shutil.copytree(artifact_stage, final_dir, symlinks=False)
    final_manifest = final_dir / manifest.name
    final_entrypoint = final_dir / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
    return NativeRuntimeBuildResult(
        artifact_dir=final_dir,
        distribution_dir=final_dir / "chrootctl.dist",
        entrypoint=final_entrypoint,
        manifest=final_manifest,
        command=command,
    )


def _package_version(repo_root: Path) -> str:
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    import re

    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
    if match is None:
        raise ValueError("unable to resolve chrootctl package version from pyproject.toml")
    return match.group(1)


def _bridge_protocol_version(repo_root: Path) -> int:
    text = (repo_root / "src/chrootctl/magisk.py").read_text(encoding="utf-8")
    import re

    match = re.search(r"(?m)^BRIDGE_PROTOCOL_VERSION\s*=\s*(\d+)\s*$", text)
    if match is None:
        raise ValueError("unable to resolve bridge protocol version from magisk.py")
    return int(match.group(1))
