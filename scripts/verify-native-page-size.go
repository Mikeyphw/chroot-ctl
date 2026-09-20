package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"encoding/binary"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"strings"
)

const (
	elfMagic  = "\x7fELF"
	ptLoad    = uint32(1)
	etDyn     = uint16(3)
	emAarch64 = uint16(183)
)

type loadSegment struct {
	Index  int
	Offset uint64
	Vaddr  uint64
	Align  uint64
}

type elfInfo struct {
	Class   byte
	Data    byte
	Type    uint16
	Machine uint16
	Loads   []loadSegment
}

func orderFor(data byte) (binary.ByteOrder, error) {
	switch data {
	case 1:
		return binary.LittleEndian, nil
	case 2:
		return binary.BigEndian, nil
	default:
		return nil, fmt.Errorf("unsupported ELF data encoding %d", data)
	}
}

func u16(b []byte, off int, order binary.ByteOrder) (uint16, error) {
	if off < 0 || off+2 > len(b) {
		return 0, errors.New("truncated ELF header")
	}
	return order.Uint16(b[off : off+2]), nil
}
func u32(b []byte, off int, order binary.ByteOrder) (uint32, error) {
	if off < 0 || off+4 > len(b) {
		return 0, errors.New("truncated ELF header")
	}
	return order.Uint32(b[off : off+4]), nil
}
func u64(b []byte, off int, order binary.ByteOrder) (uint64, error) {
	if off < 0 || off+8 > len(b) {
		return 0, errors.New("truncated ELF header")
	}
	return order.Uint64(b[off : off+8]), nil
}

func parseELF(b []byte) (elfInfo, error) {
	var out elfInfo
	if len(b) < 20 || string(b[:4]) != elfMagic {
		return out, errors.New("not an ELF file")
	}
	out.Class, out.Data = b[4], b[5]
	order, err := orderFor(out.Data)
	if err != nil {
		return out, err
	}
	out.Type, err = u16(b, 16, order)
	if err != nil {
		return out, err
	}
	out.Machine, err = u16(b, 18, order)
	if err != nil {
		return out, err
	}

	var phoff uint64
	var phentsize, phnum uint16
	var expected int
	switch out.Class {
	case 2:
		if len(b) < 64 {
			return out, errors.New("truncated ELF64 header")
		}
		phoff, err = u64(b, 32, order)
		if err != nil {
			return out, err
		}
		phentsize, err = u16(b, 54, order)
		if err != nil {
			return out, err
		}
		phnum, err = u16(b, 56, order)
		if err != nil {
			return out, err
		}
		expected = 56
	case 1:
		if len(b) < 52 {
			return out, errors.New("truncated ELF32 header")
		}
		v, e := u32(b, 28, order)
		if e != nil {
			return out, e
		}
		phoff = uint64(v)
		phentsize, err = u16(b, 42, order)
		if err != nil {
			return out, err
		}
		phnum, err = u16(b, 44, order)
		if err != nil {
			return out, err
		}
		expected = 32
	default:
		return out, fmt.Errorf("unsupported ELF class %d", out.Class)
	}
	if int(phentsize) < expected {
		return out, fmt.Errorf("program-header entry is too small (%d < %d)", phentsize, expected)
	}
	end := phoff + uint64(phentsize)*uint64(phnum)
	if phoff > uint64(len(b)) || end > uint64(len(b)) {
		return out, errors.New("program-header table is outside file")
	}

	for i := 0; i < int(phnum); i++ {
		off := int(phoff) + i*int(phentsize)
		typ, e := u32(b, off, order)
		if e != nil {
			return out, e
		}
		if typ != ptLoad {
			continue
		}
		var pOff, vaddr, align uint64
		if out.Class == 2 {
			pOff, e = u64(b, off+8, order)
			if e != nil {
				return out, e
			}
			vaddr, e = u64(b, off+16, order)
			if e != nil {
				return out, e
			}
			align, e = u64(b, off+48, order)
			if e != nil {
				return out, e
			}
		} else {
			x, e2 := u32(b, off+4, order)
			if e2 != nil {
				return out, e2
			}
			pOff = uint64(x)
			x, e2 = u32(b, off+8, order)
			if e2 != nil {
				return out, e2
			}
			vaddr = uint64(x)
			x, e2 = u32(b, off+28, order)
			if e2 != nil {
				return out, e2
			}
			align = uint64(x)
		}
		out.Loads = append(out.Loads, loadSegment{Index: i, Offset: pOff, Vaddr: vaddr, Align: align})
	}
	if len(out.Loads) == 0 {
		return out, errors.New("ELF has no PT_LOAD segments")
	}
	return out, nil
}

