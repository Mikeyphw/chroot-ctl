// Command devtoolgates validates local source contracts without Python, Android builds,
// root access, broker traffic, or release qualification. Do not weaken repository-purity.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

const moduleName = "chrootctl"

type check struct {
	label  string
	passed bool
}

func repoRoot() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		data, err := os.ReadFile(filepath.Join(dir, "go.mod"))
		if err == nil && strings.HasPrefix(string(data), "module "+moduleName+"\n") {
			return dir, nil
		}
		next := filepath.Dir(dir)
		if next == dir {
			return "", fmt.Errorf("could not locate %s repository root", moduleName)
		}
		dir = next
	}
}

func read(root, relative string) (string, error) {
	path := filepath.Join(root, filepath.FromSlash(relative))
	info, err := os.Lstat(path)
	if err != nil {
		return "", fmt.Errorf("%s: %w", relative, err)
	}
	if !info.Mode().IsRegular() || info.Size() == 0 {
		return "", fmt.Errorf("%s: regular nonempty file required (symlinks denied)", relative)
	}
	bytes, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("%s: %w", relative, err)
	}
	if len(strings.TrimSpace(string(bytes))) == 0 {
		return "", fmt.Errorf("%s: empty file", relative)
	}
	return string(bytes), nil
}

func allChecks(checks []check) error {
	var failed []string
	for _, c := range checks {
		if !c.passed {
			failed = append(failed, c.label)
		}
	}
	if len(failed) > 0 {
		return fmt.Errorf("failed source contracts: %s", strings.Join(failed, ", "))
	}
	return nil
}

func containsAll(haystack string, needles ...string) bool {
	for _, needle := range needles {
		if !strings.Contains(haystack, needle) {
			return false
		}
	}
	return true
}

const (
	chMain   = "cmd/chrootctl/main.go"
	chClient = "internal/skybindr1/client.go"
)

func actionsChecks(root string) ([]check, error) {
	paths := []string{".github/workflows/ci.yml", ".github/workflows/devtool-chrootctl-build.yml", ".devtool.toml", "scripts/ci/hosted-release-stage.sh", "config/chrootctl/devtool-hosted-source.lock"}
	contents := make(map[string]string, len(paths))
	for _, p := range paths {
		content, err := read(root, p)
		if err != nil {
			return nil, err
		}
		contents[p] = content
	}
	ci := contents[paths[0]]
	hosted := contents[paths[1]]
	dag := contents[paths[2]]
	stage := contents[paths[3]]
	lock := contents[paths[4]]
	return []check{
		{"HOSTED_DEVTOOL_SOURCE_PIN", containsAll(hosted, "Mikeyphw/devtool", "CHROOTCTL_EXPECTED_DEVTOOL_SHA", "445044ac4941c1542754cc19d74ebd785b5d8595") && containsAll(lock, "repository=Mikeyphw/devtool", "commit=445044ac4941c1542754cc19d74ebd785b5d8595")},
		{"HOSTED_NDK_API26", containsAll(hosted, "android-actions/setup-android@v4", "ndk;29.0.14206865", "CHROOTCTL_TMUX_ANDROID_API: '26'")},
		{"HOSTED_DEVTOOL_DAG", containsAll(hosted, "-m devtool", "plan ci-release", "invoke ci-release", "--target chrootctl_hosted_release", "--machine-file") && containsAll(dag, "[targets.chrootctl_hosted_release]", "[targets.chrootctl_hosted_release.workflows]", "ci-release =")},
		{"NO_DUPLICATE_NATIVE_BUILD", !containsAll(ci, "repoctl build-runtime") && !strings.Contains(ci, "build-module --") && !strings.Contains(ci, "setup-android@")},
		{"HOSTED_TWO_API26_EDITIONS", containsAll(stage, "build-editions", "verify-editions", "receipt", "CHROOTCTL_RCLONE_PATH", "CHROOTCTL_TMUX_PATH") && containsAll(hosted, "actions/upload-artifact@v4", "actions/attest@v4")},
		{"CI_SKYBIND_SOURCE_GATE", containsAll(ci, "go run ./cmd/devtoolgates actions", "go run ./cmd/devtoolgates r1")},
	}, nil
}

func r1Checks(root string) ([]check, error) {
	cli, err := read(root, chMain)
	if err != nil {
		return nil, err
	}
	client, err := read(root, chClient)
	if err != nil {
		return nil, err
	}
	return []check{
		{"REAL_CHROOTCTL_COMMAND", strings.Contains(cli, `if len(args) > 0 && args[0] == "skybind-read"`)},
		{"ROOT_PROCESS_REQUIRED", strings.Contains(cli, "os.Geteuid() != 0")},
		{"APPROVAL_WINDOW", strings.Contains(cli, "context.WithTimeout(context.Background(), 120*time.Second)")},
		{"READONLY_CLIENT", strings.Contains(cli, "skybindr1.Read(ctx, *op, *remote, *path)")},
		{"ABSTRACT_HANDOFF", strings.Contains(client, `\x00skybind-r1-grant-handoff-v1`)},
		{"NO_NATIVE_FALLBACK", !strings.Contains(client, `exec.Command("rclone"`)},
		{"SCOPED_OPERATIONS", containsAll(client, "rclone.lsjson", "rclone.size", "rclone.listremotes", "rclone.version", "system.capabilities", "validateArgs(op, remote, path)")},
		{"NO_IMPLICIT_APPROVAL", containsAll(client, "receiveGrant(ctx, grantEndpoint)", "return readOnce(ctx, readEndpoint")},
	}, nil
}

func main() {
	if len(os.Args) != 2 || (os.Args[1] != "actions" && os.Args[1] != "r1") {
		fmt.Fprintln(os.Stderr, "usage: go run ./cmd/devtoolgates {actions|r1}")
		os.Exit(2)
	}
	root, err := repoRoot()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	var checks []check
	if os.Args[1] == "actions" {
		checks, err = actionsChecks(root)
	} else {
		checks, err = r1Checks(root)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "FAIL_SOURCE_INPUT:", err)
		os.Exit(2)
	}
	for _, c := range checks {
		verdict := "PASS_"
		if !c.passed {
			verdict = "FAIL_"
		}
		fmt.Println(verdict + c.label)
	}
	if err = allChecks(checks); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	fmt.Println("PASS_" + strings.ToUpper(moduleName) + "_" + strings.ToUpper(os.Args[1]) + "_SOURCE_ONLY_NOT_DEVICE_OR_RELEASE")
}
