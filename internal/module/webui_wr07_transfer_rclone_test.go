package module
import("os";"path/filepath";"strings";"testing")
func TestWebUIWR07TransferRcloneParity(t *testing.T){
 read:=func(n string)string{b,e:=os.ReadFile(filepath.Join("webroot",n));if e!=nil{t.Fatal(e)};return string(b)}
 b,j,h:=read("chrootctl.js"),read("index.js"),read("index.html")
 for _,x:=range []string{"transfer.import_preview","transfer.preview_export","transfer.${kind}","remote.rclone.status","remote.rclone.list","remote.rclone.config_import","WEBUI_PREVIEW_REQUIRED"}{if !strings.Contains(b,x){t.Fatalf("missing transfer/rclone contract %q",x)}}
 for _,x:=range []string{"importRemoteHandoff","exportRemoteHandoff","rcloneTransferPath","clearTransferPassword","scrubTransferPayload","rclone-config-cancel","cancelOperation(rcloneState.configOperationId)"}{if !strings.Contains(j+h,x){t.Fatalf("missing transfer/rclone UI safety %q",x)}}
 if strings.Contains(j,`type="text" id="transfer-import-password"`)||strings.Contains(j,`type="text" id="transfer-export-password"`){t.Fatal("transfer password rendered as text")}
}
