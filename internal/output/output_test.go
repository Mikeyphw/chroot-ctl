package output

import (
	"os"
	"strings"
	"testing"
)

func TestWidthsAndJSON(t *testing.T) {
	old := os.Getenv("PREFIX")
	defer os.Setenv("PREFIX", old)
	_ = os.Setenv("PREFIX", "/data/data/com.termux/files/usr")
	if EffectiveWidth(120) != 80 || EffectiveWidth(5) != 20 {
		t.Fatal()
	}
	j, e := JSON(map[string]int{"b": 2})
	if e != nil || !strings.Contains(j, "\"b\": 2") {
		t.Fatal(j, e)
	}
	if !strings.Contains(WrapText("one two three four five six seven", 20), "\n") {
		t.Fatal()
	}
}
