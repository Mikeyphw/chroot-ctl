package main

import (
	"flag"
	"fmt"
	"os"
	"strconv"

	"chrootctl/internal/repoctl"
)

func usage() {
	fmt.Fprintln(os.Stderr, "usage: repoctl <build-runtime|build-module|build-source|validate|release|doctor-cross-arch> [options]")
}
func fail(err error) { fmt.Fprintln(os.Stderr, "repoctl:", err); os.Exit(1) }
func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "build-runtime":
		fs := flag.NewFlagSet("build-runtime", flag.ExitOnError)
		out := fs.String("output-root", "out/native-runtime", "")
		jobs := fs.Int("jobs", 2, "")
		cc := fs.String("cc", "", "")
		fs.Parse(os.Args[2:])
		path, e := repoctl.BuildRuntime(repoctl.RuntimeOptions{OutputRoot: *out, Jobs: *jobs, CC: *cc})
		if e != nil {
			fail(e)
		}
		fmt.Println(path)
	case "build-module":
		fs := flag.NewFlagSet("build-module", flag.ExitOnError)
		out := fs.String("output-dir", "out/module", "")
		zip := fs.String("zip", "chrootctl-magisk.zip", "")
		zipCompat := fs.String("zip-path", "", "")
		runtime := fs.String("runtime-dir", "", "")
		runtimeCompat := fs.String("native-runtime-dir", "", "")
		jobs := fs.Int("jobs", 2, "")
		install := fs.Bool("install", false, "")
		installShort := fs.Bool("i", false, "")
		checksum := fs.Bool("checksum", false, "")
		fs.Parse(os.Args[2:])
		if *zipCompat != "" {
			*zip = *zipCompat
		}
		if *runtimeCompat != "" {
			*runtime = *runtimeCompat
		}
		path, e := repoctl.BuildModule(repoctl.ModuleOptions{OutputDir: *out, ZipPath: *zip, RuntimeDir: *runtime, Jobs: *jobs, Install: *install || *installShort, Checksum: *checksum})
		if e != nil {
			fail(e)
		}
		fmt.Println(path)
	case "build-source":
		fs := flag.NewFlagSet("build-source", flag.ExitOnError)
		version := fs.String("version", "dev", "")
		out := fs.String("output", "", "")
		checksum := fs.Bool("checksum", false, "")
		fs.Parse(os.Args[2:])
		path, e := repoctl.BuildSource(repoctl.SourceOptions{Version: *version, Output: *out, Checksum: *checksum})
		if e != nil {
			fail(e)
		}
		fmt.Println(path)
	case "validate":
		if e := repoctl.Validate(); e != nil {
			fail(e)
		}
	case "release":
		fs := flag.NewFlagSet("release", flag.ExitOnError)
		version := fs.String("version", "dev", "")
		dist := fs.String("dist", "dist", "")
		jobs := fs.Int("jobs", 2, "")
		fs.Parse(os.Args[2:])
		if e := repoctl.Release(repoctl.ReleaseOptions{Version: *version, DistDir: *dist, Jobs: *jobs}); e != nil {
			fail(e)
		}
	case "doctor-cross-arch":
		fs := flag.NewFlagSet("doctor-cross-arch", flag.ExitOnError)
		var arches multi
		fs.Var(&arches, "arch", "")
		fs.Parse(os.Args[2:])
		if e := repoctl.DoctorCrossArch(arches); e != nil {
			fail(e)
		}
	case "host":
		fmt.Println(repoctl.HostSummary())
	default:
		usage()
		os.Exit(2)
	}
}

type multi []string

func (m *multi) String() string { return fmt.Sprint([]string(*m)) }
func (m *multi) Set(v string) error {
	if v == "" {
		return fmt.Errorf("empty arch")
	}
	if _, e := strconv.Atoi(v); e == nil {
		return fmt.Errorf("invalid arch %q", v)
	}
	*m = append(*m, v)
	return nil
}
