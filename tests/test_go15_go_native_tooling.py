from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(p): return (ROOT/p).read_text()
def test_build_sh_has_no_python_or_nuitka():
    s=read("build.sh"); assert "python" not in s.lower(); assert "nuitka" not in s.lower(); assert "go run ./cmd/repoctl build-module" in s
def test_ci_go_native_job_has_no_python_dependency():
    s=read(".github/workflows/ci.yml"); job=s.split("  go-native:",1)[1].split("\n  android:",1)[0]; assert "python" not in job.lower(); assert "repoctl build-runtime" in job; assert "repoctl build-module" in job; assert "repoctl build-source" in job
def test_devtool_package_command_is_go_native():
    s=read(".devtool.toml"); assert 'package_command = "go run ./cmd/repoctl build-module"' in s
def test_repoctl_owns_runtime_module_source_and_release():
    s=read("cmd/repoctl/main.go");
    for command in ["build-runtime","build-module","build-source","validate","release","doctor-cross-arch"]: assert command in s
def test_legacy_native_runtime_python_script_is_only_a_repoctl_shim():
    s=read("scripts/build-native-android-runtime.py"); assert "go\",\"run\",\"./cmd/repoctl\",\"build-runtime" in s; assert "chrootctl.native_runtime" not in s

def test_release_shell_wrapper_is_go_native():
    s=read("scripts/release"); assert "python" not in s.lower(); assert "go run ./cmd/repoctl release" in s
