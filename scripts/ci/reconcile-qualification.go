//go:build ignore

// CC-10 release-evidence reconciler. Intentionally cannot self-qualify devices;
// GitHub hosted outputs and root snapshots need independent trusted authority.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
)

type hosted struct {
	SchemaVersion int    `json:"schemaVersion"`
	AndroidAPI    int    `json:"androidApi"`
	SourceCommit  string `json:"sourceCommit"`
	DevtoolCommit string `json:"devtoolCommit"`
	Qualification string `json:"qualification"`
	Artifacts     []struct {
		Edition            string `json:"edition"`
		Filename           string `json:"filename"`
		SHA256             string `json:"sha256"`
		RuntimeManifestSHA string `json:"runtimeManifestSha256"`
	} `json:"artifacts"`
}
type deviceProof struct {
	SchemaVersion      int    `json:"schemaVersion"`
	Probe              string `json:"probe"`
	Mode               string `json:"mode"`
	Edition            string `json:"edition"`
	AndroidAPI         int    `json:"androidApi"`
	SourceCommit       string `json:"sourceCommit"`
	DevtoolCommit      string `json:"devtoolCommit"`
	RuntimeManifestSHA string `json:"runtimeManifestSha256"`
	RuntimeSHA         string `json:"runtimeSHA256"`
	BootID             string `json:"bootId"`
	BootCompleted      string `json:"bootCompleted"`
	SELinux            string `json:"selinux"`
	UID                string `json:"uid"`
	Assessment         string `json:"assessment"`
	SkybindR1          string `json:"skybindR1"`
	SkybindR3R4        string `json:"skybindR3R4"`
}
type gate struct {
	ID       string `json:"id"`
	Status   string `json:"status"`
	Evidence string `json:"evidence"`
}
type report struct {
	SchemaVersion              int      `json:"schemaVersion"`
	SourceCommit               string   `json:"sourceCommit,omitempty"`
	DevtoolCommit              string   `json:"devtoolCommit,omitempty"`
	AndroidAPI                 int      `json:"androidApi"`
	Qualification              string   `json:"qualification"`
	AllHostedArtifactsVerified bool     `json:"allHostedArtifactsVerified"`
	DeviceSnapshotsMatched     []string `json:"deviceSnapshotsMatched"`
	Gates                      []gate   `json:"gates"`
	Requires                   []string `json:"requires"`
}

func readFileJSON(path string, target any) error {
	b, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	if err := json.Unmarshal(b, target); err != nil {
		return err
	}
	return nil
}
func shaFile(path string) (string, error) {
	b, e := os.ReadFile(path)
	if e != nil {
		return "", e
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:]), nil
}

