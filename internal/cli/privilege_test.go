package cli

import (
	"reflect"
	"testing"
)

func TestCHR04DryRunNeverShortCircuitsIntoPrivilegeReexec(t *testing.T) {
	inv, err := Parse([]string{"--dry-run", "chroots", "diff", "left", "right"})
	if err != nil {
		t.Fatal(err)
	}
	if shouldReexecPrivilege(inv, false) {
		t.Fatal("dry-run must reach dispatch instead of privilege reexec")
	}
	real, err := Parse([]string{"chroots", "diff", "left", "right"})
	if err != nil {
		t.Fatal(err)
	}
	if !shouldReexecPrivilege(real, false) {
		t.Fatal("real privileged action must reexec when non-root")
	}
}

func TestCHR04PrivilegeReexecFreezesDefaultConfigIdentity(t *testing.T) {
	inv, err := Parse([]string{"chroots", "rename", "new"})
	if err != nil {
		t.Fatal(err)
	}
	got := privilegeReexecArgs(inv, []string{"chroots", "rename", "new"})
	if len(got) < 5 || got[0] != "--config" || got[1] == "" {
		t.Fatalf("config identity not frozen: %#v", got)
	}
	wantTail := []string{"chroots", "rename", "new"}
	if !reflect.DeepEqual(got[len(got)-3:], wantTail) {
		t.Fatalf("argv drift: %#v", got)
	}
}
