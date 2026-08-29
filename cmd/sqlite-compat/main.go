package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"chrootctl/internal/sqlitecompat"
)

func main() {
	os.Exit(run(os.Args[1:]))
}

func run(args []string) int {
	flags := flag.NewFlagSet("sqlite-compat", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	dbPath := flags.String("db", "", "path to an existing chrootctl registry database")
	mutate := flags.Bool("mutate", false, "apply the deterministic GO02 round-trip mutation")
	if err := flags.Parse(args); err != nil {
		return 2
	}
	if *dbPath == "" {
		fmt.Fprintln(os.Stderr, "sqlite-compat: --db is required")
		return 2
	}
	if flags.NArg() != 0 {
		fmt.Fprintf(os.Stderr, "sqlite-compat: unexpected arguments: %v\n", flags.Args())
		return 2
	}

	db, err := sqlitecompat.Open(*dbPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "sqlite-compat:", err)
		return 1
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	before, err := sqlitecompat.Probe(ctx, db)
	if err != nil {
		fmt.Fprintln(os.Stderr, "sqlite-compat probe:", err)
		return 1
	}
	if *mutate {
		if err := sqlitecompat.MutatePythonFixture(ctx, db); err != nil {
			fmt.Fprintln(os.Stderr, "sqlite-compat mutate:", err)
			return 1
		}
	}
	after, err := sqlitecompat.Probe(ctx, db)
	if err != nil {
		fmt.Fprintln(os.Stderr, "sqlite-compat post-mutation probe:", err)
		return 1
	}
	payload := map[string]any{"schemaVersion": 1, "mutated": *mutate, "before": before, "after": after}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(payload); err != nil {
		fmt.Fprintln(os.Stderr, "sqlite-compat encode:", err)
		return 1
	}
	return 0
}
