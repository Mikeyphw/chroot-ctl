package integrity

import (
	"bytes"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"

	openpgp "github.com/ProtonMail/go-crypto/openpgp/v2"
)

func TestVerifyDetachedSignatureWithPinnedKeyring(t *testing.T) {
	pinned, err := openpgp.NewEntity("Pinned", "", "pinned@example.invalid", nil)
	if err != nil {
		t.Fatal(err)
	}
	other, err := openpgp.NewEntity("Other", "", "other@example.invalid", nil)
	if err != nil {
		t.Fatal(err)
	}

	var keyring bytes.Buffer
	if err = other.Serialize(&keyring); err != nil {
		t.Fatal(err)
	}
	if err = pinned.Serialize(&keyring); err != nil {
		t.Fatal(err)
	}

	message := []byte("authenticated rootfs manifest\n")
	var signature bytes.Buffer
	// Put an unpinned signature first to ensure the verifier can select the
	// pinned signer from a detached signature containing multiple candidates.
	if err = openpgp.DetachSign(&signature, []*openpgp.Entity{other, pinned}, bytes.NewReader(message), nil); err != nil {
		t.Fatal(err)
	}

	dir := t.TempDir()
	dataPath := filepath.Join(dir, "SHA256SUMS")
	sigPath := filepath.Join(dir, "SHA256SUMS.gpg")
	if err = os.WriteFile(dataPath, message, 0o600); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(sigPath, signature.Bytes(), 0o600); err != nil {
		t.Fatal(err)
	}
	fingerprint := strings.ToUpper(hex.EncodeToString(pinned.PrimaryKey.Fingerprint))
	if err = VerifyDetachedSignatureWithKeyring(dataPath, sigPath, keyring.Bytes(), fingerprint); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(dataPath, []byte("tampered\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err = VerifyDetachedSignatureWithKeyring(dataPath, sigPath, keyring.Bytes(), fingerprint); err == nil || !strings.Contains(err.Error(), "signature verification failed") {
		t.Fatalf("tampered message error=%v", err)
	}
	if err = os.WriteFile(dataPath, message, 0o600); err != nil {
		t.Fatal(err)
	}

	var armoredSignature bytes.Buffer
	if err = openpgp.ArmoredDetachSign(&armoredSignature, []*openpgp.Entity{pinned}, bytes.NewReader(message), nil); err != nil {
		t.Fatal(err)
	}
	armoredPath := filepath.Join(dir, "SHA256SUMS.asc")
	if err = os.WriteFile(armoredPath, armoredSignature.Bytes(), 0o600); err != nil {
		t.Fatal(err)
	}
	if err = VerifyDetachedSignatureWithKeyring(dataPath, armoredPath, keyring.Bytes(), fingerprint); err != nil {
		t.Fatalf("armored signature: %v", err)
	}
	if err = VerifyDetachedSignatureWithKeyring(dataPath, sigPath, keyring.Bytes(), strings.Repeat("0", len(fingerprint))); err == nil || !strings.Contains(err.Error(), "does not contain pinned fingerprint") {
		t.Fatalf("wrong fingerprint error=%v", err)
	}
}

func TestVerifyDetachedSignatureWithKeyringFileWithoutHostGPG(t *testing.T) {
	entity, err := openpgp.NewEntity("Pinned", "", "pinned@example.invalid", nil)
	if err != nil {
		t.Fatal(err)
	}
	var keyring bytes.Buffer
	if err = entity.Serialize(&keyring); err != nil {
		t.Fatal(err)
	}
	message := []byte("manifest\n")
	var signature bytes.Buffer
	if err = openpgp.DetachSign(&signature, []*openpgp.Entity{entity}, bytes.NewReader(message), nil); err != nil {
		t.Fatal(err)
	}

	dir := t.TempDir()
	dataPath := filepath.Join(dir, "data")
	sigPath := filepath.Join(dir, "data.sig")
	keyringPath := filepath.Join(dir, "signing-keyring.gpg")
	if err = os.WriteFile(dataPath, message, 0o600); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(sigPath, signature.Bytes(), 0o600); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(keyringPath, keyring.Bytes(), 0o600); err != nil {
		t.Fatal(err)
	}
	fingerprint := strings.ToUpper(hex.EncodeToString(entity.PrimaryKey.Fingerprint))
	if err = VerifyDetachedSignatureWithKeyringFile(dataPath, sigPath, keyringPath, fingerprint); err != nil {
		t.Fatal(err)
	}
}

func TestReadKeyringFileRejectsOversizeInput(t *testing.T) {
	p := filepath.Join(t.TempDir(), "oversize.gpg")
	f, err := os.Create(p)
	if err != nil {
		t.Fatal(err)
	}
	if err = f.Truncate(maxRemoteKeyringBytes + 1); err != nil {
		_ = f.Close()
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err = readKeyringFile(p); err == nil || !strings.Contains(err.Error(), "larger than") {
		t.Fatalf("oversize error=%v", err)
	}
}
