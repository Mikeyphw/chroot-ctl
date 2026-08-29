package main

import (
	"context"
	"fmt"
	"os"

	"chrootctl/internal/cli"
	"chrootctl/internal/version"
)

func main() { os.Exit(run(os.Args[1:])) }
func run(args []string) int {
	if len(args) == 1 && (args[0] == "--version" || args[0] == "version") {
		fmt.Printf("chrootctl %s (Go native backend, commit %s)\n", version.Version, version.Commit)
		return 0
	}
	return cli.Run(context.Background(), args, os.Stdin, os.Stdout, os.Stderr)
}
