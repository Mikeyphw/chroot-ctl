package module

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWebUIWR03UsersParity(t *testing.T) {
	read := func(n string) string {
		b, e := os.ReadFile(filepath.Join("webroot", n))
		if e != nil {
			t.Fatal(e)
		}
		return string(b)
	}
	b, j, h := read("chrootctl.js"), read("index.js"), read("index.html")
	for _, x := range []string{"users.list", "users.get", "users.preview", "users.add", "users.remove", "users.sync_uid_gid", "users.set_shell", "users.set_sudo", "users.set_password", "previewUserMutation", "runUserMutation"} {
		if !strings.Contains(b, x) {
			t.Fatalf("missing user bridge contract %q", x)
		}
	}
	for _, x := range []string{"loadUsers", "reviewUser", "executeUser", "fixOwnership", "deleteHome", "confirmPassword", "policy_reasons"} {
		if !strings.Contains(j, x) {
			t.Fatalf("missing user UI wiring %q", x)
		}
	}
	for _, x := range []string{`id="users-panel"`, `data-route="users"`, `id="user-dialog"`, `id="user-password"`, `id="user-confirm"`} {
		if !strings.Contains(h, x) {
			t.Fatalf("missing users surface %q", x)
		}
	}
}
