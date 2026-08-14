
from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path

import pytest
import yaml

from chrootctl.catalog import ManifestCatalog, _grouped_selection_lines, _normalize_manifest_categories, _normalize_manifest_distros
from chrootctl.config import ChrootConfig
from chrootctl.registry import ChrootRegistry
from chrootctl.system import RunResult
from chrootctl.user_sync import UserSyncManager


class Runner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.kwargs: list[dict] = []
        self.dry_run = True

    def require_root(self) -> None:
        return None

    def run(self, args, **kwargs) -> RunResult:
        self.commands.append(list(args))
        self.kwargs.append(kwargs)
        return RunResult(returncode=0, stdout="", stderr="")

    def host_termux_uid_gid(self, termux_home: Path) -> tuple[int, int]:
        return (2000, 2000)


def build_context(tmp_path: Path) -> tuple[ChrootConfig, Runner, ChrootRegistry, logging.Logger]:
    config = ChrootConfig(chroot_root=tmp_path / "chroots", termux_home=tmp_path / "termux-home", distro_name="ubuntu")
    runner = Runner()
    registry = ChrootRegistry(tmp_path / "registry.sqlite3")
    logger = logging.getLogger("test")
    return config, runner, registry, logger


def test_manifest_catalog_lists_builtins() -> None:
    tools = ManifestCatalog("tool").list_entries()
    addons = ManifestCatalog("addon").list_entries()

    assert {entry.name for entry in tools} >= {"sync-uid", "remove-snapd", "diagnose-python-runtime"}
    assert {entry.name for entry in addons} >= {"nala"}


def test_manifest_catalog_filters_supported_distro_variants() -> None:
    assert _normalize_manifest_distros("all", filename="x.yaml") == {"ubuntu", "arch"}
    assert _normalize_manifest_distros(["ubuntu", "arch"], filename="x.yaml") == {"ubuntu", "arch"}
    with pytest.raises(ValueError, match="unsupported distro"):
        _normalize_manifest_distros(["ubuntu", "debian"], filename="x.yaml")


def test_tool_apply_requires_installed_chroot(tmp_path: Path) -> None:
    config, runner, registry, logger = build_context(tmp_path)

    with pytest.raises(RuntimeError, match="installed first"):
        ManifestCatalog("tool").apply(
            name="remove-snapd",
            config=config,
            runner=runner,
            registry=registry,
            logger=logger,
        )


def test_tool_apply_runs_bundled_script_and_updates_registry_metadata(tmp_path: Path) -> None:
    config, runner, registry, logger = build_context(tmp_path)
    registry.upsert(
        name="ubuntu",
        distro="ubuntu",
        path=str(config.chroot_base),
        phase="finalize",
        installed=True,
        metadata={},
    )

    result = ManifestCatalog("tool").apply(
        name="remove-snapd",
        config=config,
        runner=runner,
        registry=registry,
        logger=logger,
    )

    assert result.applied is True
    assert runner.commands
    assert runner.commands[-1][:4] == ["busybox", "chroot", str(config.chroot_base), "/bin/bash"]
    assert runner.kwargs[-1]["chroot_env"] is True
    assert runner.kwargs[-1]["env"]["CHROOTCTL_DISTRO"] == "ubuntu"
    assert registry.get("ubuntu")["metadata"]["tools"] == "remove-snapd"


def test_tool_apply_runs_python_script_inside_chroot(tmp_path: Path) -> None:
    config, runner, registry, logger = build_context(tmp_path)
    registry.upsert(
        name="ubuntu",
        distro="ubuntu",
        path=str(config.chroot_base),
        phase="finalize",
        installed=True,
        metadata={},
    )

    result = ManifestCatalog("tool").apply(
        name="diagnose-python-runtime",
        config=config,
        runner=runner,
        registry=registry,
        logger=logger,
    )

    assert result.applied is True
    assert runner.commands[-2] == ["busybox", "chroot", str(config.chroot_base), "python3", "--version"]
    assert runner.commands[-1] == ["busybox", "chroot", str(config.chroot_base), "python3", "-"]
    assert "CHROOTCTL_NAME" in runner.kwargs[-1]["input_text"]
    assert runner.kwargs[-1]["env"]["CHROOTCTL_USERNAME"] == "mike"
    assert runner.kwargs[-1]["chroot_env"] is True


