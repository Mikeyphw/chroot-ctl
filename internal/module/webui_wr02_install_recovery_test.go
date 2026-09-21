package module

import (
 "os"
 "path/filepath"
 "strings"
 "testing"
)

func TestWebUIWR02InstallAdvancedRecoveryParity(t *testing.T) {
 read := func(name string) string { b, err := os.ReadFile(filepath.Join("webroot", name)); if err != nil { t.Fatal(err) }; return string(b) }
 html, ui, bridge := read("index.html"), read("index.js"), read("chrootctl.js")
 for _, want := range []string{"create-release", "create-version", "create-resume", "create-repair", "create-overwrite"} { if !strings.Contains(html,want) { t.Fatalf("advanced install control missing %q",want) } }
 for _, want := range []string{"release:$('create-release')", "version:$('create-version')", "resume:$('create-resume').checked", "repair:$('create-repair').checked", "overwriteExisting:$('create-overwrite').checked", "Resume and Repair cannot both be enabled", "request.repair?'Repair':request.resume?'Resume':'Fresh install'"} { if !strings.Contains(ui,want) { t.Fatalf("advanced/recovery install wiring missing %q",want) } }
 for _, want := range []string{"payload.resume===true", "payload.repair===true", "payload.overwriteExisting===true||payload.overwrite_existing===true", "['release','version']"} { if !strings.Contains(bridge,want) { t.Fatalf("safe install bridge missing %q",want) } }
}
