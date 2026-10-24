#!/system/bin/sh
# CC-09 read-only installed Chrootctl module proof. Run *on the Android device*
# after reboot and root-manager installation; no mutations, no secrets exported.
set -eu
fail() { echo "FAIL_CC09_DEVICE_SNAPSHOT: $*" >&2; exit 1; }

# A test-only override can validate this script on Linux fixture trees. Fixture
# outputs are explicitly disqualified from real-device acceptance.
MODE=device
ROOT=/data/adb/modules/chrootctl
if [ "${CHROOTCTL_DEVICE_PROBE_FIXTURE:-0}" = 1 ]; then
  MODE=fixture
  ROOT=${CHROOTCTL_DEVICE_PROBE_ROOT:?fixture root required}
else
  [ "$(id -u)" = 0 ] || fail 'root required for real device snapshot'
  [ "$(getprop ro.build.version.sdk)" -ge 26 ] || fail 'Android API below 26'
  [ "$(getprop sys.boot_completed)" = 1 ] || fail 'boot not complete'
  [ "$(getenforce)" = Enforcing ] || fail 'SELinux is not enforcing'
fi

[ -d "$ROOT" ] && [ ! -L "$ROOT" ] || fail 'active module directory absent or symlinked'
[ ! -e "$ROOT/remove" ] && [ ! -e "$ROOT/disable" ] || fail 'module marked disabled/removed'
R="$ROOT/runtime/arm64-v8a"
V="$ROOT/config/chrootctl/build-variant.json"
C="$ROOT/config/chrootctl/runtime-sha256.list"
X="$ROOT/config/chrootctl/runtime-executables.list"
for file in "$V" "$C" "$X" "$R/runtime-manifest.json" "$R/chrootctl" "$ROOT/service.sh"; do
  [ -f "$file" ] && [ ! -L "$file" ] || fail 'required installed file absent/unsafe'
done
[ -x "$R/chrootctl" ] || fail 'Chrootctl backend not executable'
[ -x "$ROOT/service.sh" ] || fail 'boot service not executable'

if command -v sha256sum >/dev/null 2>&1; then
  digest() { sha256sum "$1" | cut -d ' ' -f 1; }
  (cd "$R" && sha256sum -c "$C" >/dev/null 2>&1) || fail 'runtime SHA inventory mismatch'
elif command -v toybox >/dev/null 2>&1; then
  digest() { toybox sha256sum "$1" | cut -d ' ' -f 1; }
  (cd "$R" && toybox sha256sum -c "$C" >/dev/null 2>&1) || fail 'runtime SHA inventory mismatch'
else
  fail 'SHA256 verification unavailable'
fi

field() { sed -n 's/^[[:space:]]*"'"$1"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$V" | head -n 1; }
api=$(sed -n 's/^[[:space:]]*"androidApi"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' "$V" | head -n 1)
edition=$(field edition)
source=$(field sourceCommit)
devtool=$(field devtoolCommit)
want_manifest=$(field runtimeManifestSha256)
installed_manifest=$(digest "$R/runtime-manifest.json")
[ "$api" = 26 ] && [ "$(field moduleId)" = chrootctl ] || fail 'edition/API/module identity differs'
[ "${#source}" -eq 40 ] && [ "${#devtool}" -eq 40 ] || fail 'source identity not embedded'
[ "${#want_manifest}" -eq 64 ] && [ "$want_manifest" = "$installed_manifest" ] || fail 'manifest digest differs'
case "$edition" in
  standard)
    [ ! -e "$R/rclone" ] && ! grep -qx rclone "$X" || fail 'standard contains rclone'
    ;;
  rclone)
    [ -f "$R/rclone" ] && [ -x "$R/rclone" ] && [ ! -L "$R/rclone" ] && grep -qx rclone "$X" || fail 'rclone edition missing its binary'
    ;;
  *) fail 'unknown edition';;
esac
# Runtime directory must have *only* the manifest's listed files. Count and
# validate the expected names against the immutable SHA list (no wildcard trust).
for entry in "$R"/*; do
  [ -f "$entry" ] && [ ! -L "$entry" ] || fail 'unexpected runtime file kind'
  name=${entry##*/}
  grep -Eq "^[0123456789abcdef]{64}  ${name}$" "$C" || fail 'extra runtime file detected'
done
# SHA hex / UUID regular expressions prevent spoofing JSON fields with quotes.
for value in "$source" "$devtool"; do
  case "$value" in *[!a-f0-9]*|'') fail 'source identity malformed';; esac
done
case "$want_manifest" in *[!a-f0-9]*|'') fail 'manifest digest malformed';; esac
if [ "$MODE" = fixture ]; then
  boot=fixture-not-device
  boot_complete=0
  selinux=UNOBSERVED
  uid=unobserved
else
  boot=$(cat /proc/sys/kernel/random/boot_id)
  case "$boot" in *[!a-f0-9-]*|'') fail 'boot identity invalid';; esac
  boot_complete=$(getprop sys.boot_completed)
  selinux=$(getenforce)
  uid=$(id -u)
fi
runtime_sha=$(digest "$R/chrootctl")
# The caller should store this output separately for each edition. This report
# does NOT attest caller process identity, grants, journal, or Skybind R1 pass.
printf '{"schemaVersion":1,"probe":"chrootctl-cc09-installed-v1","mode":"%s","edition":"%s","androidApi":26,"sourceCommit":"%s","devtoolCommit":"%s","runtimeManifestSha256":"%s","runtimeSHA256":"%s","bootId":"%s","bootCompleted":"%s","selinux":"%s","uid":"%s","assessment":"INSTALLED_SNAPSHOT_UNATTESTED","skybindR1":"NOT_TESTED","skybindR3R4":"NOT_QUALIFIED"}\n' \
  "$MODE" "$edition" "$source" "$devtool" "$installed_manifest" "$runtime_sha" "$boot" "$boot_complete" "$selinux" "$uid"