var fullSHA = regexp.MustCompile(`^[0-9a-f]{40}$`)
var digestSHA = regexp.MustCompile(`^[0-9a-f]{64}$`)
var bootIDRE = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// reconcile requires a verified hosted release-evidence document and compares
// an optional per-edition installed snapshot, but *never* marks device PASS.
func reconcile(hostedDir string, snapshots map[string]string) (report, error) {
	r := report{SchemaVersion: 1, AndroidAPI: 26, Qualification: "NOT_DEVICE_QUALIFIED", DeviceSnapshotsMatched: []string{}, Gates: []gate{}, Requires: []string{"Independent Skybind root-module process identity/grant/revocation evidence for each edition", "Real installed artifact provenance and authenticated device acceptance", "Native rclone disposable-remote acceptance for embedded edition", "GitHub full hosted native build acceptance"}}
	var h hosted
	if err := readFileJSON(filepath.Join(hostedDir, "release-evidence.json"), &h); err != nil {
		return r, fmt.Errorf("read hosted evidence: %w", err)
	}
	if h.SchemaVersion != 1 || h.AndroidAPI != 26 || !fullSHA.MatchString(h.SourceCommit) || !fullSHA.MatchString(h.DevtoolCommit) || h.Qualification != "HOSTED_CANDIDATE_NOT_DEVICE_QUALIFIED" || len(h.Artifacts) != 2 {
		return r, errors.New("untrusted hosted release identity")
	}
	r.SourceCommit = h.SourceCommit
	r.DevtoolCommit = h.DevtoolCommit
	seen := map[string]bool{}
	indexed := map[string]struct{ manifest, zip string }{}
	for _, a := range h.Artifacts {
		if (a.Edition != "standard" && a.Edition != "rclone") || seen[a.Edition] || a.Filename != "chrootctl-"+a.Edition+"-arm64.zip" || !digestSHA.MatchString(a.SHA256) || !digestSHA.MatchString(a.RuntimeManifestSHA) {
			return r, errors.New("bad edition artifact membership")
		}
		seen[a.Edition] = true
		actual, err := shaFile(filepath.Join(hostedDir, a.Filename))
		if err != nil {
			return r, err
		}
		if actual != a.SHA256 {
			return r, fmt.Errorf("%s archive bytes don't match hosted release receipt", a.Edition)
		}
		indexed[a.Edition] = struct{ manifest, zip string }{a.RuntimeManifestSHA, a.SHA256}
	}
	if !seen["standard"] || !seen["rclone"] {
		return r, errors.New("missing hosted edition")
	}
	r.AllHostedArtifactsVerified = true
	r.Gates = append(r.Gates, gate{"CC-00..CC-07", "HOSTED_CANDIDATE_PRESENT", "Two distinct API-26 edition archives match the hosted release index; not device-qualified"})
	for _, edition := range []string{"standard", "rclone"} {
		path := snapshots[edition]
		if path == "" {
			r.Gates = append(r.Gates, gate{"CC-09-" + edition, "OPEN", "Installed Android snapshot missing"})
			continue
		}
		var d deviceProof
		if err := readFileJSON(path, &d); err != nil {
			return r, fmt.Errorf("%s snapshot: %w", edition, err)
		}
		expected := indexed[edition]
		if d.SchemaVersion != 1 || d.Probe != "chrootctl-cc09-installed-v1" || d.Mode != "device" || d.Edition != edition || d.AndroidAPI != 26 || d.SourceCommit != h.SourceCommit || d.DevtoolCommit != h.DevtoolCommit || d.RuntimeManifestSHA != expected.manifest || !digestSHA.MatchString(d.RuntimeSHA) || !bootIDRE.MatchString(d.BootID) || d.BootCompleted != "1" || d.SELinux != "Enforcing" || d.UID != "0" || d.Assessment != "INSTALLED_SNAPSHOT_UNATTESTED" || d.SkybindR1 != "NOT_TESTED" || d.SkybindR3R4 != "NOT_QUALIFIED" {
			return r, fmt.Errorf("%s snapshot differs from hosted artifact/probe contract; cannot qualify", edition)
		}
		r.DeviceSnapshotsMatched = append(r.DeviceSnapshotsMatched, edition)
		r.Gates = append(r.Gates, gate{"CC-09-" + edition, "SNAPSHOT_MATCHED_UNATTESTED", "Root module manifest/source matched; no independent installed-binary authority or reboot process test"})
	}
	r.Gates = append(r.Gates, gate{"CC-08", "OPEN_REAL_SKYBIND_GATE", "Offline R1 conformance is not real root-module client approval; R3/R4 unavailable"})
	r.Gates = append(r.Gates, gate{"CC-10", "OPEN_EXTERNAL_ACCEPTANCE", "Device, release attestation and complete promise audit must be independently established"})
	return r, nil
}
func main() {
	hostedDir := flag.String("hosted-evidence", "", "directory containing release-evidence.json and both ZIPs")
	standard := flag.String("device-standard", "", "real Android device snapshot from standard edition")
	embedded := flag.String("device-rclone", "", "real Android device snapshot from rclone edition")
	output := flag.String("output", "", "write reconciliation report to this path (default stdout)")
	flag.Parse()
	if *hostedDir == "" {
		fmt.Fprintln(os.Stderr, "--hosted-evidence is required")
		os.Exit(2)
	}
	r, err := reconcile(*hostedDir, map[string]string{"standard": *standard, "rclone": *embedded})
	if err != nil {
		fmt.Fprintln(os.Stderr, "FAIL_CC10_RECONCILE:", err)
		os.Exit(1)
	}
	blob, err := json.MarshalIndent(r, "", "  ")
	if err != nil {
		panic(err)
	}
	blob = append(blob, '\n')
	if *output == "" {
		_, _ = os.Stdout.Write(blob)
	} else if err := os.WriteFile(*output, blob, 0644); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
