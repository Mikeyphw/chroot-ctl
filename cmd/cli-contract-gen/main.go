package main

import (
	"flag"
	"fmt"
	"os"

	"chrootctl/internal/contractgen"
)

func main() {
	check := flag.Bool("check", false, "verify generated CLI contract artifacts are current")
	root := flag.String("root", ".", "repository root")
	flag.Parse()
	var err error
	if *check {
		err = contractgen.Check(*root)
	} else {
		err = contractgen.Write(*root)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "cli-contract-gen:", err)
		os.Exit(1)
	}
}
