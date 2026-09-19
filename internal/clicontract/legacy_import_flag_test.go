package clicontract

import "testing"

func TestLegacyMetadataFlagIsExplicitOnImportAndInspect(t *testing.T) {
	wanted := map[string]bool{
		"chroots import":   false,
		"transfer import":  false,
		"transfer inspect": false,
	}
	for _, spec := range CommandSpecs {
		if _, ok := wanted[spec.Command]; !ok {
			continue
		}
		for _, arg := range spec.Arguments {
			if arg.Dest == "allow_legacy_metadata" {
				if arg.Action != "_StoreTrueAction" {
					t.Fatalf("%s legacy flag action=%q", spec.Command, arg.Action)
				}
				wanted[spec.Command] = true
			}
		}
	}
	for command, found := range wanted {
		if !found {
			t.Fatalf("%s is missing --allow-legacy-metadata", command)
		}
	}
}
