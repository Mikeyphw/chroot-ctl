package module

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCC09ModuleSwitchBothWaysAfterRebootNoLegacyRcloneOrStateLoss(t *testing.T) {
	// Model root-manager staged activation by switching the active symlink-like
	// module directory *after* the installer defers live mutation. This cannot
	// prove a physical reboot; it proves the checked-in staged files/logic.
	for _, pair := range [][2]string{{"rclone", "standard"}, {"standard", "rclone"}} {
		t.Run(pair[0]+"-to-"+pair[1], func(t *testing.T) {
			old := renderSecurityEdition(t, pair[0], "old")
			next := renderSecurityEdition(t, pair[1], "next")
			active := filepath.Join(t.TempDir(), "chrootctl")
			if err := os.Rename(old, active); err != nil {
				t.Fatal(err)
			}
			userState := filepath.Join(t.TempDir(), "private-state")
			if err := os.MkdirAll(userState, 0700); err != nil {
				t.Fatal(err)
			}
			golden := []byte("sensitive-preserved-user-data")
			if err := os.WriteFile(filepath.Join(userState, "config"), golden, 0600); err != nil {
				t.Fatal(err)
			}
			before, err := os.ReadFile(filepath.Join(active, "runtime", RuntimeABI, "runtime-manifest.json"))
			if err != nil {
				t.Fatal(err)
			}
			log, err := runCustomizeFixture(t, next, active, userState, "")
			if err != nil || !strings.Contains(log, "reboot required") {
				t.Fatalf("installer did not defer cross-edition switch: %v %s", err, log)
			}
			got, err := os.ReadFile(filepath.Join(active, "runtime", RuntimeABI, "runtime-manifest.json"))
			if err != nil || !bytes.Equal(before, got) {
				t.Fatal("old active runtime mutated before reboot")
			}
			// A controlled staged activation with no prior live merge.
			retired := active + ".old"
			if err := os.Rename(active, retired); err != nil {
				t.Fatal(err)
			}
			if err := os.Rename(next, active); err != nil {
				t.Fatal(err)
			}
			if err := ValidateInstalled(active); err != nil {
				t.Fatalf("new edition invalid: %v", err)
			}
			if _, err := os.Lstat(filepath.Join(active, "runtime", RuntimeABI, "rclone")); (err == nil) != (pair[1] == "rclone") {
				t.Fatalf("new runtime edition membership: %v", err)
			}
			after, err := os.ReadFile(filepath.Join(userState, "config"))
			if err != nil || !bytes.Equal(golden, after) {
				t.Fatal("user state mutated/lost")
			}
			if err := ValidateInstalled(retired); err != nil {
				t.Fatal("previous rollback edition corrupted: ", err)
			}
		})
	}
}

func TestCC09CorruptStagedUpgradeMustNotTouchActiveOrUserState(t *testing.T) {
	for _, edition := range []string{"standard", "rclone"} {
		t.Run(edition, func(t *testing.T) {
			stage := renderSecurityEdition(t, edition, "new")
			old := renderSecurityEdition(t, edition, "old")
			active := filepath.Join(t.TempDir(), "chrootctl")
			if err := os.Rename(old, active); err != nil {
				t.Fatal(err)
			}
			state := t.TempDir()
			marker := filepath.Join(state, "keep")
			if err := os.WriteFile(marker, []byte("do-not-touch"), 0600); err != nil {
				t.Fatal(err)
			}
			oldBytes, _ := os.ReadFile(filepath.Join(active, "runtime", RuntimeABI, "runtime-manifest.json"))
			if err := os.Remove(filepath.Join(stage, "runtime", RuntimeABI, "chrootctl")); err != nil {
				t.Fatal(err)
			}
			out, err := runCustomizeFixture(t, stage, active, state, "")
			if err == nil {
				t.Fatalf("installer accepted missing sealed native runtime: %s", out)
			}
			newBytes, err := os.ReadFile(filepath.Join(active, "runtime", RuntimeABI, "runtime-manifest.json"))
			if err != nil || !bytes.Equal(oldBytes, newBytes) {
				t.Fatal("installed active module corrupted on rejected upgrade")
			}
			content, err := os.ReadFile(marker)
			if err != nil || string(content) != "do-not-touch" {
				t.Fatal("private state mutated on rejected upgrade")
			}
			if err := ValidateInstalled(active); err != nil {
				t.Fatalf("previous runtime no longer valid: %v", err)
			}
		})
	}
}
