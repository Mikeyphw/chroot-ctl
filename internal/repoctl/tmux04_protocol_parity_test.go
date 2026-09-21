package repoctl

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestTmux04SessionProtocolAndCLIParity(t *testing.T) {
	root := filepath.Join("..", "..")
	raw, err := os.ReadFile(filepath.Join(root, "migration", "contracts", "v1", "bridge.json"))
	if err != nil {
		t.Fatal(err)
	}
	var bridge struct {
		OperationCount int                           `json:"operationCount"`
		ArbitraryShell bool                          `json:"arbitraryShell"`
		Operations     []struct{ Name, Mode string } `json:"operations"`
	}
	if err := json.Unmarshal(raw, &bridge); err != nil {
		t.Fatal(err)
	}
	if bridge.OperationCount != 99 || len(bridge.Operations) != 99 {
		t.Fatalf("bridge operation count=%d decoded=%d", bridge.OperationCount, len(bridge.Operations))
	}
	if bridge.ArbitraryShell {
		t.Fatal("generic app bridge must remain arbitraryShell=false")
	}
	want := map[string]string{"sessions.list": "query", "sessions.get": "query", "sessions.create": "operation", "sessions.capture": "query", "sessions.input": "operation", "sessions.detach": "operation", "sessions.kill": "operation", "sessions.reconcile": "operation", "sessions.runtime": "query"}
	for _, op := range bridge.Operations {
		if mode, ok := want[op.Name]; ok {
			if op.Mode != mode {
				t.Fatalf("%s mode=%s want=%s", op.Name, op.Mode, mode)
			}
			delete(want, op.Name)
		}
	}
	if len(want) != 0 {
		t.Fatalf("missing session operations: %#v", want)
	}

	raw, err = os.ReadFile(filepath.Join(root, "migration", "contracts", "v1", "cli.json"))
	if err != nil {
		t.Fatal(err)
	}
	var cli struct {
		CommandNodeCount int                                 `json:"commandNodeCount"`
		CommandNodes     []struct{ Command, Handler string } `json:"commandNodes"`
	}
	if err := json.Unmarshal(raw, &cli); err != nil {
		t.Fatal(err)
	}
	if cli.CommandNodeCount != 92 || len(cli.CommandNodes) != 92 {
		t.Fatalf("cli command count=%d decoded=%d", cli.CommandNodeCount, len(cli.CommandNodes))
	}
	commands := map[string]bool{"sessions": false, "sessions list": false, "sessions get": false, "sessions create": false, "sessions capture": false, "sessions detach": false, "sessions kill": false, "sessions reconcile": false, "sessions runtime": false}
	for _, n := range cli.CommandNodes {
		if _, ok := commands[n.Command]; ok {
			if n.Handler != "sessions" {
				t.Fatalf("%s handler=%s", n.Command, n.Handler)
			}
			commands[n.Command] = true
		}
	}
	for name, ok := range commands {
		if !ok {
			t.Fatalf("missing CLI command %s", name)
		}
	}
}
