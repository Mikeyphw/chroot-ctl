package output

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
)

const (
	TermuxWidthCap      = 80
	MinWidth            = 20
	NarrowWidth         = 72
	CompactCatalogWidth = 88
)

func IsTermux() bool {
	p := os.Getenv("PREFIX")
	return strings.Contains(p, "com.termux") || strings.HasSuffix(p, "/usr")
}
func EffectiveWidth(width int) int {
	if width <= 0 {
		width = 80
	}
	if IsTermux() && width > TermuxWidthCap {
		width = TermuxWidthCap
	}
	if width < MinWidth {
		width = MinWidth
	}
	return width
}
func WrapText(text string, width int) string {
	width = EffectiveWidth(width)
	if text == "" {
		return ""
	}
	words := strings.Fields(text)
	if len(words) == 0 {
		return ""
	}
	lines := []string{}
	line := ""
	for _, w := range words {
		if line == "" {
			line = w
			continue
		}
		if len(line)+1+len(w) <= width {
			line += " " + w
		} else {
			lines = append(lines, line)
			line = w
		}
	}
	if line != "" {
		lines = append(lines, line)
	}
	return strings.Join(lines, "\n")
}
func JSON(value any) (string, error) {
	b, e := json.MarshalIndent(value, "", "  ")
	if e != nil {
		return "", e
	}
	return string(b) + "\n", nil
}
func CompactRows(title string, rows []map[string]string) string {
	var b strings.Builder
	fmt.Fprintln(&b, title)
	for i, row := range rows {
		label := fmt.Sprintf("item %d", i+1)
		for _, k := range []string{"name", "check", "username", "target", "category", "kind"} {
			if row[k] != "" {
				label = row[k]
				break
			}
		}
		fmt.Fprintf(&b, "[%s]\n", label)
		keys := make([]string, 0, len(row))
		for k := range row {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			fmt.Fprintf(&b, "%s=%s\n", k, row[k])
		}
	}
	return b.String()
}
