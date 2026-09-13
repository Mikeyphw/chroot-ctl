package cli

import (
	"encoding/json"
	"os"
	"testing"
)

func TestContractCommandSurfaceHas69Nodes(t *testing.T) {
	if len(CommandSpecs) != 69 {
		t.Fatalf("nodes=%d", len(CommandSpecs))
	}
	seen := map[string]bool{}
	for _, s := range CommandSpecs {
		if seen[s.Command] {
			t.Fatalf("duplicate %s", s.Command)
		}
		seen[s.Command] = true
	}
	raw, e := os.ReadFile("../../migration/contracts/v1/cli.json")
	if e != nil {
		t.Fatal(e)
	}
	var c struct {
		CommandNodeCount int `json:"commandNodeCount"`
		CommandNodes     []struct {
			Command string `json:"command"`
		} `json:"commandNodes"`
	}
	if e = json.Unmarshal(raw, &c); e != nil {
		t.Fatal(e)
	}
	if c.CommandNodeCount != 69 || len(c.CommandNodes) != 69 {
		t.Fatalf("contract=%d/%d", c.CommandNodeCount, len(c.CommandNodes))
	}
	for _, n := range c.CommandNodes {
		if !seen[n.Command] {
			t.Fatalf("missing %s", n.Command)
		}
	}
}
func TestEveryFrozenPathParses(t *testing.T) {
	for _, s := range CommandSpecs {
		args := append([]string(nil), s.Path...)
		for _, a := range s.Arguments {
			if len(a.Options) > 0 && a.Required {
				args = append(args, a.Options[0], sample(a))
			}
			if len(a.Options) == 0 && a.Required {
				args = append(args, sample(a))
			}
		}
		for _, group := range s.RequireOneOfGroups {
			if len(group) == 0 {
				continue
			}
			for _, a := range s.Arguments {
				if a.Dest == group[0] && len(a.Options) > 0 {
					args = append(args, a.Options[0])
					break
				}
			}
		}
		inv, e := Parse(args)
		if e != nil {
			t.Fatalf("%s: %v args=%v", s.Command, e, args)
		}
		if inv.Spec.Command != s.Command {
			t.Fatalf("got=%s want=%s", inv.Spec.Command, s.Command)
		}
	}
}
func sample(a ArgumentSpec) string {
	if len(a.Choices) > 0 {
		return a.Choices[0]
	}
	if a.Type == "int" {
		return "1"
	}
	switch a.Dest {
	case "archive":
		return "/tmp/a.tar.zst"
	case "output":
		return "/tmp/module"
	case "topic":
		return "chroots"
	}
	return "value"
}
func TestGlobalOptionsAndAppend(t *testing.T) {
	inv, e := Parse([]string{"--config", "/tmp/c", "--dry-run", "--name", "demo", "install", "ubuntu", "--tool", "a", "--tool=b"})
	if e != nil {
		t.Fatal(e)
	}
	if inv.Globals.ConfigPath != "/tmp/c" || !inv.Globals.DryRun || inv.Globals.Name != "demo" {
		t.Fatalf("%+v", inv.Globals)
	}
	v := inv.Strings("tools")
	if len(v) != 2 || v[0] != "a" || v[1] != "b" {
		t.Fatalf("%v", v)
	}
}
func TestRemainderConsumesDashOptionsAfterCommand(t *testing.T) {
	inv, e := Parse([]string{"exec", "printf", "-v", "x"})
	if e != nil {
		t.Fatal(e)
	}
	v := inv.Strings("argv")
	if len(v) != 3 || v[1] != "-v" {
		t.Fatalf("%v", v)
	}
}

func TestRemainderPreservesDashArguments(t *testing.T) {
	inv, e := Parse([]string{"exec", "--", "printf", "--foo"})
	if e != nil {
		t.Fatal(e)
	}
	v := inv.Strings("argv")
	if len(v) != 2 || v[1] != "--foo" {
		t.Fatalf("%v", v)
	}
}
func TestInvalidChoiceFails(t *testing.T) {
	if _, e := Parse([]string{"install", "debian"}); e == nil {
		t.Fatal("expected error")
	}
}
