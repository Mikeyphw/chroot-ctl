package repoctl

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

type auditCoverage struct {
	SchemaVersion            int                     `json:"schemaVersion"`
	Snapshot                 string                  `json:"snapshot"`
	SourceFindingCount       int                     `json:"sourceFindingCount"`
	CanonicalFindingCount    int                     `json:"canonicalFindingCount"`
	DeduplicatedFindingCount int                     `json:"deduplicatedFindingCount"`
	StandaloneFindingCount   int                     `json:"standaloneFindingCount"`
	Overlays                 []auditOverlay          `json:"overlays"`
	CanonicalFindings        []auditCanonicalFinding `json:"canonicalFindings"`
}

type auditOverlay struct {
	ID     string `json:"id"`
	Title  string `json:"title"`
	Status string `json:"status"`
}

type auditCanonicalFinding struct {
	ID                 string               `json:"id"`
	Title              string               `json:"title"`
	OwnerOverlay       string               `json:"ownerOverlay"`
	SupportingOverlays []string             `json:"supportingOverlays"`
	Status             string               `json:"status"`
	SourceFindings     []auditSourceFinding `json:"sourceFindings"`
}

type auditSourceFinding struct {
	ID           string `json:"id"`
	Severity     string `json:"severity"`
	Domain       string `json:"domain"`
	SourceReport string `json:"sourceReport"`
	Title        string `json:"title"`
}

// ValidateAuditCoverage makes the bug-hunt ledger an executable release invariant.
// It deliberately checks accounting rather than issue semantics: later overlays may
// advance statuses, but they may not silently lose canonical or source findings.
func ValidateAuditCoverage(root string) error {
	path := filepath.Join(root, "docs", "audit", "roadmap-coverage.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read audit coverage: %w", err)
	}
	var coverage auditCoverage
	if err := json.Unmarshal(raw, &coverage); err != nil {
		return fmt.Errorf("parse audit coverage: %w", err)
	}
	if coverage.SchemaVersion != 1 {
		return fmt.Errorf("audit coverage schemaVersion=%d, want 1", coverage.SchemaVersion)
	}
	if coverage.Snapshot != "chroot-ctl-20260912-153425-968931.tar.gz" {
		return fmt.Errorf("audit coverage snapshot=%q is not the audited baseline", coverage.Snapshot)
	}
	if coverage.SourceFindingCount != 609 || coverage.CanonicalFindingCount != 272 || coverage.DeduplicatedFindingCount != 45 || coverage.StandaloneFindingCount != 227 {
		return fmt.Errorf(
			"audit coverage declared counts changed: source=%d canonical=%d deduplicated=%d standalone=%d",
			coverage.SourceFindingCount, coverage.CanonicalFindingCount, coverage.DeduplicatedFindingCount, coverage.StandaloneFindingCount,
		)
	}

	expectedOverlays := map[string]bool{}
	for i := 1; i <= 20; i++ {
		expectedOverlays[fmt.Sprintf("CHR%02d", i)] = true
	}
	overlays := map[string]auditOverlay{}
	for _, item := range coverage.Overlays {
		if !expectedOverlays[item.ID] {
			return fmt.Errorf("audit coverage has unknown overlay %q", item.ID)
		}
		if _, exists := overlays[item.ID]; exists {
			return fmt.Errorf("audit coverage repeats overlay %q", item.ID)
		}
		if item.Title == "" || (item.Status != "planned" && item.Status != "implemented" && item.Status != "closed") {
			return fmt.Errorf("audit coverage overlay %q has incomplete metadata", item.ID)
		}
		overlays[item.ID] = item
	}
	if len(overlays) != len(expectedOverlays) {
		return fmt.Errorf("audit coverage overlays=%d, want %d", len(overlays), len(expectedOverlays))
	}

	expectedCanonical := map[string]bool{}
	for i := 1; i <= 45; i++ {
		expectedCanonical[fmt.Sprintf("D%02d", i)] = true
	}
	for i := 1; i <= 227; i++ {
		expectedCanonical[fmt.Sprintf("U%03d", i)] = true
	}
	canonical := map[string]auditCanonicalFinding{}
	sourceIDs := map[string]string{}
	sourceCount := 0
	for _, finding := range coverage.CanonicalFindings {
		if !expectedCanonical[finding.ID] {
			return fmt.Errorf("audit coverage has unknown canonical finding %q", finding.ID)
		}
		if _, exists := canonical[finding.ID]; exists {
			return fmt.Errorf("audit coverage repeats canonical finding %q", finding.ID)
		}
		if finding.Title == "" || !expectedOverlays[finding.OwnerOverlay] {
			return fmt.Errorf("audit coverage canonical finding %q has invalid title/owner", finding.ID)
		}
		if finding.Status != "planned" && finding.Status != "implemented" && finding.Status != "closed" {
			return fmt.Errorf("audit coverage canonical finding %q has invalid status %q", finding.ID, finding.Status)
		}
		for _, support := range finding.SupportingOverlays {
			if !expectedOverlays[support] || support == finding.OwnerOverlay {
				return fmt.Errorf("audit coverage canonical finding %q has invalid supporting overlay %q", finding.ID, support)
			}
		}
		if len(finding.SourceFindings) == 0 {
			return fmt.Errorf("audit coverage canonical finding %q has no source manifestations", finding.ID)
		}
		for _, source := range finding.SourceFindings {
			sourceCount++
			if source.ID == "" || source.Title == "" || source.Domain == "" || source.SourceReport == "" {
				return fmt.Errorf("audit coverage canonical finding %q has incomplete source manifestation", finding.ID)
			}
			sourceKey := source.SourceReport + "\x00" + source.ID
			if previous, exists := sourceIDs[sourceKey]; exists {
				return fmt.Errorf("audit source finding %q in %q is multiply mapped to %s and %s", source.ID, source.SourceReport, previous, finding.ID)
			}
			sourceIDs[sourceKey] = finding.ID
		}
		canonical[finding.ID] = finding
	}
	if len(canonical) != 272 || len(canonical) != len(expectedCanonical) {
		missing := make([]string, 0)
		for id := range expectedCanonical {
			if _, ok := canonical[id]; !ok {
				missing = append(missing, id)
			}
		}
		sort.Strings(missing)
		return fmt.Errorf("audit canonical coverage=%d/272; missing=%v", len(canonical), missing)
	}
	if sourceCount != 609 || len(sourceIDs) != 609 {
		return fmt.Errorf("audit source coverage=%d unique=%d, want 609/609", sourceCount, len(sourceIDs))
	}

	// CHR01 owns exactly the build-foundation canonical set.  This makes the
	// first roadmap overlay's completion state auditable rather than prose-only.
	for _, id := range []string{"D37", "U097", "U098", "U099"} {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR01" || finding.Status == "planned" {
			return fmt.Errorf("CHR01 finding %s is not marked implemented", id)
		}
	}
	if got := len(canonical["D37"].SourceFindings); got != 36 {
		return fmt.Errorf("D37 source-manifestation coverage=%d, want 36", got)
	}

	chr02 := []string{"D09", "D10", "D43", "U100", "U101", "U102", "U103", "U212", "U213", "U214", "U215", "U216"}
	chr02Sources := 0
	for _, id := range chr02 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR02" || finding.Status == "planned" {
			return fmt.Errorf("CHR02 finding %s is not marked implemented", id)
		}
		chr02Sources += len(finding.SourceFindings)
	}
	if chr02Sources != 37 {
		return fmt.Errorf("CHR02 source-manifestation coverage=%d, want 37", chr02Sources)
	}
	return nil
}
