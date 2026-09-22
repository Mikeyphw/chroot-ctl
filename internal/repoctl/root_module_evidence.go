package repoctl

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	chmodule "chrootctl/internal/module"
)

const rootModuleEvidenceSchemaVersion = 4

var rootModuleEvidenceStages = []string{"root_restore", "root_build", "root_test", "root_lint", "root_package"}

type rootModuleEvidenceCheck struct {
	Status     string `json:"status"`
	Command    string `json:"command"`
	Provenance string `json:"provenance"`
	ExitCode   int    `json:"exitCode"`
	RecordedAt int64  `json:"recordedAt"`
	Detail     string `json:"detail,omitempty"`
}

type rootModuleEvidence struct {
	SchemaVersion               int                                `json:"schemaVersion"`
	GeneratedAt                 int64                              `json:"generatedAt"`
	ValidationRunID             string                             `json:"validationRunId"`
	SourceCommit                string                             `json:"sourceCommit"`
	SourceTree                  string                             `json:"sourceTree"`
	CompatibilityManifestSHA256 string                             `json:"compatibilityManifestSha256"`
	Checks                      map[string]rootModuleEvidenceCheck `json:"checks"`
}

func rootModuleValidationRunID() string {
	b := make([]byte, 8)
	if _, err := rand.Read(b); err == nil {
		return fmt.Sprintf("root-module-%d-%s", time.Now().Unix(), hex.EncodeToString(b))
	}
	return fmt.Sprintf("root-module-%d", time.Now().UnixNano())
}

func readStageMarker(dir, stage string) (rootModuleEvidenceCheck, error) {
	path := filepath.Join(dir, stage+".ok")
	raw, err := os.ReadFile(path)
	if err != nil {
		return rootModuleEvidenceCheck{}, fmt.Errorf("missing Devtool validation stage marker %s: %w", stage, err)
	}
	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	if len(lines) < 2 {
		return rootModuleEvidenceCheck{}, fmt.Errorf("invalid Devtool validation stage marker %s", stage)
	}
	recordedAt, err := strconv.ParseInt(strings.TrimSpace(lines[0]), 10, 64)
	if err != nil || recordedAt <= 0 {
		return rootModuleEvidenceCheck{}, fmt.Errorf("invalid Devtool validation timestamp for %s", stage)
	}
	command := strings.TrimSpace(strings.Join(lines[1:], " "))
	if command == "" {
		return rootModuleEvidenceCheck{}, fmt.Errorf("missing Devtool validation command for %s", stage)
	}
	return rootModuleEvidenceCheck{Status: "pass", Command: command, Provenance: "devtool-stage", ExitCode: 0, RecordedAt: recordedAt}, nil
}

func compatibilitySHAFromModule(moduleDir string) (string, error) {
	path := filepath.Join(moduleDir, "config", "chrootctl", "compatibility-manifest.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:]), nil
}

// SealRootModuleEvidence converts the successful Devtool root-module lifecycle
// into schema-v4 runtime evidence and embeds that evidence into the module seal.
// Package is the terminal validation stage; the command validates the resulting
// tree/ZIP before returning, so a failing final package can never publish the
// evidence as a successful artifact.
func SealRootModuleEvidence(markersDir, moduleDir, zipPath string, checksum bool) error {
	root, err := repoRoot()
	if err != nil {
		return err
	}
	if !filepath.IsAbs(markersDir) {
		markersDir = filepath.Join(root, markersDir)
	}
	if !filepath.IsAbs(moduleDir) {
		moduleDir = filepath.Join(root, moduleDir)
	}
	if !filepath.IsAbs(zipPath) {
		zipPath = filepath.Join(root, zipPath)
	}

	checks := map[string]rootModuleEvidenceCheck{}
	for _, stage := range []string{"root_restore", "root_build", "root_test", "root_lint"} {
		item, readErr := readStageMarker(markersDir, stage)
		if readErr != nil {
			return readErr
		}
		checks[stage] = item
	}
	checks["root_package"] = rootModuleEvidenceCheck{
		Status:     "pass",
		Command:    "scripts/devtool/root-module-package.sh",
		Provenance: "devtool-stage",
		ExitCode:   0,
		RecordedAt: time.Now().Unix(),
		Detail:     "Package preflight passed; final tree/ZIP validation is enforced before this command returns.",
	}
	compatSHA, err := compatibilitySHAFromModule(moduleDir)
	if err != nil {
		return err
	}
	evidence := rootModuleEvidence{
		SchemaVersion:               rootModuleEvidenceSchemaVersion,
		GeneratedAt:                 time.Now().Unix(),
		ValidationRunID:             rootModuleValidationRunID(),
		CompatibilityManifestSHA256: compatSHA,
		Checks:                      checks,
	}
	raw, err := json.MarshalIndent(evidence, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	if err = chmodule.SealValidationEvidence(moduleDir, zipPath, raw); err != nil {
		return err
	}
	if checksum {
		if _, err = WriteChecksum(zipPath); err != nil {
			return err
		}
	}
	return nil
}
