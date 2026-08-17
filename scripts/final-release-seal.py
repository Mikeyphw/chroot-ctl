#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import ast
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - exercised on supported Python 3.10 hosts
    tomllib = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
ANDROID_DIR = ROOT / "android"
MANIFEST = ROOT / "docs/release/compatibility-manifest.json"
PYPROJECT = ROOT / "pyproject.toml"
CHECKS: tuple[tuple[str, str], ...] = (
    ("python_pytest", "Python pytest"),
    ("python_mypy", "Python mypy"),
    ("python_compileall", "Python compileall"),
    ("android_contract_validators", "Android source-contract validators"),
    ("source_package", "Source package validator"),
    ("android_compileDebugKotlin", "Android compileDebugKotlin"),
    ("android_testDebugUnitTest", "Android testDebugUnitTest"),
    ("android_lintDebug", "Android lintDebug"),
    ("module_render", "Module render/tree validator"),
    ("module_zip", "Module ZIP validator"),
    ("module_shell", "Module shell contract"),
    ("source_no_webui", "Retired WebUI regression scan"),
)
CHECK_IDS = tuple(item[0] for item in CHECKS)
_ALLOWED_PROVENANCE = {"subprocess", "deduplicated-subprocess"}
EXPECTED_CHANGED_PATHS = frozenset((
    'android/app/build.gradle.kts',
    'android/app/src/main/kotlin/com/mikeyphw/chrootctl/MainActivity.kt',
    'android/app/src/main/kotlin/com/mikeyphw/chrootctl/operations/ChrootOperationService.kt',
    'android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt',
    'android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/home/HomeScreen.kt',
    'android/app/src/main/res/values/strings.xml',
    'android/gradle/libs.versions.toml',
    'android/gradle/wrapper/gradle-wrapper.properties',
    'docs/android/PHASE_22_RELEASE_HARDENING.md',
    'docs/android/PHASE_29D_RUNTIME_BOOTSTRAP_AND_RESPONSIVE_ACTIONS.md',
    'docs/android/PHASE_29F_BINDER_DEATH_RECOVERY.md',
    'docs/android/PHASE_34B_ROOTSERVICE_STREAM_CRASH_HOTFIX.md',
    'docs/android/PHASE_41_42_UI_QUALITY_REAL_DEVICE_SMOKE.md',
    'docs/release/VALIDATION_EVIDENCE.md',
    'scripts/final-release-seal.py',
    'scripts/record-validation-evidence.py',
    'scripts/validate-android-phase08-10.py',
    'scripts/validate-android-phase11-13.py',
    'scripts/validate-android-phase14-15.py',
    'scripts/validate-android-phase16-17.py',
    'scripts/validate-android-phase18-19.py',
    'scripts/validate-android-phase20-21.py',
    'scripts/validate-android-phase22.py',
    'scripts/validate-android-phase23.py',
    'scripts/validate-android-phase24.py',
    'scripts/validate-android-phase25.py',
    'scripts/validate-android-phase26.py',
    'scripts/validate-android-phase27.py',
    'scripts/validate-android-phase28.py',
    'scripts/validate-android-phase29.py',
    'scripts/validate-android-phase29c.py',
    'scripts/validate-android-phase29d.py',
    'scripts/validate-android-phase29f.py',
    'scripts/validate-android-phase30-31.py',
    'scripts/validate-android-phase32.py',
    'scripts/validate-android-phase33.py',
    'scripts/validate-android-phase34.py',
    'scripts/validate-android-phase34b.py',
    'scripts/validate-android-phase34c.py',
    'scripts/validate-android-phase34d.py',
    'scripts/validate-android-phase35-36.py',
    'scripts/validate-android-phase38.py',
    'scripts/validate-android-phase39-40.py',
    'scripts/validate-android-phase41-42.py',
    'scripts/validate-final-release-seal.sh',
    'src/chrootctl/base_install.py',
    'src/chrootctl/bridge/cli.py',
    'src/chrootctl/bridge/registry.py',
    'src/chrootctl/services/install.py',
    'src/chrootctl/services/release_readiness.py',
    'src/chrootctl/user_sync.py',
    'tests/test_android_phase14_15.py',
    'tests/test_android_phase16_17.py',
    'tests/test_android_phase18_19.py',
    'tests/test_android_phase20_21.py',
    'tests/test_android_phase22.py',
    'tests/test_android_phase23.py',
    'tests/test_android_phase24.py',
    'tests/test_android_phase25.py',
    'tests/test_android_phase26.py',
    'tests/test_android_phase27.py',
    'tests/test_android_phase28.py',
    'tests/test_android_phase29.py',
    'tests/test_android_phase29c.py',
    'tests/test_android_phase29d.py',
    'tests/test_android_phase29f.py',
    'tests/test_android_phase30_31.py',
    'tests/test_android_phase32.py',
    'tests/test_android_phase33.py',
    'tests/test_android_phase34.py',
    'tests/test_android_phase34b.py',
    'tests/test_android_phase34c.py',
    'tests/test_android_phase34d.py',
    'tests/test_android_phase39_40.py',
    'tests/test_catalog.py',
    'tests/test_chroot_users.py',
    'tests/test_cli.py',
    'tests/test_controller.py',
    'tests/test_host_clipboard.py',
    'tests/test_install_service.py',
    'tests/test_installers.py',
    'tests/test_overlay01_02_contracts.py',
    'tests/test_overlay05_android_state_contracts.py',
    'tests/test_overlay06_storage_transactions_contracts.py',
    'tests/test_overlay09_module_runtime_packaging_contracts.py',
    'tests/test_overlay10_support_readiness_contracts.py',
    'tests/test_overlay11_release_seal_contracts.py',
    'tests/test_runtime_chroots.py',
    'tests/test_runtime_clipboard.py',
    'tests/test_runtime_install.py',
    'tests/test_runtime_session.py',
    'tests/test_user_sync.py',
))
ANDROID_TASKS = (
    ":app:compileDebugKotlin",
    ":app:testDebugUnitTest",
    ":app:lintDebug",
)



