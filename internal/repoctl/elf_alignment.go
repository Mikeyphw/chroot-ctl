package repoctl

import (
	"debug/elf"
	"fmt"
)

func verifyELFLoadAlignment(path string, min uint64) error {
	ef, err := elf.Open(path)
	if err != nil {
		return err
	}
	defer ef.Close()
	seen := false
	for _, p := range ef.Progs {
		if p.Type != elf.PT_LOAD {
			continue
		}
		seen = true
		if p.Align < min || p.Align%min != 0 {
			return fmt.Errorf("Android ELF PT_LOAD p_align=%d requires %d", p.Align, min)
		}
	}
	if !seen {
		return fmt.Errorf("Android ELF contains no PT_LOAD segments")
	}
	return nil
}
