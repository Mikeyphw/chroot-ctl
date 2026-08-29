package main

import (
	"context"
	"fmt"
	"os"

	"chrootctl/internal/bridge"
	"chrootctl/internal/version"
)

func main() { os.Exit(run(os.Args[1:])) }
func run(args []string) int {
	if len(args) == 1 && (args[0] == "--version" || args[0] == "version") {
		fmt.Printf("chrootctl %s (Go migration scaffold, commit %s; Python baseline %s)\n", version.Version, version.Commit, version.PythonBaseline)
		return 0
	}
	if len(args) > 0 && args[0] == "app" {
		return bridge.RunApp(context.Background(), args[1:], os.Stdin, os.Stdout, os.Stderr)
	}
	fmt.Fprintln(os.Stderr, "chrootctl: Go bridge parity is available through `chrootctl app`; the human CLI remains Python-authoritative until GO11")
	return 64
}
