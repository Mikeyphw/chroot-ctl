from pathlib import Path


def test_overlay07_install_integrity_contracts():
    root = Path(__file__).parents[1]
    models = (root / "src/chrootctl/models.py").read_text()
    service = (root / "src/chrootctl/services/install.py").read_text()
    execution = (root / "src/chrootctl/services/install_execution.py").read_text()
    parser = (root / "src/chrootctl/parser.py").read_text()
    ubuntu = (root / "src/chrootctl/ubuntu.py").read_text()
    arch = (root / "src/chrootctl/arch.py").read_text()
    base = (root / "src/chrootctl/base_install.py").read_text()
    assert 'arch: str = "arm64"' in models
    assert 'mirror.archlinuxarm.org' in service and 'geo.mirror.pkgbuild.com' not in service
    assert '"arches": ("amd64",)' in service and '"arches": ("arm64",)' in service
    assert 'self._mirror_options(request.distro, request.arch)' in execution
    assert 'resume and repair are mutually exclusive' in service
    assert '--resume and --repair are mutually exclusive' in parser
    assert 'explicit phase cannot be combined with resume/repair' in service
    assert 'verify_detached_signature' in ubuntu and 'verify_sha256' in ubuntu
    assert 'verify_detached_signature' in arch and 'http://os.archlinuxarm.org' not in arch
    assert '_promote_staged_rootfs' in base and '_chrootctl_install_mutation_id' in base
    assert '"version": 2, "steps": steps' in base and 'def _run_install_substep' in base
    assert 'bootstrap.prerequisite-packages' not in base  # substep IDs are composed dynamically
    assert '_run_install_substep("bootstrap"' in ubuntu and '_run_install_substep("bootstrap"' in arch
    assert 'visudo -cf' in base and 'os.replace(temp, sudoers)' in base
    assert 'except InstallFetchError as exc' in base and '_verify_md5' not in base
    assert 'if self.runner.dry_run:' in base
