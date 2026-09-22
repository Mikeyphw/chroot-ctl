package ubuntu

import (
	"strings"
	"testing"
)

func TestParseReleaseAndTarball(t *testing.T) {
	html := `<a href="24.04/">24.04</a><a href="noble/">noble</a><a href="../">up</a>`
	r := ParseReleaseIndex(html)
	if len(r) != 2 {
		t.Fatalf("%+v", r)
	}
	name, url, e := ResolveTarball(`<a href="ubuntu-base-24.04-base-arm64.tar.gz">x</a>`, "arm64", "https://x/")
	if e != nil || !strings.Contains(name, "arm64") || url != "https://x/"+name {
		t.Fatalf("%s %s %v", name, url, e)
	}
}
func TestUnsupportedArch(t *testing.T) {
	if _, _, e := ResolveTarball("", "riscv64", "x"); e == nil {
		t.Fatal("expected")
	}
}

func TestTarballSuffixForArchMatchesResolverContract(t *testing.T) {
	tests := map[string]string{
		"arm64": "-base-arm64.tar.gz",
		"amd64": "-base-amd64.tar.gz",
	}
	for arch, want := range tests {
		if got := tarballSuffixForArch(arch); got != want {
			t.Fatalf("arch=%s suffix=%q want=%q", arch, got, want)
		}
	}
	if got := tarballSuffixForArch("riscv64"); got != "" {
		t.Fatalf("unsupported arch suffix=%q", got)
	}
}

func TestResolveTarballPrefersNewestPointRelease(t *testing.T) {
	html := `<a href="ubuntu-base-24.04.3-base-arm64.tar.gz">old</a>
<a href="ubuntu-base-24.04.5-base-arm64.tar.gz">current</a>
<a href="ubuntu-base-24.04.4-base-arm64.tar.gz">previous</a>`
	name, url, err := ResolveTarball(html, "arm64", "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/")
	if err != nil {
		t.Fatal(err)
	}
	if name != "ubuntu-base-24.04.5-base-arm64.tar.gz" {
		t.Fatalf("selected %q; want 24.04.5 artifact", name)
	}
	if !strings.HasSuffix(url, "/"+name) {
		t.Fatalf("url=%q", url)
	}
}

func TestResolveTarballUsesNumericVersionOrdering(t *testing.T) {
	html := `<a href="ubuntu-base-24.04.9-base-arm64.tar.gz">nine</a>
<a href="ubuntu-base-24.04.10-base-arm64.tar.gz">ten</a>`
	name, _, err := ResolveTarball(html, "arm64", "https://example.invalid/")
	if err != nil {
		t.Fatal(err)
	}
	if name != "ubuntu-base-24.04.10-base-arm64.tar.gz" {
		t.Fatalf("selected %q; want numeric 24.04.10", name)
	}
}

func TestResolveReleaseDefaultsToStableSeriesAlias(t *testing.T) {
	i := &Installer{}
	i.FetchText = func(url string) (string, error) {
		if url != ReleaseIndexURL {
			t.Fatalf("unexpected url=%q", url)
		}
		return `<a href="24.04.4/">24.04.4</a><a href="24.04.5/">24.04.5</a><a href="24.04/">24.04</a><a href="noble/">noble</a>`, nil
	}
	ref, err := i.resolveRelease("", "")
	if err != nil {
		t.Fatal(err)
	}
	if ref.Label != "24.04" || ref.URL != ReleaseIndexURL+"24.04/release/" {
		t.Fatalf("ref=%+v", ref)
	}
}

func TestTarballVersionReportsExactSelectedArtifact(t *testing.T) {
	version, ok := tarballVersion("ubuntu-base-24.04.5-base-arm64.tar.gz", "arm64")
	if !ok || version != "24.04.5" {
		t.Fatalf("version=%q ok=%v", version, ok)
	}
	if _, ok := tarballVersion("ubuntu-base-current-base-arm64.tar.gz", "arm64"); ok {
		t.Fatal("non-numeric tarball version should be rejected")
	}
}
