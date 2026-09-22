package integrity

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/ProtonMail/go-crypto/openpgp/armor"
	openpgp "github.com/ProtonMail/go-crypto/openpgp/v2"
)

const UbuntuSigningFingerprint = "843938DF228D22F7B3742BC0D94AA3F0EFE21092"
const ArchLinuxARMSigningFingerprint = "68B3537F39A313B3E574D06777193F152BDBE6A6"

const UbuntuSigningKeyringURL = "https://archive.ubuntu.com/ubuntu/project/ubuntu-archive-keyring.gpg"
const ArchLinuxARMSigningKeyURL = "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x" + ArchLinuxARMSigningFingerprint

const maxRemoteKeyringBytes = 4 << 20

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

// VerifyDetachedSignatureWithKeyringFile verifies data using a downloaded
// public keyring while pinning trust to the exact primary-key fingerprint.
// The cryptographic verification is performed in-process so Android/KernelSU
// installs do not depend on a host gpg binary. Network retrieval remains in the
// installer so it uses chrootctl's logged/retrying download transport.
func VerifyDetachedSignatureWithKeyringFile(data, signature, keyringPath, fingerprint string) error {
	keyring, err := readKeyringFile(keyringPath)
	if err != nil {
		return IntegrityError{Message: fmt.Sprintf("cannot read pinned signing key %s: %v", normalizeFingerprint(fingerprint), err)}
	}
	return VerifyDetachedSignatureWithKeyring(data, signature, keyring, fingerprint)
}

func readKeyringFile(path string) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, maxRemoteKeyringBytes+1))
	if err != nil {
		return nil, err
	}
	if len(b) == 0 {
		return nil, fmt.Errorf("%s is empty", filepath.Base(path))
	}
	if len(b) > maxRemoteKeyringBytes {
		return nil, fmt.Errorf("%s is larger than %d bytes", filepath.Base(path), maxRemoteKeyringBytes)
	}
	return b, nil
}

// VerifyDetachedSignatureWithKeyring is the deterministic verification core.
// The supplied keyring may be binary or ASCII-armored and may contain many
// keys; only the entity whose primary fingerprint exactly matches fingerprint
// is admitted to the verification keyring.
func VerifyDetachedSignatureWithKeyring(data, signature string, keyring []byte, fingerprint string) error {
	expected := normalizeFingerprint(fingerprint)
	if expected == "" {
		return IntegrityError{Message: "pinned signing fingerprint is empty"}
	}
	entities, err := parseKeyring(keyring)
	if err != nil {
		return IntegrityError{Message: fmt.Sprintf("cannot parse signing keyring for %s: %v", expected, err)}
	}
	pinned := make(openpgp.EntityList, 0, 1)
	for _, entity := range entities {
		if entity == nil || entity.PrimaryKey == nil {
			continue
		}
		if fingerprintHex(entity.PrimaryKey.Fingerprint) == expected {
			pinned = append(pinned, entity)
		}
	}
	if len(pinned) == 0 {
		return IntegrityError{Message: "retrieved keyring does not contain pinned fingerprint " + expected}
	}

	signed, err := os.Open(data)
	if err != nil {
		return err
	}
	defer signed.Close()
	signatureBytes, err := os.ReadFile(signature)
	if err != nil {
		return err
	}
	signatureReader := io.Reader(bytes.NewReader(signatureBytes))
	trimmedSignature := bytes.TrimSpace(signatureBytes)
	if bytes.HasPrefix(trimmedSignature, []byte("-----BEGIN PGP SIGNATURE-----")) {
		block, decodeErr := armor.Decode(bytes.NewReader(trimmedSignature))
		if decodeErr != nil {
			return IntegrityError{Message: fmt.Sprintf("cannot parse detached signature for %s: %v", filepath.Base(data), decodeErr)}
		}
		if block.Type != openpgp.SignatureType {
			return IntegrityError{Message: fmt.Sprintf("cannot parse detached signature for %s: expected %s armor, got %s", filepath.Base(data), openpgp.SignatureType, block.Type)}
		}
		signatureReader = block.Body
	}

	md, err := openpgp.VerifyDetachedSignatureReader(pinned, signed, signatureReader, nil)
	if err != nil {
		return IntegrityError{Message: fmt.Sprintf("signature verification failed for %s: %v", filepath.Base(data), err)}
	}
	if md == nil || md.UnverifiedBody == nil {
		return IntegrityError{Message: fmt.Sprintf("signature verification failed for %s: verifier returned no message body", filepath.Base(data))}
	}
	if _, err = io.Copy(io.Discard, md.UnverifiedBody); err != nil {
		return IntegrityError{Message: fmt.Sprintf("signature verification failed for %s: %v", filepath.Base(data), err)}
	}
	if md.SignatureError != nil {
		return IntegrityError{Message: fmt.Sprintf("signature verification failed for %s: %v", filepath.Base(data), md.SignatureError)}
	}
	if !md.IsVerified || md.SignedBy == nil || md.SignedBy.Entity == nil || md.SignedBy.Entity.PrimaryKey == nil {
		return IntegrityError{Message: fmt.Sprintf("signature verification failed for %s: no valid pinned signature", filepath.Base(data))}
	}
	actual := fingerprintHex(md.SignedBy.Entity.PrimaryKey.Fingerprint)
	if actual != expected {
		return IntegrityError{Message: fmt.Sprintf("signature verification failed for %s: signer fingerprint %s does not match pinned fingerprint %s", filepath.Base(data), actual, expected)}
	}
	return nil
}

func parseKeyring(raw []byte) (openpgp.EntityList, error) {
	trimmed := bytes.TrimSpace(raw)
	if bytes.HasPrefix(trimmed, []byte("-----BEGIN PGP PUBLIC KEY BLOCK-----")) {
		return openpgp.ReadArmoredKeyRing(bytes.NewReader(trimmed))
	}
	return openpgp.ReadKeyRing(bytes.NewReader(trimmed))
}

func normalizeFingerprint(fingerprint string) string {
	fingerprint = strings.ToUpper(strings.TrimSpace(fingerprint))
	fingerprint = strings.ReplaceAll(fingerprint, " ", "")
	fingerprint = strings.ReplaceAll(fingerprint, ":", "")
	return fingerprint
}

func fingerprintHex(fingerprint []byte) string {
	return strings.ToUpper(hex.EncodeToString(fingerprint))
}