def git(*args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def source_commit() -> str:
    return git("rev-parse", "HEAD")


def source_tree() -> str:
    return git("rev-parse", "HEAD^{tree}")


def validated_tree() -> str:
    """Hash tracked and non-ignored untracked worktree bytes without touching the real index."""
    fd, index_name = tempfile.mkstemp(prefix="chrootctl-final-seal-index-")
    os.close(fd)
    index = Path(index_name)
    try:
        index.unlink(missing_ok=True)
        env = dict(os.environ); env["GIT_INDEX_FILE"] = str(index)
        git("read-tree", "HEAD", env=env)
        git("add", "-A", "--", ".", env=env)
        tree = git("write-tree", env=env)
        if not _is_git_oid(tree):
            raise RuntimeError("git write-tree returned an invalid object id")
        return tree
    finally:
        index.unlink(missing_ok=True)


def _is_git_oid(value: object) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(ch in "0123456789abcdef" for ch in text)


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def compatibility_manifest_sha256() -> str:
    if not MANIFEST.is_file() or MANIFEST.is_symlink():
        raise RuntimeError("compatibility manifest is missing or unsafe")
    digest = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    if not _is_sha256(digest):
        raise RuntimeError("compatibility manifest SHA-256 is invalid")
    return digest


def default_evidence_paths() -> list[Path]:
    override = os.environ.get("CHROOTCTL_VALIDATION_RESULTS", "").strip()
    if override:
        return [Path(override).expanduser()]
    is_android = bool(os.environ.get("ANDROID_ROOT")) or Path("/system/bin/app_process").exists()
    if is_android:
        return [Path("/data/adb/chrootctl/validation-results.json")]
    state_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if state_home:
        return [Path(state_home).expanduser() / "chrootctl" / "validation-results.json"]
    return [Path.home() / ".local" / "share" / "chrootctl" / "validation-results.json"]


def _assert_no_symlink_components(path: Path) -> None:
    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if (current.exists() or current.is_symlink()) and current.is_symlink():
            raise RuntimeError(f"refusing symlink evidence path component: {current}")


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.expanduser().absolute()
    _assert_no_symlink_components(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _assert_no_symlink_components(path.parent)
    if path.is_symlink():
        raise RuntimeError(f"refusing symlink evidence path: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)
            handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(temp, path)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"evidence destination is not a regular file: {path}")
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try: os.fsync(dir_fd)
            finally: os.close(dir_fd)
        except OSError:
            pass
    finally:
        temp.unlink(missing_ok=True)


def _atomic_json_write_via_su(path: Path, payload: Mapping[str, Any]) -> None:
    su = shutil.which("su")
    if not su:
        raise RuntimeError(f"validation evidence requires root write access to {path}, but su is unavailable")
    fd, source_name = tempfile.mkstemp(prefix="chrootctl-validation-evidence-")
    source = Path(source_name)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)
            handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        parent = path.expanduser().absolute().parent; target = path.expanduser().absolute()
        script = "\n".join((
            "set -eu", f"parent={shlex.quote(str(parent))}", f"target={shlex.quote(str(target))}", f"source={shlex.quote(str(source))}",
            'cur="/"; oldifs="$IFS"; IFS="/"; for part in ${parent#/}; do [ -n "$part" ] || continue; cur="$cur$part"; [ ! -L "$cur" ] || { echo "refusing symlink evidence directory component: $cur" >&2; exit 1; }; cur="$cur/"; done; IFS="$oldifs"',
            'mkdir -p "$parent"', 'chmod 700 "$parent"',
            '[ ! -L "$target" ] || { echo "refusing symlink evidence path" >&2; exit 1; }',
            'tmp="$(mktemp "$parent/.validation-results.json.XXXXXX")"',
            "trap 'rm -f \"$tmp\"' EXIT INT TERM", 'cp "$source" "$tmp"', 'chmod 600 "$tmp"', 'mv -f "$tmp" "$target"',
            'trap - EXIT INT TERM', '[ ! -L "$target" ] && [ -f "$target" ] || { echo "unsafe evidence destination" >&2; exit 1; }', 'chmod 600 "$target"',
        ))
        result = subprocess.run([su, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "su evidence write failed")
    finally:
        source.unlink(missing_ok=True)


def _write_evidence(paths: Iterable[Path], payload: Mapping[str, Any]) -> list[Path]:
    written: list[Path] = []
    for raw_path in paths:
        path = raw_path.expanduser()
        try:
            _atomic_json_write(path, payload)
        except OSError as direct_error:
            if str(path).startswith("/data/adb/"):
                try: _atomic_json_write_via_su(path, payload)
                except RuntimeError as root_error:
                    raise RuntimeError(f"failed to write validation evidence to {path}: {direct_error}; root fallback: {root_error}") from root_error
            else:
                raise RuntimeError(f"failed to write validation evidence to {path}: {direct_error}") from direct_error
        written.append(path)
    if not written:
        raise RuntimeError("no validation-evidence destination")
    return written


def changed_paths() -> set[str]:
    tracked = git("diff", "--name-only", "HEAD", "--", ".").splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard", "--", ".").splitlines()
    return {item.strip() for item in [*tracked, *untracked] if item.strip()}


def assert_transaction_tree(
    label: str, *, source_commit: str, source_tree: str, expected_validated_tree: str
) -> None:
    if git("rev-parse", "HEAD") != source_commit:
        raise RuntimeError(f"{label}: HEAD changed during validation")
    if git("rev-parse", "HEAD^{tree}") != source_tree:
        raise RuntimeError(f"{label}: source commit tree changed during validation")
    # Keep the expected tree value distinct from the validated_tree() function.
    # A previous Overlay 11 build named this parameter ``validated_tree`` and
    # then attempted ``validated_tree()``, turning a tree-id string into a
    # callable and failing before any release gate could run.
    actual_tree = validated_tree()
    if actual_tree != expected_validated_tree:
        raise RuntimeError(
            f"{label}: validated worktree changed during validation: "
            f"{expected_validated_tree} -> {actual_tree}"
        )
    actual_paths = changed_paths()
    if actual_paths != EXPECTED_CHANGED_PATHS:
        missing = sorted(EXPECTED_CHANGED_PATHS - actual_paths)
        extra = sorted(actual_paths - EXPECTED_CHANGED_PATHS)
        raise RuntimeError(f"{label}: worktree is not the exact Overlay 11 tree; missing={missing} extra={extra}")


def q(argv: list[str]) -> str:
    return " ".join(shlex.quote(item) for item in argv)


def _fallback_toml_string_list(text: str, section: str, key: str) -> list[str]:
    """Read the simple string-array form used by this repo when Python 3.10 lacks tomllib."""
    active = ""
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        index += 1
        if stripped.startswith("[") and stripped.endswith("]"):
            active = stripped[1:-1].strip()
            continue
        if active != section or not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != key:
            continue
        value = value.strip()
        while value.count("[") > value.count("]") and index < len(lines):
            value += "\n" + lines[index].strip()
            index += 1
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise RuntimeError(f"cannot parse pyproject.toml {section}.{key} string list") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise RuntimeError(f"pyproject.toml {section}.{key} must be a string list")
        return parsed
    raise RuntimeError(f"pyproject.toml is missing {section}.{key}")


def declared_python_validation_requirements() -> tuple[str, ...]:
    """Return the repository-declared runtime + dev requirements for final validation."""
    if not PYPROJECT.is_file() or PYPROJECT.is_symlink():
        raise RuntimeError("pyproject.toml is missing or unsafe")
    try:
        text = PYPROJECT.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read pyproject.toml for validation dependencies: {exc}") from exc
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception as exc:
            raise RuntimeError(f"cannot parse pyproject.toml for validation dependencies: {exc}") from exc
        project = data.get("project")
        if not isinstance(project, dict):
            raise RuntimeError("pyproject.toml [project] table is missing")
        runtime = project.get("dependencies")
        optional = project.get("optional-dependencies")
        dev = optional.get("dev") if isinstance(optional, dict) else None
    else:
        runtime = _fallback_toml_string_list(text, "project", "dependencies")
        dev = _fallback_toml_string_list(text, "project.optional-dependencies", "dev")
    if not isinstance(runtime, list) or not runtime or not all(isinstance(item, str) and item.strip() for item in runtime):
        raise RuntimeError("pyproject.toml project.dependencies must be a non-empty string list")
    if not isinstance(dev, list) or not dev or not all(isinstance(item, str) and item.strip() for item in dev):
        raise RuntimeError("pyproject.toml project.optional-dependencies.dev must be a non-empty string list")
    requirements = tuple(dict.fromkeys(item.strip() for item in [*runtime, *dev]))
    lowered = "\n".join(requirements).lower()
    for required_name in ("pydantic", "pytest", "mypy"):
        if required_name not in lowered:
            raise RuntimeError(f"final validation dependency contract is missing {required_name}")
    return requirements


def validation_tmp_base() -> Path:
    """Resolve a temporary root that cannot live inside the validated Git checkout."""
    raw = os.environ.get("DEVTOOL_VALIDATION_TMPDIR") or os.environ.get("TMPDIR") or tempfile.gettempdir()
    candidate = Path(raw).expanduser().resolve(strict=False)
    repo_root = ROOT.resolve(strict=False)
    try:
        candidate.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise RuntimeError(f"Python validation temporary directory must be outside the Git checkout: {candidate}")
    return candidate


def prepare_python_validation_environment(
    tmp_base: Path, *, parent_env: dict[str, str], source_commit: str, source_tree: str, expected_validated_tree: str
) -> tuple[tempfile.TemporaryDirectory[str], Path, tuple[str, ...], dict[str, str]]:
    """Create an isolated dependency-complete Python validation environment outside the checkout."""
    requirements = declared_python_validation_requirements()
    holder: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory(
        prefix="chrootctl-final-python-env-", dir=tmp_base
    )
    try:
        venv_dir = Path(holder.name) / "venv"
        bootstrap_env = dict(parent_env)
        bootstrap_env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        bootstrap_env["PYTHONDONTWRITEBYTECODE"] = "1"
        run([sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir)], env=bootstrap_env)
        python_executable = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python_executable.is_file():
            raise RuntimeError(f"validation venv did not produce a Python interpreter: {python_executable}")
        run([
            str(python_executable), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *requirements
        ], env=bootstrap_env)
        run([
            str(python_executable), "-c",
            "import mypy, pydantic, pytest, rich, yaml; print('Overlay 11 Python validation environment ready')",
        ], env=bootstrap_env)
        assert_transaction_tree(
            "after Python validation environment preparation",
            source_commit=source_commit, source_tree=source_tree, expected_validated_tree=expected_validated_tree,
        )
        gate_env = dict(bootstrap_env)
        gate_env["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + gate_env["PYTHONPATH"] if gate_env.get("PYTHONPATH") else "")
        return holder, python_executable, requirements, gate_env
    except Exception:
        holder.cleanup()
        raise


def run(argv: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> tuple[float, float]:
    print(f"+ (cd {cwd} && {q(argv)})", flush=True)
    started = time.time()
    result = subprocess.run(argv, cwd=cwd, env=env, check=False)
    finished = time.time()
    if result.returncode != 0:
        raise RuntimeError(f"gate failed with exit code {result.returncode}: {q(argv)}")
    return started, finished


def pass_result(command: str, started: float, finished: float, detail: str, *, provenance: str = "subprocess", **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "status": "pass", "exitCode": 0, "command": command, "detail": detail,
        "provenance": provenance, "recordedAt": finished, "startedAt": started, "finishedAt": finished,
    }
    item.update(extra)
    return item


def clear_python_test_caches() -> None:
    """Remove only known ignored Python/pytest caches from inside the checkout."""
    candidates = sorted(
        (path for path in ROOT.rglob("*") if path.name in {"__pycache__", ".pytest_cache", ".mypy_cache"}),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in candidates:
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


def run_pytest_gate(python_executable: Path, env: dict[str, str], *, source_commit: str, source_tree: str, validated_tree: str) -> tuple[float, float, str]:
    """Run the complete test-file inventory in isolated deterministic partitions.

    The suite contains subprocess/runtime tests whose process-global state can make one
    giant pytest process order-sensitive.  Partitioning by sorted file inventory keeps
    every test in the release gate while giving each group a fresh interpreter.
    """
    test_files = sorted((ROOT / "tests").glob("test_*.py"))
    if not test_files:
        raise RuntimeError("Python regression gate collected no test files")
    partitions: list[list[Path]] = [[] for _ in range(4)]
    for index, path in enumerate(test_files):
        partitions[index % len(partitions)].append(path)
    flattened = [path for part in partitions for path in part]
    if len(flattened) != len(test_files) or set(flattened) != set(test_files):
        raise RuntimeError("Python regression partitioning lost or duplicated test files")

    clear_python_test_caches()
    gate_started = time.time()
    commands: list[str] = []
    for index, partition in enumerate(partitions, 1):
        argv = [str(python_executable), "-m", "pytest", "-q", "-p", "no:cacheprovider", *[str(path.relative_to(ROOT)) for path in partition]]
        print(f"Python regression partition {index}/{len(partitions)} ({len(partition)} files)", flush=True)
        run(argv, env=env)
        assert_transaction_tree(
            f"after Python regression partition {index}",
            source_commit=source_commit,
            source_tree=source_tree,
            expected_validated_tree=validated_tree,
        )
        clear_python_test_caches()
        commands.append(q(argv))
    gate_finished = time.time()
    return gate_started, gate_finished, " && ".join(commands)


def run_final_seal(*, run_id: str) -> dict[str, Any]:
    if not (ROOT / ".git").exists():
        raise RuntimeError("final release seal requires a Git checkout")
    if subprocess.run(["git", "-C", str(ROOT), "diff", "--cached", "--quiet"], check=False).returncode != 0:
        raise RuntimeError("final release seal refuses a pre-staged index")
    source_commit_id = source_commit()
    source_tree_id = source_tree()
    validated_tree_id = validated_tree()
    started_at = time.time()
    assert_transaction_tree("before gates", source_commit=source_commit_id, source_tree=source_tree_id, expected_validated_tree=validated_tree_id)

    results: dict[str, dict[str, Any]] = {}
    tmp_base = validation_tmp_base()
    tmp_base.mkdir(parents=True, exist_ok=True)
    base_env = dict(os.environ)
    base_env["PYTHONDONTWRITEBYTECODE"] = "1"
    python_env_holder, python_executable, python_requirements, env = prepare_python_validation_environment(
        tmp_base, parent_env=base_env, source_commit=source_commit_id, source_tree=source_tree_id,
        expected_validated_tree=validated_tree_id,
    )
    try:
        s, f, pytest_command = run_pytest_gate(
            python_executable, env, source_commit=source_commit_id, source_tree=source_tree_id, validated_tree=validated_tree_id
        )
        results["python_pytest"] = pass_result(
            pytest_command, s, f,
            "Full Python regression inventory passed in four isolated deterministic pytest partitions; every tests/test_*.py file ran exactly once.",
            pythonExecutable=str(python_executable), dependencyRequirements=list(python_requirements),
        )
        with tempfile.TemporaryDirectory(prefix="chrootctl-mypy-cache-") as mypy_cache:
            s, f = run([str(python_executable), "-m", "mypy", "--cache-dir", mypy_cache, "src"], env=env)
        results["python_mypy"] = pass_result("python3 -m mypy --cache-dir <tmp> src", s, f, "Python type gate passed without mutating the validated repository tree.")
        s, f = run([str(python_executable), "-m", "compileall", "-q", "src"], env=env)
        results["python_compileall"] = pass_result("python3 -m compileall -q src", s, f, "Python source byte-compilation gate passed.")

        validators = sorted((ROOT / "scripts").glob("validate-android-phase*.py"))
        if not validators:
            raise RuntimeError("no Android phase validators were collected")
        validator_start = time.time(); retired_result: tuple[float, float, str] | None = None
        for validator in validators:
            command = [str(python_executable), str(validator.relative_to(ROOT))]
            s, f = run(command, env=env)
            if validator.name == "validate-android-phase20-21.py":
                retired_result = (s, f, q(command))
        validator_finish = time.time()
        results["android_contract_validators"] = pass_result(
            "for validator in scripts/validate-android-phase*.py; do python3 $validator; done",
            validator_start, validator_finish, f"{len(validators)} Android source-contract validators passed exactly once."
        )
        if retired_result is None:
            raise RuntimeError("retired WebUI phase20-21 validator was not collected")
        rs, rf, rcmd = retired_result
        results["source_no_webui"] = pass_result(
            rcmd, rs, rf, "Retired WebUI scan passed as the phase20-21 member of the one-pass Android validator set.",
            provenance="deduplicated-subprocess", derivedFrom="android_contract_validators"
        )

        with tempfile.TemporaryDirectory(prefix="chrootctl-final-seal-", dir=tmp_base) as temp_name:
            temp = Path(temp_name)
            source_archive = temp / "chrootctl-final-seal.tar.gz"
            cmd = [str(python_executable), "manage_source.py", "build-source", "--version", "final-seal", "--output", str(source_archive), "--checksum"]
            s, f = run(cmd, env=env)
            if not source_archive.is_file() or source_archive.stat().st_size == 0:
                raise RuntimeError("source package gate did not produce a non-empty archive")
            results["source_package"] = pass_result("python3 manage_source.py build-source --version final-seal --output <tmp>/chrootctl-final-seal.tar.gz --checksum", s, f, "Source package build/checksum gate passed.")

            # Never trust an environment flag or a prior caller's claim that Android
            # already passed.  Devtool's manifest-driven tasks remain an outer gate,
            # while the evidence-producing seal independently executes the exact same
            # required task set against the still-verified Overlay 11 worktree.
            gradle = ["./gradlew", *ANDROID_TASKS]
            s, f = run(gradle, cwd=ANDROID_DIR, env=env)
            for task, check_id in zip(ANDROID_TASKS, ("android_compileDebugKotlin", "android_testDebugUnitTest", "android_lintDebug")):
                results[check_id] = pass_result(
                    q(gradle), s, f,
                    f"Gradle task {task} completed in the evidence-producing final Android invocation.",
                    provenance="subprocess", task=task, target="chrootctl_android",
                )

            shell_start = time.time()
            run(["bash", "-n", "build.sh"], env=env)
            resource_shells = sorted((ROOT / "src/chrootctl/resources").rglob("*.sh"))
            for script in resource_shells:
                run(["bash", "-n", str(script.relative_to(ROOT))], env=env)
            shell_finish = time.time()
            results["module_shell"] = pass_result("bash -n build.sh && bash -n src/chrootctl/resources/**/*.sh", shell_start, shell_finish, f"Module source shell syntax passed for build.sh and {len(resource_shells)} resource scripts.")

            zip_a, zip_b = temp / "chrootctl-module-a.zip", temp / "chrootctl-module-b.zip"
            out_a, out_b = temp / "module-a", temp / "module-b"
            cmd_a = [str(python_executable), "manage_source.py", "build-magisk", "--output-dir", str(out_a), "--zip-path", str(zip_a), "--checksum"]
            cmd_b = [str(python_executable), "manage_source.py", "build-magisk", "--output-dir", str(out_b), "--zip-path", str(zip_b), "--checksum"]
            s1, f1 = run(cmd_a, env=env); s2, f2 = run(cmd_b, env=env)
            if not zip_a.is_file() or not zip_b.is_file():
                raise RuntimeError("module ZIP gate did not produce both archives")
            sha_a = hashlib.sha256(zip_a.read_bytes()).hexdigest(); sha_b = hashlib.sha256(zip_b.read_bytes()).hexdigest()
            if sha_a != sha_b:
                raise RuntimeError(f"deterministic module ZIP gate failed: {sha_a} != {sha_b}")
            rendered_shells = []
            for script in sorted(out_a.rglob("*")):
                if not script.is_file(): continue
                try: first = script.open("rb").readline(256)
                except OSError: continue
                if first.startswith(b"#!") and (b"sh" in first or b"bash" in first):
                    run(["bash", "-n", str(script)], env=env); rendered_shells.append(script)
            results["module_render"] = pass_result("python3 manage_source.py build-magisk <module-a> --checksum", s1, f1, "Module render/tree validation passed.")
            results["module_zip"] = pass_result("python3 manage_source.py build-magisk twice + SHA-256 equality + rendered shell validation", s1, time.time(), f"Deep module ZIP validation passed; deterministic SHA-256={sha_a}; renderedShells={len(rendered_shells)}.", moduleSha256=sha_a)

        assert_transaction_tree("after gates", source_commit=source_commit_id, source_tree=source_tree_id, expected_validated_tree=validated_tree_id)
        completed_at = time.time()
        if set(results) != set(CHECK_IDS):
            missing = sorted(set(CHECK_IDS) - set(results)); extra = sorted(set(results) - set(CHECK_IDS))
            raise RuntimeError(f"validation result set mismatch; missing={missing} extra={extra}")
        if not _is_git_oid(source_commit_id) or not _is_git_oid(source_tree_id) or not _is_git_oid(validated_tree_id):
            raise RuntimeError("release evidence requires exact lowercase 40-hex Git object ids")
        if source_tree_id == validated_tree_id:
            raise RuntimeError("validatedTree unexpectedly equals sourceTree; Overlay 11 changes are not present")
        if not run_id.strip():
            raise RuntimeError("validationRunId is required")
        if not isinstance(started_at, (int, float)) or not isinstance(completed_at, (int, float)) or completed_at < started_at:
            raise RuntimeError("validation time range is invalid")
        checks: dict[str, dict[str, Any]] = {}
        for check_id in CHECK_IDS:
            item = dict(results[check_id])
            if item.get("status") != "pass" or item.get("exitCode") != 0:
                raise RuntimeError(f"refusing to record non-passing result for {check_id}")
            if str(item.get("provenance") or "") not in _ALLOWED_PROVENANCE:
                raise RuntimeError(f"passing result for {check_id} has invalid provenance")
            if not str(item.get("command") or "").strip():
                raise RuntimeError(f"passing result for {check_id} is missing command provenance")
            gate_started = item.get("startedAt"); gate_finished = item.get("finishedAt"); recorded_at = item.get("recordedAt")
            if not all(isinstance(value, (int, float)) for value in (gate_started, gate_finished, recorded_at)):
                raise RuntimeError(f"passing result for {check_id} is missing timing provenance")
            if not (started_at <= gate_started <= gate_finished <= completed_at and gate_finished <= recorded_at <= completed_at):
                raise RuntimeError(f"passing result for {check_id} has inconsistent timing provenance")
            if item.get("provenance") == "deduplicated-subprocess":
                parent = str(item.get("derivedFrom") or "")
                if parent not in CHECK_IDS or parent == check_id:
                    raise RuntimeError(f"deduplicated result for {check_id} has invalid derivedFrom provenance")
            checks[check_id] = item
        payload = {
            "schemaVersion": 2, "generatedAt": completed_at, "validationRunId": run_id,
            "validationStartedAt": started_at, "validationCompletedAt": completed_at,
            "sourceCommit": source_commit_id, "sourceTree": source_tree_id, "validatedTree": validated_tree_id,
            "compatibilityManifestSha256": compatibility_manifest_sha256(), "checks": checks,
        }
        # This is intentionally the only success-evidence assembly path. The legacy
        # recorder script is a hard-fail shim and exposes no payload builder/writer API.
        written = _write_evidence(default_evidence_paths(), payload)
        for path in written: print(f"validation evidence: {path}")
        print(f"source commit: {source_commit_id}")
        print(f"source tree: {source_tree_id}")
        print(f"validated tree: {validated_tree_id}")
        return payload
    finally:
        python_env_holder.cleanup()

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Overlay 11 final release gates and record provenance-bound evidence.")
    parser.add_argument("--run-id", default=os.environ.get("DEVTOOL_RUN_ID", "").strip())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = str(args.run_id or f"manual-{uuid.uuid4().hex}")
    try:
        run_final_seal(run_id=run_id)
    except Exception as exc:
        print(f"Overlay 11 final release seal failed: {exc}", file=sys.stderr)
        return 1
    print("Overlay 11 final release seal passed; evidence was recorded only after all required gates succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
