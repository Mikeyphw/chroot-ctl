package repoctl

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type validationCheck struct {
	Status     string `json:"status"`
	Command    string `json:"command"`
	Provenance string `json:"provenance"`
	ExitCode   int    `json:"exitCode"`
	RecordedAt int64  `json:"recordedAt"`
	Detail     string `json:"detail,omitempty"`
}

type validationEvidence struct {
	SchemaVersion               int                        `json:"schemaVersion"`
	GeneratedAt                 int64                      `json:"generatedAt"`
	ValidationRunID             string                     `json:"validationRunId"`
	SourceCommit                string                     `json:"sourceCommit"`
	SourceTree                  string                     `json:"sourceTree"`
	CompatibilityManifestSHA256 string                     `json:"compatibilityManifestSha256"`
	Checks                      map[string]validationCheck `json:"checks"`
}

func recordCheck(checks map[string]validationCheck, id, command, provenance string, fn func() error) error {
	err := fn()
	item := validationCheck{Status: "pass", Command: command, Provenance: provenance, ExitCode: 0, RecordedAt: time.Now().Unix()}
	if err != nil {
		item.Status = "fail"
		item.ExitCode = 1
		item.Detail = err.Error()
	}
	checks[id] = item
	return err
}

func recordCheckGroup(checks map[string]validationCheck, ids []string, command, provenance string, fn func() error) error {
	err := fn()
	item := validationCheck{Status: "pass", Command: command, Provenance: provenance, ExitCode: 0, RecordedAt: time.Now().Unix()}
	if err != nil {
		item.Status = "fail"
		item.ExitCode = 1
		item.Detail = err.Error()
	}
	for _, id := range ids {
		checks[id] = item
	}
	return err
}

func validationRunID() string {
	b := make([]byte, 8)
	if _, err := rand.Read(b); err == nil {
		return fmt.Sprintf("go17-%d-%s", time.Now().Unix(), hex.EncodeToString(b))
	}
	return fmt.Sprintf("go17-%d", time.Now().UnixNano())
}

func validationEvidencePath(root, requested string) string {
	if strings.TrimSpace(requested) != "" {
		if filepath.IsAbs(requested) {
			return requested
		}
		return filepath.Join(root, requested)
	}
	// Legacy repoctl final-seal evidence is intentionally repository-local.
	// Runtime readiness is fed only by the schema-v4 root-module evidence
	// embedded in the sealed module and published by post-fs-data.sh. Keeping
	// the legacy schema-v3 writer out of /data/adb/chrootctl prevents a manual
	// final-seal invocation from overwriting authoritative runtime evidence.
	return filepath.Join(root, "dist", "legacy-final-seal-results.json")
}

func writeFinalSealEvidence(root, path string, checks map[string]validationCheck) (string, error) {
	required := []string{"go_test", "go_vet", "go_contracts", "repo_purity", "audit_coverage", "source_package", "android_compileDebugKotlin", "android_testDebugUnitTest", "android_lint_configuration_seal", "module_render", "module_zip", "module_shell", "source_no_webui"}
	for _, id := range required {
		item, ok := checks[id]
		if !ok || item.Status != "pass" || item.ExitCode != 0 {
			return "", fmt.Errorf("cannot write final-seal evidence: check %s did not pass", id)
		}
	}
	compat := filepath.Join(root, "docs", "release", "compatibility-manifest.json")
	compatSHA, err := regularFileSHA256(compat)
	if err != nil {
		return "", err
	}
	commit, tree := "", ""
	if _, err := os.Stat(filepath.Join(root, ".git")); err == nil {
		commit = gitValueSimple(root, "rev-parse", "HEAD")
		tree = gitValueSimple(root, "rev-parse", "HEAD^{tree}")
		if commit == "" || tree == "" {
			return "", fmt.Errorf("cannot resolve Git source identity for final-seal evidence")
		}
		status := gitValueSimple(root, "status", "--porcelain", "--untracked-files=normal")
		if strings.TrimSpace(status) != "" {
			return "", fmt.Errorf("refusing final-seal evidence for a dirty Git worktree")
		}
	}
	evidence := validationEvidence{SchemaVersion: 3, GeneratedAt: time.Now().Unix(), ValidationRunID: validationRunID(), SourceCommit: commit, SourceTree: tree, CompatibilityManifestSHA256: compatSHA, Checks: checks}
	path = validationEvidencePath(root, path)
	if err = writePrivateJSON(path, evidence); err != nil {
		return "", err
	}
	return path, nil
}

func gitValueSimple(root string, args ...string) string {
	cmd := exec.Command("git", append([]string{"-C", root}, args...)...)
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func validateModuleShellContract(root string) error {
	files := []string{"service.sh", "bin/chrootctl-magisk-helper", "system/bin/chrootctl"}
	for _, rel := range files {
		path := filepath.Join(root, filepath.FromSlash(rel))
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		text := string(data)
		if !strings.HasPrefix(text, "#!/system/bin/sh\n") {
			return fmt.Errorf("module shell file lacks Android sh shebang: %s", rel)
		}
		lower := strings.ToLower(text)
		for _, token := range []string{"python", "nuitka"} {
			if strings.Contains(lower, token) {
				return fmt.Errorf("module shell file %s contains retired runtime token %q", rel, token)
			}
		}
	}
	service, _ := os.ReadFile(filepath.Join(root, "service.sh"))
	helper, _ := os.ReadFile(filepath.Join(root, "bin/chrootctl-magisk-helper"))
	launcher, _ := os.ReadFile(filepath.Join(root, "system/bin/chrootctl"))
	if !strings.Contains(string(service), "__module-service") || !strings.Contains(string(helper), "run --boot") || !strings.Contains(string(helper), `--name "$target" mount`) || !strings.Contains(string(launcher), `exec "$RUNTIME_BIN" "$@"`) {
		return fmt.Errorf("module boot/runtime shell contract is incomplete")
	}
	return nil
}

func validateNoWebUI(root string) error {
	roots := []string{filepath.Join(root, "internal"), filepath.Join(root, "android", "app", "src", "main"), filepath.Join(root, "resources")}
	for _, base := range roots {
		err := filepath.WalkDir(base, func(path string, d os.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if d.IsDir() {
				return nil
			}
			data, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			lower := strings.ToLower(string(data))
			for _, token := range []string{"chrootctl-web", "fastapi", "jinja2", "uvicorn", "python-multipart", "android.webkit.webview"} {
				if strings.Contains(lower, token) {
					rel, _ := filepath.Rel(root, path)
					return fmt.Errorf("retired WebUI runtime token %q remains in %s", token, filepath.ToSlash(rel))
				}
			}
			return nil
		})
		if err != nil {
			return err
		}
	}
	return nil
}
