package module
import("os";"path/filepath";"strings";"testing")
func TestWR12StandaloneAndroidAppStaysRetired(t *testing.T){
 root:=filepath.Clean(filepath.Join("..",".."))
 retiredFiles:=[]string{
  "android/settings.gradle.kts","android/build.gradle.kts","android/gradlew","android/gradlew.bat",
  "android/gradle.properties","android/gradle/libs.versions.toml","android/app/build.gradle.kts",
  "android/app/src/main/AndroidManifest.xml",
 }
 for _,rel:=range retiredFiles{if st,e:=os.Stat(filepath.Join(root,rel));e==nil&&!st.IsDir(){t.Fatalf("standalone Android product file returned: %s",rel)}else if e!=nil&&!os.IsNotExist(e){t.Fatal(e)}}
 for _,tree:=range []string{"android/app/src/main","android/app/src/test","android/app/src/androidTest"}{
  dir:=filepath.Join(root,tree);found:=false
  _=filepath.WalkDir(dir,func(path string,d os.DirEntry,err error)error{if err==nil&&!d.IsDir(){found=true};return nil})
  if found{t.Fatalf("standalone Android product files returned under: %s",tree)}
 }
 toml,e:=os.ReadFile(filepath.Join(root,".devtool.toml"));if e!=nil{t.Fatal(e)}
 if strings.Contains(string(toml),"targets.chrootctl_android"){t.Fatal("retired chrootctl_android Devtool target returned")}
 ci,e:=os.ReadFile(filepath.Join(root,".github","workflows","ci.yml"));if e!=nil{t.Fatal(e)}
 if strings.Contains(string(ci),"\n  android:\n")||strings.Contains(string(ci),"chrootctlAndroidAppSeal"){t.Fatal("retired APK CI job returned")}
 repoctl,e:=os.ReadFile(filepath.Join(root,"internal","repoctl","repoctl.go"));if e!=nil{t.Fatal(e)}
 if !strings.Contains(string(repoctl),"ValidateRootModuleRetirement(root)"){t.Fatal("active repoctl validation does not enforce WR12 retirement")}
}
