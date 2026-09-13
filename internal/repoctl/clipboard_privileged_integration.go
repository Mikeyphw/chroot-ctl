package repoctl

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ValidateClipboardPrivilegedIntegration keeps CHR14 executable instead of prose-only.
// It seals the clipboard bridge lifecycle/trust model that was found in the audit:
// one host socket authority, private custom control paths, serialized starts,
// no live socket takeover, stale-state cleanup, bounded stdin/wire/runtime IO,
// target-scoped wrapper enablement, and daemon log retention.
func ValidateClipboardPrivilegedIntegration(root string) error {
	read := func(rel string) (string, error) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			return "", fmt.Errorf("CHR14 read %s: %w", rel, err)
		}
		return string(b), nil
	}
	mustContain := func(rel string, tokens ...string) error {
		text, err := read(rel)
		if err != nil {
			return err
		}
		for _, token := range tokens {
			if !strings.Contains(text, token) {
				return fmt.Errorf("CHR14 %s missing invariant %q", rel, token)
			}
		}
		return nil
	}
	mustNotContain := func(rel string, tokens ...string) error {
		text, err := read(rel)
		if err != nil {
			return err
		}
		for _, token := range tokens {
			if strings.Contains(text, token) {
				return fmt.Errorf("CHR14 %s still contains forbidden token %q", rel, token)
			}
		}
		return nil
	}

	if err := mustContain("internal/clipboard/clipboard.go",
		"managedRoot(cfg)",
		"PIDFile:    filepath.Join(runtimeDir, \"clipboard-daemon.pid\")",
		"func normalizePaths(cfg config.ChrootConfig, paths Paths) (Paths, error)",
		"custom clipboard control directory must already exist and be private",
		"func acquireLock(path string) (*fileLock, error)",
		"verifyNoCorruptLiveState(paths)",
		"clipboard socket already exists",
		"cleanupPaths(paths)",
		"MaxConcurrentRequests",
		"SetReadDeadline(time.Now().Add(2 * time.Second))",
		"SetWriteDeadline(time.Now().Add(2 * time.Second))",
		"WrapperMarkerVersion",
		"authorizeTarget(cfg, strings.TrimSpace(req.Target))",
		"target_enabled",
	); err != nil {
		return err
	}
	if err := mustContain("internal/cli/dispatch.go",
		"func clipboardSetText(inv Invocation, stdin io.Reader) (string, error)",
		"MaxClipboardTextBytes + 1",
		"strings.Join(values, \" \")",
		"socket = paths.SocketPath",
		"clipboard.StopDaemon(paths)",
		"ConfigFor(a.Inv.Globals.Name, \"\")",
	); err != nil {
		return err
	}
	if err := mustContain("resources/tool-scripts/setup-clipboard.sh",
		"TARGET_NAME='__CHROOTCTL_NAME__'",
		"--arg target \"$TARGET_NAME\"",
		"jq -Rs",
		"MAX_CLIPBOARD_BYTES=1048576",
		"sed -i \"s|__CHROOTCTL_NAME__|$target_escaped|g\" /usr/local/bin/termux-clip",
	); err != nil {
		return err
	}
	if err := mustNotContain("internal/cli/dispatch.go",
		"socket = clipboard.ChrootSocket",
		"io.ReadAll(a.Stdin)",
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/roadmap-coverage.json",
		`"id": "CHR14"`,
		`"title": "Clipboard privileged integration"`,
		`"ownerOverlay": "CHR14"`,
		`"status": "implemented"`,
	); err != nil {
		return err
	}
	if err := mustContain("docs/audit/CHR14_CLIPBOARD_PRIVILEGED_INTEGRATION.md", "Clipboard privileged integration", "ValidateClipboardPrivilegedIntegration"); err != nil {
		return err
	}
	return nil
}
