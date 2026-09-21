package repoctl
import("fmt";"io/fs";"os";"path/filepath";"strings")
func treeHasFiles(root string) (bool,error){
 found:=false
 err:=filepath.WalkDir(root,func(path string,d fs.DirEntry,err error)error{
  if err!=nil {if os.IsNotExist(err){return nil};return err}
  if !d.IsDir(){found=true}
  return nil
 })
 if os.IsNotExist(err){return false,nil};return found,err
}
func ValidateRootModuleRetirement(root string) error {
 retiredFiles:=[]string{
  "android/settings.gradle.kts","android/build.gradle.kts","android/gradlew","android/gradlew.bat",
  "android/gradle.properties","android/gradle/libs.versions.toml","android/app/build.gradle.kts",
  "android/app/src/main/AndroidManifest.xml",
 }
 for _,rel:=range retiredFiles{if st,err:=os.Stat(filepath.Join(root,rel));err==nil&&!st.IsDir(){return fmt.Errorf("WR12 retired standalone Android product file returned: %s",rel)}else if err!=nil&&!os.IsNotExist(err){return err}}
 for _,rel:=range []string{"android/app/src/main","android/app/src/test","android/app/src/androidTest"}{has,err:=treeHasFiles(filepath.Join(root,rel));if err!=nil{return err};if has{return fmt.Errorf("WR12 retired standalone Android product files returned under: %s",rel)}}
 raw,err:=os.ReadFile(filepath.Join(root,".devtool.toml"));if err!=nil{return err};s:=string(raw)
 for _,bad:=range []string{"[targets.chrootctl_android]","chrootctlAndroidAppSeal"}{if strings.Contains(s,bad){return fmt.Errorf("WR12 retired Devtool contract returned: %s",bad)}}
 for _,need:=range []string{"[targets.chrootctl_root_module]","internal/module/**","internal/bridge/**","build-module","chrootctl-magisk.zip"}{if !strings.Contains(s,need){return fmt.Errorf("WR12 root-module authority missing %q",need)}}
 ci,err:=os.ReadFile(filepath.Join(root,".github","workflows","ci.yml"));if err!=nil{return err}
 if strings.Contains(string(ci),"\n  android:\n")||strings.Contains(string(ci),"chrootctlAndroidAppSeal"){return fmt.Errorf("WR12 retired APK CI path returned")}
 return nil
}
