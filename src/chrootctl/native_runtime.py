from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

# GO12 runtime identity. Validators intentionally retain schema-v1 support for
# already-installed Python/Nuitka modules until the compatibility transition is
# sealed in later phases.
NATIVE_RUNTIME_SCHEMA_VERSION = 2
NATIVE_RUNTIME_KIND = "go-native"
LEGACY_NATIVE_RUNTIME_SCHEMA_VERSION = 1
LEGACY_NATIVE_RUNTIME_KIND = "nuitka-onefile"
NATIVE_RUNTIME_PLATFORM = "android"
DEFAULT_NATIVE_RUNTIME_ABI = "arm64-v8a"
DEFAULT_NATIVE_RUNTIME_ENTRYPOINT = "chrootctl"
DEFAULT_NATIVE_RUNTIME_BUILD_ROOT = Path("out/native-runtime")
SUPPORTED_ANDROID_MACHINES = {"aarch64": "arm64-v8a", "arm64": "arm64-v8a"}
TERMUX_PREFIX = Path("/data/data/com.termux/files/usr")
MAX_NATIVE_RUNTIME_FILE_BYTES = 128 * 1024 * 1024
MAX_NATIVE_RUNTIME_TOTAL_BYTES = 256 * 1024 * 1024
DEFAULT_ANDROID_API = 26
DEFAULT_ANDROID_NDK_VERSION = "29.0.14206865"


@dataclass(frozen=True, slots=True)
class NativeRuntimeBuildResult:
    artifact_dir: Path
    distribution_dir: Path
    entrypoint: Path
    manifest: Path
    command: tuple[str, ...]


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
    # Retained for source compatibility. GO12 can also build through an Android
    # NDK from a non-Termux host, so callers should prefer resolve_android_cc.
    if not is_native_termux_environment(environ=environ, machine=machine):
        raise RuntimeError("native Android runtime host is not native Termux")
    return detect_android_abi(machine=machine)


def go_android_build_command(*, repo_root: Path, output_binary: Path, go_executable: str = "go") -> tuple[str, ...]:
    repo_root = repo_root.expanduser().resolve()
    output_binary = output_binary.expanduser().resolve()
    if not (repo_root / "go.mod").is_file() or not (repo_root / "cmd/chrootctl").is_dir():
        raise FileNotFoundError("Go chrootctl source tree is incomplete")
    return (
        go_executable,
        "build",
        "-trimpath",
        "-tags",
        "android",
        "-o",
        str(output_binary),
        "./cmd/chrootctl",
    )


def _candidate_ndk_roots(env: Mapping[str, str], ndk_version: str) -> Sequence[Path]:
    values = [env.get("ANDROID_NDK_ROOT"), env.get("ANDROID_NDK_HOME")]
    for key in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        base = env.get(key)
        if base:
            values.append(str(Path(base) / "ndk" / ndk_version))
    return tuple(Path(v).expanduser() for v in values if v)


def resolve_android_cc(
    *,
    environ: Mapping[str, str] | None = None,
    api: int = DEFAULT_ANDROID_API,
    ndk_version: str = DEFAULT_ANDROID_NDK_VERSION,
) -> str:
    env = os.environ if environ is None else environ
    explicit = str(env.get("CHROOTCTL_ANDROID_CC") or "").strip()
    if explicit:
        path = Path(explicit)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError("CHROOTCTL_ANDROID_CC must name an executable absolute path")
        return str(path)
    prefix = str(env.get("PREFIX") or "").strip()
    if prefix.startswith("/data/data/com.termux/"):
        candidate = Path(prefix) / "bin/clang"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    termux = Path("/data/data/com.termux/files/usr/bin/clang")
    if termux.is_file() and os.access(termux, os.X_OK):
        return str(termux)
    name = f"aarch64-linux-android{api}-clang"
    for ndk in _candidate_ndk_roots(env, ndk_version):
        prebuilt = ndk / "toolchains/llvm/prebuilt"
        if not prebuilt.is_dir():
            continue
        for candidate in sorted(prebuilt.glob(f"*/bin/{name}")):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    raise RuntimeError(
        f"no Android arm64 C compiler found; set CHROOTCTL_ANDROID_CC or install Android NDK {ndk_version}"
    )


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
        files.append({
            "path": relative,
            "size": size,
            "sha256": _sha256(path),
            "executable": bool(path.stat().st_mode & 0o111),
        })
    return files