def test_python_script_reports_missing_chroot_python(tmp_path: Path) -> None:
    config, runner, registry, logger = build_context(tmp_path)
    registry.upsert(
        name="ubuntu",
        distro="ubuntu",
        path=str(config.chroot_base),
        phase="finalize",
        installed=True,
        metadata={},
    )

    def fail_python(args, **kwargs):
        runner.commands.append(list(args))
        runner.kwargs.append(kwargs)
        if args[-1] == "--version":
            return RunResult(returncode=127, stdout="", stderr="python3: not found")
        return RunResult(returncode=0, stdout="", stderr="")

    runner.run = fail_python  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="requires python3 inside the chroot"):
        ManifestCatalog("tool").apply(
            name="diagnose-python-runtime",
            config=config,
            runner=runner,
            registry=registry,
            logger=logger,
        )


def test_addon_apply_runs_bundled_script_and_updates_registry_metadata(tmp_path: Path) -> None:
    config, runner, registry, logger = build_context(tmp_path)
    registry.upsert(
        name="ubuntu",
        distro="ubuntu",
        path=str(config.chroot_base),
        phase="finalize",
        installed=True,
        metadata={"tools": "remove-snapd"},
    )

    result = ManifestCatalog("addon").apply(
        name="nala",
        config=config,
        runner=runner,
        registry=registry,
        logger=logger,
    )

    assert result.applied is True
    assert runner.commands[-1][:4] == ["busybox", "chroot", str(config.chroot_base), "/bin/bash"]
    assert registry.get("ubuntu")["metadata"]["addons"] == "nala"


def test_sync_uid_tool_uses_user_sync_manager(tmp_path: Path, monkeypatch) -> None:
    config, runner, registry, logger = build_context(tmp_path)
    registry.upsert(
        name="ubuntu",
        distro="ubuntu",
        path=str(config.chroot_base),
        phase="finalize",
        installed=True,
        metadata={},
    )
    called: list[tuple[str | None, bool]] = []

    def fake_sync_id(self, username: str | None = None, fix_ownership: bool = True) -> dict[str, str]:
        called.append((username, fix_ownership))
        return {"username": username or self.config.username}

    monkeypatch.setattr(UserSyncManager, "sync_id", fake_sync_id)

    result = ManifestCatalog("tool").apply(
        name="sync-uid",
        config=config,
        runner=runner,
        registry=registry,
        logger=logger,
    )

    assert result.name == "sync-uid"
    assert called == [("mike", True)]
    assert registry.get("ubuntu")["metadata"]["tools"] == "sync-uid"


