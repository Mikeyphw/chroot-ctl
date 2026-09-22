package module

import (
	"os"
	"strings"
	"testing"
)

func TestPostCUXFlatSurfaceVisualContract(t *testing.T) {
	cssBytes, err := os.ReadFile("webroot/index.css")
	if err != nil {
		t.Fatal(err)
	}
	css := string(cssBytes)
	marker := "Post-CUX flat-surface visual convergence: BKX-inspired, borderless hierarchy."
	pos := strings.LastIndex(css, marker)
	if pos < 0 {
		t.Fatalf("missing flat-surface convergence marker")
	}
	flat := css[pos:]
	required := []string{
		"--bg: #080909",
		"--surface: #1d1b18",
		"--surface-2: #292620",
		"--accent: #b9ca7b",
		".card,",
		"background-image: none !important",
		"box-shadow: none !important",
		"border: 0 !important",
		".button.primary",
		".product-nav",
		".operation-row.needs-attention",
		"Focus remains an outline",
		"outline: 3px solid var(--accent)",
	}
	for _, token := range required {
		if !strings.Contains(flat, token) {
			t.Fatalf("flat-surface contract missing %q", token)
		}
	}
	forbidden := []string{
		"linear-gradient(",
		"box-shadow: 0 ",
		"border: 1px",
		"border-top: 1px",
		"border-right: 1px",
		"border-bottom: 1px",
		"border-left: 1px",
	}
	for _, token := range forbidden {
		if strings.Contains(flat, token) {
			t.Fatalf("flat-surface override reintroduces visible chrome %q", token)
		}
	}

	htmlBytes, err := os.ReadFile("webroot/index.html")
	if err != nil {
		t.Fatal(err)
	}
	html := string(htmlBytes)
	if !strings.Contains(html, `<meta name="theme-color" content="#080909">`) {
		t.Fatal("WebView theme color does not match the flat near-black canvas")
	}
}
