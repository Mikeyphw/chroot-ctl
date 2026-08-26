from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_webui_source_and_browser_tests_are_retired() -> None:
    root = repo_root()
    assert not any(path.is_file() for path in (root / "src/chrootctl/web").glob("**/*"))
    assert not (root / "tests/test_web_app.py").exists()
    assert not (root / "tests/test_web_jobs.py").exists()
    assert not (root / "tests/test_web_security.py").exists()
    assert not (root / "tests/test_transfer_upload.py").exists()
    assert not (root / "playwright.config.ts").exists()


def test_python_packaging_exposes_only_cli_and_android_bridge() -> None:
    root = repo_root()
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'chrootctl = "chrootctl.cli:main"' in pyproject
    assert 'chrootctl-app = "chrootctl.bridge.cli:main"' in pyproject
    assert "chrootctl-web" not in pyproject
    for token in ("fastapi", "Jinja2", "uvicorn", "python-multipart", "web/templates", "web/static"):
        assert token not in pyproject


def test_magisk_renderer_no_longer_emits_webui_artifacts(tmp_path: Path) -> None:
    from chrootctl.magisk import MagiskModuleConfig, render_magisk_module
    from chrootctl.native_runtime import DEFAULT_NATIVE_RUNTIME_ENTRYPOINT, write_native_runtime_manifest

    # Release identity is now verified against the real package metadata, so use
    # the repository package as input while keeping the rendered module isolated.
    package_root = repo_root() / "src"
    native_runtime = tmp_path / "native/arm64-v8a"
    native_entrypoint = native_runtime / DEFAULT_NATIVE_RUNTIME_ENTRYPOINT
    native_entrypoint.parent.mkdir(parents=True)
    native_entrypoint.write_bytes(b"\x7fELFfake-chrootctl")
    native_entrypoint.chmod(0o755)
    write_native_runtime_manifest(
        native_runtime, abi="arm64-v8a", package_version="0.11.0", bridge_protocol_version=1, nuitka_version="test"
    )
    output_dir = tmp_path / "module"
    render_magisk_module(
        output_dir,
        services=None,
        startup_targets=(),
        module_config=MagiskModuleConfig(package_source_dir=package_root, native_runtime_dir=native_runtime),
    )

    assert (output_dir / "system/bin/chrootctl").exists()
    assert not (output_dir / "system/bin/chrootctl-python-bootstrap").exists()
    assert not (output_dir / "bin/chrootctl-python-bootstrap").exists()
    assert not (output_dir / "payload").exists()
    assert not (output_dir / "system/bin/chrootctl-web").exists()
    assert not (output_dir / "system/bin/chrootctl-webui-service").exists()
    assert not (output_dir / "bin/chrootctl-webui-service").exists()
    assert not (output_dir / "config/chrootctl/webui.env").exists()
    assert not (output_dir / "webroot/index.html").exists()
    assert not (output_dir / "payload").exists()


def test_parity_matrix_is_green_or_retired() -> None:
    matrix = (repo_root() / "docs/android/WEBUI_PARITY_MATRIX.md").read_text(encoding="utf-8")
    assert "Phase 21 retirement" in matrix
    assert "Native complete" in matrix
    assert "Retired" in matrix
    assert "FastAPI HTTP server" in matrix
    assert "libsu RootService Binder bridge" in matrix
