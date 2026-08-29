package integrity

import (
	"bufio"
	sys "chrootctl/internal/system"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

const UbuntuSigningFingerprint = "843938DF228D22F7B3742BC0D94AA3F0EFE21092"
const ArchLinuxARMSigningFingerprint = "68B3537F39A313B3E574D06777193F152BDBE6A6"
const DefaultKeyserver = "hkps://keyserver.ubuntu.com"

type FetchError struct{ Err error }

func (e FetchError) Error() string { return e.Err.Error() }
func (e FetchError) Unwrap() error { return e.Err }

type IntegrityError struct{ Message string }

func (e IntegrityError) Error() string { return e.Message }
func SHA256File(path string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	if _, e = io.Copy(h, f); e != nil {
		return "", e
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

var sumLine = regexp.MustCompile(`^([0-9A-Fa-f]{64})\s+[* ]?(.+)$`)

func ChecksumFromManifest(path, filename string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	s := bufio.NewScanner(f)
	for s.Scan() {
		m := sumLine.FindStringSubmatch(strings.TrimSpace(s.Text()))
		if len(m) == 3 && filepath.Base(m[2]) == filename {
			return strings.ToLower(m[1]), nil
		}
	}
	if e = s.Err(); e != nil {
		return "", e
	}
	return "", IntegrityError{Message: "authenticated checksum manifest does not contain " + filename}
}
func VerifySHA256(path, expected string) error {
	actual, e := SHA256File(path)
	if e != nil {
		return e
	}
	expected = strings.ToLower(expected)
	if actual != expected {
		return IntegrityError{Message: fmt.Sprintf("sha256 mismatch for %s: expected %s, got %s", filepath.Base(path), expected, actual)}
	}
	return nil
}
func VerifyDetachedSignature(ctx context.Context, runner *sys.Runner, data, signature, fingerprint, keyserver string) error {
	if runner == nil {
		return errors.New("runner is nil")
	}
	expected := strings.ToUpper(strings.ReplaceAll(fingerprint, " ", ""))
	if keyserver == "" {
		keyserver = DefaultKeyserver
	}
	home, e := os.MkdirTemp("", "chrootctl-gpg-")
	if e != nil {
		return e
	}
	defer os.RemoveAll(home)
	_ = os.Chmod(home, 0o700)
	if _, e = runner.Run(ctx, []string{"gpg", "--batch", "--homedir", home, "--keyserver", keyserver, "--recv-keys", expected}, sys.RunOptions{Timeout: 120 * time.Second}); e != nil {
		return IntegrityError{Message: fmt.Sprintf("cannot obtain pinned signing key %s: %v", expected, e)}
	}
	listed, e := runner.Run(ctx, []string{"gpg", "--batch", "--homedir", home, "--with-colons", "--fingerprint", expected}, sys.RunOptions{Timeout: 30 * time.Second})
	if e != nil {
		return IntegrityError{Message: fmt.Sprintf("cannot obtain pinned signing key %s: %v", expected, e)}
	}
	seen := false
	for _, line := range strings.Split(listed.Stdout, "\n") {
		f := strings.Split(line, ":")
		if len(f) > 9 && f[0] == "fpr" && strings.ToUpper(f[9]) == expected {
			seen = true
		}
	}
	if !seen {
		return IntegrityError{Message: "retrieved key does not match pinned fingerprint " + expected}
	}
	verified, e := runner.Run(ctx, []string{"gpg", "--batch", "--homedir", home, "--status-fd=1", "--verify", signature, data}, sys.RunOptions{Timeout: 60 * time.Second, AllowFailure: true})
	if e != nil {
		return IntegrityError{Message: fmt.Sprintf("signature verification failed for %s: %v", filepath.Base(data), e)}
	}
	valid := false
	for _, line := range strings.Split(verified.Stdout, "\n") {
		if strings.HasPrefix(line, "[GNUPG:] VALIDSIG ") {
			f := strings.Fields(line)
			if len(f) >= 3 && strings.ToUpper(f[2]) == expected {
				valid = true
				break
			}
		}
	}
	if !valid {
		detail := strings.TrimSpace(verified.Stderr)
		if detail == "" {
			detail = strings.TrimSpace(verified.Stdout)
		}
		if detail == "" {
			detail = "no valid pinned signature"
		}
		if len(detail) > 1000 {
			detail = detail[:1000]
		}
		return IntegrityError{Message: fmt.Sprintf("signature verification failed for %s: %s", filepath.Base(data), detail)}
	}
	return nil
}
