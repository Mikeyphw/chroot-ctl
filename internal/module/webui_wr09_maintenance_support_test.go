package module
import("os";"path/filepath";"strings";"testing")
func TestWebUIWR09MaintenanceSupportParity(t *testing.T){
 read:=func(n string)string{b,e:=os.ReadFile(filepath.Join("webroot",n));if e!=nil{t.Fatal(e)};return string(b)}
 b,j,h:=read("chrootctl.js"),read("index.js"),read("index.html")
 for _,x:=range []string{"system.runtime","system.module_status","support.preview","support.bundle","repair.preview","repair.apply","cleanup.temp_preview","cleanup.temp","A fresh maintenance preview is required"}{if !strings.Contains(b,x){t.Fatalf("missing maintenance contract %q",x)}}
 for _,x:=range []string{"expected_path","diff_lines","Global registry","managed artifact","cancelOperation(maintenanceState.operationId)"}{if !strings.Contains(j+h,x){t.Fatalf("missing maintenance safety/parity %q",x)}}
 if strings.Contains(h,`name="archive"`)||strings.Contains(h,`id="support-archive"`){t.Fatal("support UI must not accept arbitrary archive paths")}
}