def write_native_runtime_manifest(
    artifact_dir: Path,
    *,
    abi: str,
    package_version: str,
    bridge_protocol_version: int,
    compiler_version: str | None = None,
    nuitka_version: str | None = None,
    schema_version: int = NATIVE_RUNTIME_SCHEMA_VERSION,
    runtime_kind: str = NATIVE_RUNTIME_KIND,
) -> Path:
    expanded = artifact_dir.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"native runtime artifact directory must not be symlinked: {expanded}")
    artifact_dir = expanded.resolve()
    entrypoint = artifact_dir / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
    if not entrypoint.is_file() or entrypoint.is_symlink():
        raise FileNotFoundError(f"native runtime entrypoint is missing or unsafe: {entrypoint}")
    if entrypoint.read_bytes()[:4] != b"\x7fELF":
        raise ValueError("native runtime entrypoint is not an ELF executable")
    _normalize_runtime_permissions(artifact_dir)
    compiler = compiler_version or nuitka_version or "unknown"
    if schema_version == LEGACY_NATIVE_RUNTIME_SCHEMA_VERSION:
        payload: dict[str, object] = {
            "schemaVersion": schema_version,
            "runtimeKind": LEGACY_NATIVE_RUNTIME_KIND if runtime_kind == NATIVE_RUNTIME_KIND else runtime_kind,
            "platform": NATIVE_RUNTIME_PLATFORM,
            "abi": abi,
            "entrypoint": DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
            "pythonPackageVersion": package_version,
            "bridgeProtocolVersion": bridge_protocol_version,
            "compiler": {"name": "Nuitka", "version": compiler},
            "files": _runtime_file_inventory(artifact_dir),
        }
    else:
        payload = {
            "schemaVersion": NATIVE_RUNTIME_SCHEMA_VERSION,
            "runtimeKind": NATIVE_RUNTIME_KIND,
            "platform": NATIVE_RUNTIME_PLATFORM,
            "abi": abi,
            "entrypoint": DEFAULT_NATIVE_RUNTIME_ENTRYPOINT,
            "backendVersion": package_version,
            "bridgeProtocolVersion": bridge_protocol_version,
            "compiler": {"name": "Go", "version": compiler},
            "files": _runtime_file_inventory(artifact_dir),
        }
    manifest = artifact_dir / "runtime-manifest.json"
    fd, tmp_name = tempfile.mkstemp(prefix=".runtime-manifest.", suffix=".json", dir=str(artifact_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp_name, manifest)
    finally:
        try: os.unlink(tmp_name)
        except FileNotFoundError: pass
    return manifest


def validate_native_runtime_artifact(
    artifact_dir: Path,
    *,
    expected_abi: str = DEFAULT_NATIVE_RUNTIME_ABI,
    package_version: str | None = None,
    bridge_protocol_version: int | None = None,
) -> dict[str, object]:
    expanded = artifact_dir.expanduser()
    if expanded.is_symlink() or not expanded.is_dir():
        raise NotADirectoryError(f"native runtime artifact must be a real directory: {expanded}")
    artifact_dir = expanded.resolve()
    manifest_path = artifact_dir / "runtime-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise FileNotFoundError(f"native runtime manifest is missing or unsafe: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("native runtime manifest must be a JSON object")
    schema = payload.get("schemaVersion")
    kind = payload.get("runtimeKind")
    if schema == NATIVE_RUNTIME_SCHEMA_VERSION:
        if kind != NATIVE_RUNTIME_KIND:
            raise ValueError("native runtime manifest runtimeKind mismatch")
        version_field = "backendVersion"
    elif schema == LEGACY_NATIVE_RUNTIME_SCHEMA_VERSION:
        if kind != LEGACY_NATIVE_RUNTIME_KIND:
            raise ValueError("legacy native runtime manifest runtimeKind mismatch")
        version_field = "pythonPackageVersion"
    else:
        raise ValueError(f"unsupported native runtime manifest schemaVersion: {schema!r}")
    for key, expected in {"platform": NATIVE_RUNTIME_PLATFORM, "abi": expected_abi, "entrypoint": DEFAULT_NATIVE_RUNTIME_ENTRYPOINT}.items():
        if payload.get(key) != expected:
            raise ValueError(f"native runtime manifest {key} mismatch: expected {expected!r}")
    if package_version is not None and payload.get(version_field) != package_version:
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
        missing = sorted(set(expected_entries) - set(actual_entries)); extra = sorted(set(actual_entries) - set(expected_entries))
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
    del python_executable, machine
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    repo_root = repo_root.expanduser().resolve()
    env = dict(os.environ if environ is None else environ)
    go = shutil.which("go", path=env.get("PATH"))
    if go is None:
        raise RuntimeError("Go is required to build the native Android runtime")
    cc = resolve_android_cc(environ=env)
    abi = DEFAULT_NATIVE_RUNTIME_ABI
    expanded_root = (output_root or (repo_root / DEFAULT_NATIVE_RUNTIME_BUILD_ROOT)).expanduser()
    if expanded_root.is_symlink():
        raise ValueError("native runtime output root must not be symlinked")
    root = expanded_root.resolve(); root.mkdir(parents=True, exist_ok=True)
    final_dir = root / abi
    with tempfile.TemporaryDirectory(prefix="chrootctl-go-native-", dir=str(root)) as tmp:
        stage = Path(tmp) / abi; stage.mkdir(parents=True)
        entrypoint = stage / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
        command = go_android_build_command(repo_root=repo_root, output_binary=entrypoint, go_executable=go)
        build_env = env.copy(); build_env.update({"GOOS": "android", "GOARCH": "arm64", "CGO_ENABLED": "1", "CC": cc, "GOMAXPROCS": str(jobs)})
        completed = subprocess.run(command, cwd=repo_root, env=build_env, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"Go native Android runtime build failed with exit {completed.returncode}")
        if not entrypoint.is_file() or entrypoint.is_symlink() or entrypoint.read_bytes()[:4] != b"\x7fELF":
            raise RuntimeError("Go build did not produce a safe Android ELF entrypoint")
        entrypoint.chmod(0o755)
        version_completed = subprocess.run([go, "version"], cwd=repo_root, env=env, check=False, text=True, capture_output=True)
        go_version = version_completed.stdout.strip() if version_completed.returncode == 0 else "unknown"
        manifest = write_native_runtime_manifest(stage, abi=abi, package_version=_package_version(repo_root), bridge_protocol_version=_bridge_protocol_version(repo_root), compiler_version=go_version)
        validate_native_runtime_artifact(stage, expected_abi=abi, package_version=_package_version(repo_root), bridge_protocol_version=_bridge_protocol_version(repo_root))
        if final_dir.exists():
            if final_dir.is_symlink() or not final_dir.is_dir():
                raise ValueError(f"refusing unsafe existing native runtime destination: {final_dir}")
            shutil.rmtree(final_dir)
        shutil.copytree(stage, final_dir, symlinks=False)
    return NativeRuntimeBuildResult(artifact_dir=final_dir, distribution_dir=final_dir, entrypoint=final_dir / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT, manifest=final_dir / "runtime-manifest.json", command=command)


def _package_version(repo_root: Path) -> str:
    import re
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
    if match is None: raise ValueError("unable to resolve chrootctl package version from pyproject.toml")
    return match.group(1)


def _bridge_protocol_version(repo_root: Path) -> int:
    import re
    text = (repo_root / "src/chrootctl/magisk.py").read_text(encoding="utf-8")
    match = re.search(r"(?m)^BRIDGE_PROTOCOL_VERSION\s*=\s*(\d+)\s*$", text)
    if match is None: raise ValueError("unable to resolve bridge protocol version from magisk.py")
    return int(match.group(1))