func verifyELFBytes(b []byte, label string, min uint64) []string {
	info, err := parseELF(b)
	if err != nil {
		return []string{fmt.Sprintf("%s: %v", label, err)}
	}
	var problems []string
	for _, s := range info.Loads {
		if s.Align < min {
			problems = append(problems, fmt.Sprintf("%s: PT_LOAD[%d] p_align=0x%x is below 0x%x", label, s.Index, s.Align, min))
		}
		if s.Offset%min != s.Vaddr%min {
			problems = append(problems, fmt.Sprintf("%s: PT_LOAD[%d] file/vaddr are not congruent modulo 0x%x (offset=0x%x, vaddr=0x%x)", label, s.Index, min, s.Offset, s.Vaddr))
		}
	}
	return problems
}

func validMin(n uint64) bool               { return n > 0 && n&(n-1) == 0 }
func readFile(name string) ([]byte, error) { return os.ReadFile(name) }
func printProblems(problems []string) bool {
	for _, p := range problems {
		fmt.Fprintln(os.Stderr, p)
	}
	return len(problems) != 0
}

func elfCommand(args []string) int {
	fs := flag.NewFlagSet("elf", flag.ContinueOnError)
	min := fs.Uint64("min-page-size", 16384, "minimum page size")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if !validMin(*min) || fs.NArg() == 0 {
		fmt.Fprintln(os.Stderr, "elf: min page size must be a power of two and at least one path is required")
		return 2
	}
	failed := false
	for _, name := range fs.Args() {
		b, err := readFile(name)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%s: %v\n", name, err)
			failed = true
			continue
		}
		problems := verifyELFBytes(b, name, *min)
		if printProblems(problems) {
			failed = true
		} else {
			fmt.Printf("16 KiB ELF alignment: PASS: %s\n", name)
		}
	}
	if failed {
		return 1
	}
	return 0
}

func runtimeCommand(args []string) int {
	fs := flag.NewFlagSet("runtime", flag.ContinueOnError)
	min := fs.Uint64("min-page-size", 16384, "minimum page size")
	version := fs.String("version", "", "required embedded rclone version without leading v")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if !validMin(*min) || *version == "" || fs.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "runtime: --version, power-of-two --min-page-size and one path are required")
		return 2
	}
	name := fs.Arg(0)
	b, err := readFile(name)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s: %v\n", name, err)
		return 1
	}
	info, err := parseELF(b)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s: %v\n", name, err)
		return 1
	}
	problems := verifyELFBytes(b, name, *min)
	if info.Class != 2 || info.Data != 1 {
		problems = append(problems, fmt.Sprintf("%s: rclone runtime must be little-endian ELF64", name))
	}
	if info.Type != etDyn {
		problems = append(problems, fmt.Sprintf("%s: rclone runtime must be position-independent ET_DYN (e_type=%d)", name, info.Type))
	}
	if info.Machine != emAarch64 {
		problems = append(problems, fmt.Sprintf("%s: rclone runtime is not AArch64 (e_machine=%d)", name, info.Machine))
	}
	marker := []byte("v" + *version)
	if !bytes.Contains(b, marker) {
		problems = append(problems, fmt.Sprintf("%s: rclone runtime is missing embedded version marker %s", name, marker))
	}
	if printProblems(problems) {
		return 1
	}
	fmt.Printf("chrootctl rclone runtime ELF/version/16 KiB contract: PASS: %s\n", name)
	return 0
}

func unsafeArchivePath(name string) bool {
	if name == "" || strings.HasPrefix(name, "/") {
		return true
	}
	clean := path.Clean(name)
	if clean == ".." || strings.HasPrefix(clean, "../") {
		return true
	}
	for _, part := range strings.Split(name, "/") {
		if part == ".." {
			return true
		}
	}
	return false
}

func archiveSafeCommand(args []string) int {
	if len(args) == 0 {
		fmt.Fprintln(os.Stderr, "archive-safe: at least one .tar.gz is required")
		return 2
	}
	failed := false
	for _, name := range args {
		f, err := os.Open(name)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%s: %v\n", name, err)
			failed = true
			continue
		}
		gz, err := gzip.NewReader(f)
		if err != nil {
			f.Close()
			fmt.Fprintf(os.Stderr, "%s: %v\n", name, err)
			failed = true
			continue
		}
		tr := tar.NewReader(gz)
		for {
			h, e := tr.Next()
			if e == io.EOF {
				break
			}
			if e != nil {
				fmt.Fprintf(os.Stderr, "%s: %v\n", name, e)
				failed = true
				break
			}
			if unsafeArchivePath(h.Name) {
				fmt.Fprintf(os.Stderr, "%s: unsafe archive member: %s\n", name, h.Name)
				failed = true
			}
			if (h.Typeflag == tar.TypeSymlink || h.Typeflag == tar.TypeLink) && unsafeArchivePath(h.Linkname) {
				fmt.Fprintf(os.Stderr, "%s: unsafe archive link target: %s -> %s\n", name, h.Name, h.Linkname)
				failed = true
			}
		}
		gz.Close()
		f.Close()
	}
	if failed {
		return 1
	}
	fmt.Println("chrootctl rclone release archive path safety: PASS")
	return 0
}

