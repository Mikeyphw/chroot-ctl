package module
import("os";"path/filepath";"strings";"testing")
func TestWebUIWR11CompatibilityHardening(t *testing.T){
 read:=func(n string)string{b,e:=os.ReadFile(filepath.Join("webroot",n));if e!=nil{t.Fatal(e)};return string(b)}
 b,j,h:=read("chrootctl.js"),read("index.js"),read("index.html")
 for _,x:=range []string{"app','capabilities","REQUIRED_PROTOCOL_VERSION=1","WEBUI_PROTOCOL_INCOMPATIBLE","WEBUI_UNSAFE_BACKEND","WEBUI_CAPABILITY_UNAVAILABLE","requireCapability(operation,mode)"}{if !strings.Contains(b,x){t.Fatalf("missing compatibility guard %q",x)}}
 for _,x:=range []string{"loadCompatibility","supportsOperation","Advertised operations","aria-live=\"polite\"","role=\"status\""}{if !strings.Contains(j+h,x){t.Fatalf("missing compatibility/accessibility surface %q",x)}}
 if !strings.Contains(b,"arbitraryShell===true"){t.Fatal("unsafe arbitrary-shell backend is not rejected")}
}
