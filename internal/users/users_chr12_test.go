package users

import (
	"chrootctl/internal/config"
	sys "chrootctl/internal/system"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func chr12Manager(t *testing.T) (Manager, string) {
	t.Helper()
	d := t.TempDir()
	cfg := config.Default(config.RuntimeContext{Home: d})
	cfg.ChrootRoot = d
	cfg.DistroName = "ubuntu"
	cfg.Username = "mike"
	cfg.TermuxHome = d
	etc := filepath.Join(cfg.ChrootBase(), "etc")
	if err := os.MkdirAll(filepath.Join(etc, "sudoers.d"), 0o755); err != nil {
		t.Fatal(err)
	}
	passwd := strings.Join([]string{
		"root:x:0:0:root:/root:/bin/bash",
		"daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin",
		"mike:x:1000:1000:Mike:/home/mike:/bin/bash",
		"",
	}, "\n")
	if err := os.WriteFile(filepath.Join(etc, "passwd"), []byte(passwd), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(etc, "group"), []byte("root:x:0:\nsudo:x:27:mike\nmike:x:1000:\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return Manager{Config: cfg, Runner: &sys.Runner{DryRun: true}}, etc
}

func TestCHR12ListClassifiesProtectedSystemAndActualSudo(t *testing.T) {
	m, etc := chr12Manager(t)
	if err := os.WriteFile(filepath.Join(etc, "sudoers.d", "mike"), []byte(sudoersRule("mike")), 0o440); err != nil {
		t.Fatal(err)
	}
	rows, err := m.List()
	if err != nil {
		t.Fatal(err)
	}
	byName := map[string]User{}
	for _, row := range rows {
		byName[row.Username] = row
	}
	if !byName["root"].Protected || byName["root"].Mutable {
		t.Fatalf("root policy = %+v", byName["root"])
	}
	if !byName["daemon"].System || byName["daemon"].Mutable {
		t.Fatalf("daemon policy = %+v", byName["daemon"])
	}
	if !byName["mike"].Sudo || !byName["mike"].SudoRule || !byName["mike"].SudoGroup || !byName["mike"].Mutable {
		t.Fatalf("mike sudo/policy = %+v", byName["mike"])
	}
}

func TestCHR12ProtectedMutationPolicyRejectsRootAndSystemUsers(t *testing.T) {
	m, _ := chr12Manager(t)
	for _, name := range []string{"root", "daemon"} {
		if _, err := m.ensureMutableUser(name, "test"); err == nil {
			t.Fatalf("expected protected/system rejection for %s", name)
		}
	}
	if _, err := m.ensureMutableUser("mike", "test"); err != nil {
		t.Fatalf("expected managed user to be mutable: %v", err)
	}
	if err := rejectProtectedNewUser("root"); err == nil {
		t.Fatal("expected root creation rejection")
	}
}

func TestCHR12SudoersPathAndRuleMatchInstallerContract(t *testing.T) {
	m, _ := chr12Manager(t)
	if got := filepath.Base(m.sudoers("mike")); got != "mike" {
		t.Fatalf("sudoers basename = %s", got)
	}
	rule := sudoersRule("mike")
	if !strings.Contains(rule, "NOPASSWD: ALL") || !sudoersRuleMentionsUser(rule, "mike") {
		t.Fatalf("rule not passwordless or not recognized: %q", rule)
	}
}

func TestCHR12IdentityRowsReturnReadErrors(t *testing.T) {
	if _, err := identityRowsErr(filepath.Join(t.TempDir(), "missing-passwd")); err == nil {
		t.Fatal("expected missing passwd error")
	}
}

func TestCHR12PasswordValidationPreservesOuterSpaces(t *testing.T) {
	got, err := ValidatePassword("  leading and trailing spaces  ")
	if err != nil {
		t.Fatal(err)
	}
	if got != "  leading and trailing spaces  " {
		t.Fatalf("password was trimmed: %q", got)
	}
}