func apkCommand(args []string) int {
	fs := flag.NewFlagSet("apk", flag.ContinueOnError)
	min := fs.Uint64("min-page-size", 16384, "minimum page size")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if !validMin(*min) || fs.NArg() == 0 {
		fmt.Fprintln(os.Stderr, "apk: min page size must be a power of two and at least one APK is required")
		return 2
	}
	failed := false
	for _, name := range fs.Args() {
		zr, err := zip.OpenReader(name)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%s: %v\n", name, err)
			failed = true
			continue
		}
		nativeCount := 0
		required := map[string]bool{"libchrootctlgo.so": false, "rclone": false}
		var problems []string
		for _, f := range zr.File {
			if !strings.HasPrefix(f.Name, "lib/") || !strings.HasSuffix(f.Name, ".so") {
				continue
			}
			nativeCount++
			base := filepath.Base(f.Name)
			if _, ok := required[base]; ok {
				required[base] = true
			}
			rc, e := f.Open()
			if e != nil {
				problems = append(problems, fmt.Sprintf("%s!/%s: %v", name, f.Name, e))
				continue
			}
			b, e := io.ReadAll(rc)
			rc.Close()
			if e != nil {
				problems = append(problems, fmt.Sprintf("%s!/%s: %v", name, f.Name, e))
				continue
			}
			label := name + "!/" + f.Name
			problems = append(problems, verifyELFBytes(b, label, *min)...)
			if f.Method == zip.Store {
				off, e := f.DataOffset()
				if e != nil {
					problems = append(problems, fmt.Sprintf("%s: cannot determine APK payload offset: %v", label, e))
				} else if uint64(off)%*min != 0 {
					problems = append(problems, fmt.Sprintf("%s: uncompressed APK payload offset 0x%x is not aligned to 0x%x", label, off, *min))
				}
			}
		}
		zr.Close()
		if nativeCount == 0 {
			problems = append(problems, fmt.Sprintf("%s: APK contains no native libraries", name))
		}
		for lib, ok := range required {
			if !ok {
				problems = append(problems, fmt.Sprintf("%s: required chrootctl native runtime is missing: %s", name, lib))
			}
		}
		if printProblems(problems) {
			failed = true
		} else {
			fmt.Printf("16 KiB APK native-page-size contract: PASS: %s\n", name)
		}
	}
	if failed {
		return 1
	}
	return 0
}

func writeFixture(name string, align, offset, vaddr uint64) error {
	data := make([]byte, 0x5000)
	copy(data[:4], []byte(elfMagic))
	data[4] = 2
	data[5] = 1
	data[6] = 1
	binary.LittleEndian.PutUint16(data[16:18], etDyn)
	binary.LittleEndian.PutUint16(data[18:20], emAarch64)
	binary.LittleEndian.PutUint32(data[20:24], 1)
	binary.LittleEndian.PutUint64(data[32:40], 64)
	binary.LittleEndian.PutUint16(data[52:54], 64)
	binary.LittleEndian.PutUint16(data[54:56], 56)
	binary.LittleEndian.PutUint16(data[56:58], 1)
	ph := data[64:120]
	binary.LittleEndian.PutUint32(ph[0:4], ptLoad)
	binary.LittleEndian.PutUint32(ph[4:8], 5)
	binary.LittleEndian.PutUint64(ph[8:16], offset)
	binary.LittleEndian.PutUint64(ph[16:24], vaddr)
	binary.LittleEndian.PutUint64(ph[24:32], vaddr)
	binary.LittleEndian.PutUint64(ph[32:40], 1)
	binary.LittleEndian.PutUint64(ph[40:48], 1)
	binary.LittleEndian.PutUint64(ph[48:56], align)
	return os.WriteFile(name, data, 0o600)
}

func fixtureCommand(args []string) int {
	fs := flag.NewFlagSet("fixture", flag.ContinueOnError)
	good := fs.String("good", "", "path for a 16 KiB-compatible ELF fixture")
	bad := fs.String("bad", "", "path for a 4 KiB ELF fixture")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if *good == "" || *bad == "" {
		fmt.Fprintln(os.Stderr, "fixture: --good and --bad are required")
		return 2
	}
	if err := writeFixture(*good, 0x4000, 0x4000, 0x8000); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if err := writeFixture(*bad, 0x1000, 0x1000, 0x2000); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: verify-native-page-size.go <elf|runtime|apk|archive-safe|fixture> [options]")
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	var code int
	switch os.Args[1] {
	case "elf":
		code = elfCommand(os.Args[2:])
	case "runtime":
		code = runtimeCommand(os.Args[2:])
	case "apk":
		code = apkCommand(os.Args[2:])
	case "archive-safe":
		code = archiveSafeCommand(os.Args[2:])
	case "fixture":
		code = fixtureCommand(os.Args[2:])
	default:
		usage()
		code = 2
	}
	os.Exit(code)
}
