package rcloneops

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func fakeRuntime(t *testing.T) (Runtime, string) {
	t.Helper()
	root := t.TempDir()
	remoteRoot := filepath.Join(root, "remote")
	if err := os.MkdirAll(filepath.Join(remoteRoot, "chroots"), 0o700); err != nil {
		t.Fatal(err)
	}
	logPath := filepath.Join(root, "args.log")
	script := filepath.Join(root, "rclone")
	body := `#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$RCLONE_TEST_LOG"
cmd=$1; shift
path_for() {
  v=$1
  case "$v" in drive:*) v=${v#drive:} ;; *) echo "bad remote" >&2; exit 5 ;; esac
  v=${v#/}
  printf '%s/%s' "$RCLONE_FAKE_ROOT" "$v"
}
case "$cmd" in
  version) printf '%s\n' 'rclone v1.75.1' ;;
  cat) cat "$(path_for "$1")" ;;
  rcat)
    p=$(path_for "$1"); mkdir -p "$(dirname "$p")"; cat > "$p"
    n=$(wc -c < "$p" | tr -d ' ')
    printf '{"stats":{"bytes":%s,"transfers":1,"totalBytes":%s,"totalTransfers":1}}\n' "$n" "$n" >&2
    ;;
  moveto) src=$(path_for "$1"); dst=$(path_for "$2"); mkdir -p "$(dirname "$dst")"; mv -f "$src" "$dst" ;;
  deletefile) rm -f "$(path_for "$1")" ;;
  lsjson)
    p=$(path_for "$1")
    case " $* " in
      *' --stat '*)
        if [ -d "$p" ]; then printf '{"Path":"%s","Name":"%s","Size":-1,"ModTime":"2026-01-01T00:00:00Z","IsDir":true}\n' "$1" "$(basename "$p")"
        elif [ -f "$p" ]; then n=$(wc -c < "$p" | tr -d ' '); printf '{"Path":"%s","Name":"%s","Size":%s,"ModTime":"2026-01-01T00:00:00Z","IsDir":false}\n' "$1" "$(basename "$p")" "$n"
        else echo 'object not found' >&2; exit 4; fi
        ;;
      *) printf '[]\n' ;;
    esac
    ;;
  *) echo "unexpected command: $cmd" >&2; exit 3 ;;
esac
`
	if err := os.WriteFile(script, []byte(body), 0o700); err != nil {
		t.Fatal(err)
	}
	config := filepath.Join(root, "rclone.conf")
	if err := os.WriteFile(config, []byte("[drive]\ntype = local\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CHROOTCTL_RCLONE_PATH", script)
	t.Setenv("CHROOTCTL_RCLONE_CONFIG", config)
	t.Setenv("RCLONE_TEST_LOG", logPath)
	t.Setenv("RCLONE_FAKE_ROOT", remoteRoot)
	runtime, err := RuntimeFromEnvironment()
	if err != nil {
		t.Fatal(err)
	}
	return runtime, remoteRoot
}

func TestRuntimeProbeAndCredentialFreeRemoteOperations(t *testing.T) {
	runtime, remoteRoot := fakeRuntime(t)
	info, err := runtime.Probe(context.Background())
	if err != nil || info.Version != "v1.75.1" || len(info.ConfiguredRemotes) != 1 || info.ConfiguredRemotes[0] != "drive" {
		t.Fatalf("info=%+v err=%v", info, err)
	}
	payload := strings.Repeat("payload", 100)
	if err := runtime.Rcat(context.Background(), "rclone://drive/chroots/a.tar.zst", strings.NewReader(payload), StreamOptions{}); err != nil {
		t.Fatal(err)
	}
	if got, err := os.ReadFile(filepath.Join(remoteRoot, "chroots", "a.tar.zst")); err != nil || string(got) != payload {
		t.Fatalf("remote payload mismatch err=%v", err)
	}
	var got strings.Builder
	if err := runtime.StreamRead(context.Background(), "rclone://drive/chroots/a.tar.zst", StreamOptions{}, func(r io.Reader) error { _, e := io.Copy(&got, r); return e }); err != nil {
		t.Fatal(err)
	}
	if got.String() != payload {
		t.Fatal("stream read did not round-trip")
	}
	if err := runtime.Move(context.Background(), "rclone://drive/chroots/a.tar.zst", "rclone://drive/chroots/b.tar.zst"); err != nil {
		t.Fatal(err)
	}
	entry, err := runtime.Stat(context.Background(), "rclone://drive/chroots/b.tar.zst")
	if err != nil || entry.Size != int64(len(payload)) || entry.IsDir {
		t.Fatalf("entry=%+v err=%v", entry, err)
	}
}

func TestDiagnosticSanitizationAndConfigImport(t *testing.T) {
	runtime, _ := fakeRuntime(t)
	input := `failed config=` + runtime.Config + ` token=abc password=hidden client_secret:"json-secret" refresh_token:rv123 access_key_id=id123 secret_access_key=sk123 {"access_token":"quoted-secret","client_id":"quoted-id"}`
	got := runtime.sanitizeDiagnostic(input)
	for _, secret := range []string{runtime.Config, "abc", "hidden", "json-secret", "rv123", "id123", "sk123", "quoted-secret", "quoted-id"} {
		if strings.Contains(got, secret) {
			t.Fatalf("diagnostic leaked %q: %s", secret, got)
		}
	}
	if !strings.Contains(got, "<rclone-config>") || strings.Count(got, "<redacted>") < 8 {
		t.Fatalf("sanitization evidence missing: %s", got)
	}

	staged := filepath.Join(t.TempDir(), "rclone.conf")
	if err := os.WriteFile(staged, []byte("RCLONE_ENCRYPT_V0:secret"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := ImportConfig(staged); err == nil || !strings.Contains(err.Error(), "encrypted rclone.conf") {
		t.Fatalf("expected encrypted config rejection, got %v", err)
	}
}

func TestConfiguredRemoteMustExist(t *testing.T) {
	runtime, _ := fakeRuntime(t)
	if _, err := runtime.Stat(context.Background(), "rclone://box/chroots/a.tar.zst"); err == nil || !strings.Contains(err.Error(), `remote "box" is not configured`) {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestRemoteExistsAndMoveAreFailClosed(t *testing.T) {
	runtime, remoteRoot := fakeRuntime(t)
	missing, err := runtime.Exists(context.Background(), "rclone://drive/chroots/missing.tar.zst")
	if err != nil || missing {
		t.Fatalf("missing exists=%v err=%v", missing, err)
	}
	if err := os.WriteFile(filepath.Join(remoteRoot, "chroots", "src.tar.zst"), []byte("payload"), 0o600); err != nil {
		t.Fatal(err)
	}
	exists, err := runtime.Exists(context.Background(), "rclone://drive/chroots/src.tar.zst")
	if err != nil || !exists {
		t.Fatalf("existing exists=%v err=%v", exists, err)
	}
	if err := runtime.Move(context.Background(), "rclone://drive/chroots/src.tar.zst", "rclone://drive/chroots/final.tar.zst"); err != nil {
		t.Fatal(err)
	}
	logBytes, err := os.ReadFile(os.Getenv("RCLONE_TEST_LOG"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(logBytes), "moveto drive:chroots/src.tar.zst drive:chroots/final.tar.zst --immutable") {
		t.Fatalf("moveto did not use immutable publication: %s", logBytes)
	}
}
