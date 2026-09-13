package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"syscall"
	"testing"
)

func TestGlobalsAcceptedAfterCommandAndEqualsSyntax(t *testing.T) {
	inv, err := Parse([]string{"status", "--json", "--name=work", "--config=/tmp/c"})
	if err != nil {
		t.Fatal(err)
	}
	if !inv.Globals.JSON || inv.Globals.Name != "work" || inv.Globals.ConfigPath != "/tmp/c" {
		t.Fatalf("%+v", inv.Globals)
	}
}

func TestCommandLocalOptionWinsGlobalCollision(t *testing.T) {
	inv, err := Parse([]string{"magisk", "render", "--output", "/tmp/module", "--name", "boot-a", "--name=boot-b"})
	if err != nil {
		t.Fatal(err)
	}
	if inv.Globals.Name != "" {
		t.Fatalf("global name stolen: %q", inv.Globals.Name)
	}
	got := inv.Strings("magisk_names")
	if len(got) != 2 || got[0] != "boot-a" || got[1] != "boot-b" {
		t.Fatalf("names=%v", got)
	}
}

func TestHelpSkipsRequiredAndActionGroupValidation(t *testing.T) {
	for _, args := range [][]string{{"magisk", "render", "--help"}, {"users", "sudo", "--help"}} {
		inv, err := Parse(args)
		if err != nil {
			t.Fatalf("%v: %v", args, err)
		}
		if !inv.Help {
			t.Fatalf("help=false: %v", args)
		}
	}
}

func TestMutuallyExclusiveAndRequiredActionGroups(t *testing.T) {
	if _, err := Parse([]string{"start", "--login", "--root-login"}); err == nil {
		t.Fatal("expected exclusive-group error")
	}
	if _, err := Parse([]string{"users", "sudo", "alice"}); err == nil {
		t.Fatal("expected require-one-of error")
	}
	if _, err := Parse([]string{"users", "sudo", "alice", "--enable", "--disable"}); err == nil {
		t.Fatal("expected exclusive sudo action error")
	}
}

func TestIntegerBoundsComeFromContract(t *testing.T) {
	if _, err := Parse([]string{"events", "list", "--limit", "1001"}); err == nil {
		t.Fatal("expected max bound error")
	}
	if _, err := Parse([]string{"logs", "--tail=-1"}); err == nil {
		t.Fatal("expected min bound error")
	}
}

func TestOutputAndPrivilegeCapabilitiesComeFromSpec(t *testing.T) {
	inv, err := Parse([]string{"run", "--list", "--json"})
	if err != nil {
		t.Fatal(err)
	}
	if got := inv.Spec.EffectivePrivilege(inv.Values); got != "none" {
		t.Fatalf("privilege=%q", got)
	}
	if _, err = Parse([]string{"run", "svc", "--foreground", "--json"}); err == nil {
		t.Fatal("expected raw foreground/json conflict")
	}
	if _, err = Parse([]string{"completion", "zsh", "--json"}); err == nil {
		t.Fatal("expected unsupported json error")
	}
}

func TestVersionIsContractAction(t *testing.T) {
	for _, args := range [][]string{{"version"}, {"--version"}, {"--json", "--version"}} {
		inv, err := Parse(args)
		if err != nil {
			t.Fatalf("%v: %v", args, err)
		}
		if inv.Spec.Command != "version" {
			t.Fatalf("%v -> %q", args, inv.Spec.Command)
		}
	}
}

func TestVersionJSONUsesStableEnvelope(t *testing.T) {
	var out, errOut bytes.Buffer
	code := Run(context.Background(), []string{"--json", "version"}, strings.NewReader(""), &out, &errOut)
	if code != 0 {
		t.Fatalf("code=%d stderr=%s", code, errOut.String())
	}
	var env responseEnvelope
	if err := json.Unmarshal(out.Bytes(), &env); err != nil {
		t.Fatal(err)
	}
	if env.SchemaVersion != 1 || !env.OK || env.Command != "version" || env.Error != nil {
		t.Fatalf("env=%+v", env)
	}
}

func TestParseFailureJSONUsesSameEnvelope(t *testing.T) {
	var out, errOut bytes.Buffer
	code := Run(context.Background(), []string{"--json", "completion", "zsh"}, strings.NewReader(""), &out, &errOut)
	if code != 2 {
		t.Fatalf("code=%d stdout=%s stderr=%s", code, out.String(), errOut.String())
	}
	var env responseEnvelope
	if err := json.Unmarshal(out.Bytes(), &env); err != nil {
		t.Fatal(err)
	}
	if env.SchemaVersion != 1 || env.OK || env.Error == nil || env.Error.Code == "" {
		t.Fatalf("env=%+v", env)
	}
	if errOut.Len() != 0 {
		t.Fatalf("stderr not pure: %q", errOut.String())
	}
}

func TestSignalExitCodesAreStable(t *testing.T) {
	for sig, want := range map[syscall.Signal]int{syscall.SIGINT: 130, syscall.SIGTERM: 143} {
		ctx, cancel := context.WithCancelCause(context.Background())
		cancel(NewSignalError(sig))
		if got := signalExitCode(ctx, 0); got != want {
			t.Fatalf("signal %d: got %d want %d", sig, got, want)
		}
	}
}
