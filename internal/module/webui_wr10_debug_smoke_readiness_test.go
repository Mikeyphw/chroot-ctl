package module
import("os";"path/filepath";"strings";"testing")
func TestWebUIWR10DebugSmokeReadinessParity(t *testing.T){
 read:=func(n string)string{b,e:=os.ReadFile(filepath.Join("webroot",n));if e!=nil{t.Fatal(e)};return string(b)}
 b,j,h:=read("chrootctl.js"),read("index.js"),read("index.html"); all:=b+j+h
 for _,x:=range []string{"debug.probes","debug.timeline","debug.export","smoke.plan","smoke.preview","smoke.run","smoke.report","smoke.last_result","smoke.result.persist","smoke.result.export","smoke.failure.bundle","release.readiness"}{if !strings.Contains(all,x){t.Fatalf("missing WR10 contract %q",x)}}
 for _,x:=range []string{"Review exact plan","read-only","cancelOperation(diagnosticsState.operationId)","Failure bundle","Root-module diagnostics"}{if !strings.Contains(all,x){t.Fatalf("missing WR10 UI/safety %q",x)}}
 if strings.Contains(h,`id="smoke-archive"`)||strings.Contains(h,`id="debug-archive"`){t.Fatal("managed evidence must not expose arbitrary archive paths")}
}
