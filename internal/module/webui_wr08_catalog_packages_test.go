package module
import("os";"path/filepath";"strings";"testing")
func TestWebUIWR08CatalogPackagesParity(t *testing.T){
 read:=func(n string)string{b,e:=os.ReadFile(filepath.Join("webroot",n));if e!=nil{t.Fatal(e)};return string(b)}
 b,j,h:=read("chrootctl.js"),read("index.js"),read("index.html")
 for _,x:=range []string{"catalog.search","packages.inventory","packages.compare","catalog.preview","catalog.apply","A fresh catalog preview is required"}{if !strings.Contains(b,x){t.Fatalf("missing contract %q",x)}}
 for _,x:=range []string{"risk_level","rollback","state_reason","destructive","loadPackages","comparePackages","cancelOperation(catalogState.operationId)"}{if !strings.Contains(j,x){t.Fatalf("missing catalog/package parity %q",x)}}
 for _,x:=range []string{`id="catalog-panel"`,`data-section="catalog"`,`id="packages-output"`}{if !strings.Contains(h,x){t.Fatalf("missing surface %q",x)}}
}