def test_external_tool_catalog_rejects_builtin_override(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "tools"
    script_dir = tmp_path / "tool-scripts"
    manifest_dir.mkdir()
    script_dir.mkdir()
    script_text = "echo external\n"
    script_sha = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
    (script_dir / "custom-remove-snapd.sh").write_text(script_text, encoding="utf-8")
    (manifest_dir / "remove-snapd.yaml").write_text(
        "\n".join(
            [
                "name: remove-snapd",
                "description: Custom remove snapd",
                "distro: ubuntu",
                "script: custom-remove-snapd.sh",
                f"sha256: {script_sha}",
            ]
        ),
        encoding="utf-8",
    )

    config = ChrootConfig(tool_manifest_dirs=(manifest_dir,), tool_script_dirs=(script_dir,))
    with pytest.raises(ValueError, match="attempts to override existing catalog entry"):
        ManifestCatalog("tool", config=config).list_entries()


def test_external_python_tool_catalog_loads(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "tools"
    script_dir = tmp_path / "tool-scripts"
    manifest_dir.mkdir()
    script_dir.mkdir()
    script_text = "print('external')\n"
    script_sha = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
    (script_dir / "python-tool.py").write_text(script_text, encoding="utf-8")
    (manifest_dir / "python-tool.yaml").write_text(
        "\n".join(
            [
                "name: python-tool",
                "description: Python tool",
                "distro: ubuntu",
                "script: python-tool.py",
                f"sha256: {script_sha}",
            ]
        ),
        encoding="utf-8",
    )

    config = ChrootConfig(tool_manifest_dirs=(manifest_dir,), tool_script_dirs=(script_dir,))
    entry = ManifestCatalog("tool", config=config).get_entry("python-tool")

    assert entry.script == "python-tool.py"
    assert "external" in entry.script_text


def test_external_manifest_rejects_path_traversal(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "tools"
    script_dir = tmp_path / "tool-scripts"
    manifest_dir.mkdir()
    script_dir.mkdir()
    (manifest_dir / "bad.yaml").write_text(
        "\n".join(
            [
                "name: bad-tool",
                "description: Bad",
                "distro: ubuntu",
                "script: ../escape.sh",
            ]
        ),
        encoding="utf-8",
    )

    config = ChrootConfig(tool_manifest_dirs=(manifest_dir,), tool_script_dirs=(script_dir,))
    with pytest.raises(ValueError, match="invalid script path"):
        ManifestCatalog("tool", config=config).list_entries()


def test_external_manifest_requires_existing_script(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "tools"
    script_dir = tmp_path / "tool-scripts"
    manifest_dir.mkdir()
    script_dir.mkdir()
    (manifest_dir / "missing.yaml").write_text(
        "\n".join(
            [
                "name: missing-tool",
                "description: Missing",
                "distro: ubuntu",
                "script: missing.sh",
            ]
        ),
        encoding="utf-8",
    )

    config = ChrootConfig(tool_manifest_dirs=(manifest_dir,), tool_script_dirs=(script_dir,))
    with pytest.raises(ValueError, match="missing external script"):
        ManifestCatalog("tool", config=config).list_entries()


def test_external_manifest_rejects_unsupported_script_suffix(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "tools"
    script_dir = tmp_path / "tool-scripts"
    manifest_dir.mkdir()
    script_dir.mkdir()
    (manifest_dir / "bad.yaml").write_text(
        "\n".join(
            [
                "name: bad-tool",
                "description: Bad",
                "distro: ubuntu",
                "script: bad.rb",
            ]
        ),
        encoding="utf-8",
    )

    config = ChrootConfig(tool_manifest_dirs=(manifest_dir,), tool_script_dirs=(script_dir,))
    with pytest.raises(ValueError, match="unsupported script suffix"):
        ManifestCatalog("tool", config=config).list_entries()


def test_config_loads_external_repository_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "repositories": {
            "tool_manifests": ["~/tools", "/tmp/tool-manifests"],
            "tool_scripts": ["/tmp/tool-scripts"],
            "addon_manifests": ["/tmp/addon-manifests"],
            "addon_scripts": ["/tmp/addon-scripts"]
          }
        }
        """,
        encoding="utf-8",
    )

    config = ChrootConfig.load(config_path)

    assert len(config.tool_manifest_dirs) == 2
    assert config.tool_manifest_dirs[0].name == "tools"
    assert config.tool_script_dirs == (Path("/tmp/tool-scripts"),)
    assert config.addon_manifest_dirs == (Path("/tmp/addon-manifests"),)
    assert config.addon_script_dirs == (Path("/tmp/addon-scripts"),)


def test_manifest_categories_are_normalized_and_filterable() -> None:
    assert _normalize_manifest_categories(["Package Management", "package_management"], filename="x.yaml") == {"package-management"}

    tools = ManifestCatalog("tool")
    remove_snapd = tools.get_entry("remove-snapd")
    assert remove_snapd.categories == ("package-management", "system")
    package_tools = {entry.name for entry in tools.list_entries(category="package management")}
    assert {"remove-snapd", "setup-dev-basics", "setup-flatpak"} <= package_tools


def test_external_categories_are_normalized_and_added_to_catalog(tmp_path: Path) -> None:
    manifests = tmp_path / "tools"
    scripts = tmp_path / "tool-scripts"
    manifests.mkdir()
    scripts.mkdir()

    script_text = "echo external\n"
    script_sha = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
    (scripts / "external-cleanup.sh").write_text(script_text, encoding="utf-8")
    (manifests / "external-cleanup.yaml").write_text(
        f"""
name: external-cleanup
description: External cleanup
distro: ubuntu
categories:
  - Cleanup
  - package management
script: external-cleanup.sh
sha256: {script_sha}
""".strip(),
        encoding="utf-8",
    )

    config = ChrootConfig(
        tool_manifest_dirs=(manifests,),
        tool_script_dirs=(scripts,),
    )
    catalog = ManifestCatalog("tool", config=config)
    entry = catalog.get_entry("external-cleanup")

    assert entry.description == "External cleanup"
    assert entry.categories == ("cleanup", "package-management")
    categories = catalog.categories()
    assert "cleanup" in categories
    assert "package-management" in categories
    assert "system" in categories


def test_external_manifest_requires_script_hash(tmp_path: Path) -> None:
    manifests = tmp_path / "tools"
    scripts = tmp_path / "tool-scripts"
    manifests.mkdir()
    scripts.mkdir()
    (scripts / "external.sh").write_text("echo external\n", encoding="utf-8")
    (manifests / "external.yaml").write_text(
        "name: external\ndescription: External\ndistro: ubuntu\nscript: external.sh\n",
        encoding="utf-8",
    )
    config = ChrootConfig(tool_manifest_dirs=(manifests,), tool_script_dirs=(scripts,))
    with pytest.raises(ValueError, match="must declare a lowercase sha256"):
        ManifestCatalog("tool", config=config).list_entries()


def test_external_manifest_rejects_script_hash_mismatch(tmp_path: Path) -> None:
    manifests = tmp_path / "tools"
    scripts = tmp_path / "tool-scripts"
    manifests.mkdir()
    scripts.mkdir()
    (scripts / "external.sh").write_text("echo changed\n", encoding="utf-8")
    (manifests / "external.yaml").write_text(
        "name: external\ndescription: External\ndistro: ubuntu\nscript: external.sh\nsha256: " + ("0" * 64) + "\n",
        encoding="utf-8",
    )
    config = ChrootConfig(tool_manifest_dirs=(manifests,), tool_script_dirs=(scripts,))
    with pytest.raises(ValueError, match="script sha256 mismatch"):
        ManifestCatalog("tool", config=config).list_entries()


def test_catalog_categories_are_sorted_and_unique() -> None:
    categories = ManifestCatalog("tool").categories()
    assert categories == sorted(set(categories))
    assert "system" in categories


def test_grouped_selection_lines_sort_by_primary_category_then_name() -> None:
    entries = ManifestCatalog("tool").list_entries()
    lines = _grouped_selection_lines(entries)
    assert lines
    assert all(line.count("\t") == 2 for line in lines)
    categories = [line.split("\t", 2)[1].split(",", 1)[0] for line in lines]
    assert categories == sorted(categories)


def test_builtin_manifests_all_resolve_to_bundled_scripts() -> None:
    for kind in ("tool", "addon"):
        catalog = ManifestCatalog(kind)  # type: ignore[arg-type]
        assert catalog.list_entries()
        for entry in catalog.list_entries():
            assert entry.script_text
            assert entry.script.endswith((".sh", ".py"))


def test_builtin_shell_scripts_have_valid_syntax() -> None:
    script_paths = list(Path("src/chrootctl/resources/tool-scripts").glob("*.sh"))
    script_paths += list(Path("src/chrootctl/resources/addon-scripts").glob("*.sh"))
    assert script_paths
    for path in script_paths:
        result = subprocess.run(["sh", "-n", str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


def test_builtin_python_scripts_compile() -> None:
    script_paths = list(Path("src/chrootctl/resources/tool-scripts").glob("*.py"))
    script_paths += list(Path("src/chrootctl/resources/addon-scripts").glob("*.py"))
    assert script_paths
    for path in script_paths:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_builtin_all_distro_scripts_cover_ubuntu_and_arch() -> None:
    for manifest_dir, script_dir in (
        (Path("src/chrootctl/resources/tools"), Path("src/chrootctl/resources/tool-scripts")),
        (Path("src/chrootctl/resources/addons"), Path("src/chrootctl/resources/addon-scripts")),
    ):
        for manifest in manifest_dir.glob("*.yaml"):
            payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
            script_text = (script_dir / payload["script"]).read_text(encoding="utf-8")
            distros = _normalize_manifest_distros(payload["distro"], filename=manifest.name)
            if distros == {"ubuntu", "arch"} and payload["script"].endswith(".sh"):
                assert "ubuntu)" in script_text, manifest.name
                assert "arch)" in script_text, manifest.name
            elif payload["script"].endswith(".sh"):
                assert "unsupported distro" in script_text, manifest.name


def test_package_data_includes_python_scripts() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "resources/tool-scripts/*.py" in pyproject
    assert "resources/addon-scripts/*.py" in pyproject
