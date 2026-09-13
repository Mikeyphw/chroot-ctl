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

	chr03 := []string{"D01", "D42", "U104", "U105", "U106", "U107", "U108", "U109", "U222"}
	chr03Sources := 0
	for _, id := range chr03 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR03" || finding.Status == "planned" {
			return fmt.Errorf("CHR03 finding %s is not marked implemented", id)
		}
		chr03Sources += len(finding.SourceFindings)
	}
	if chr03Sources != 17 {
		return fmt.Errorf("CHR03 source-manifestation coverage=%d, want 17", chr03Sources)
	}

	chr04 := []string{"D07", "D08", "U202", "U203", "U204", "U205", "U206", "U207", "U208", "U209", "U210", "U211"}
	chr04Sources := 0
	for _, id := range chr04 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR04" || finding.Status == "planned" {
			return fmt.Errorf("CHR04 finding %s is not marked implemented", id)
		}
		chr04Sources += len(finding.SourceFindings)
	}
	if chr04Sources != 22 {
		return fmt.Errorf("CHR04 source-manifestation coverage=%d, want 22", chr04Sources)
	}
	if d02 := canonical["D02"]; !containsString(d02.SupportingOverlays, "CHR04") {
		return fmt.Errorf("CHR04 wrapper dry-run support must remain recorded on D02")
	}

	chr05 := []string{"D05", "D06", "D31", "U081", "U082", "U083", "U084", "U085", "U086", "U087", "U088", "U089", "U090", "U091", "U092", "U223", "U226", "U227"}
	chr05Sources := 0
	for _, id := range chr05 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR05" || finding.Status == "planned" {
			return fmt.Errorf("CHR05 finding %s is not marked implemented", id)
		}
		chr05Sources += len(finding.SourceFindings)
	}
	if chr05Sources != 35 {
		return fmt.Errorf("CHR05 source-manifestation coverage=%d, want 35", chr05Sources)
	}

	chr06 := []string{"D02", "D03", "U217", "U218", "U219", "U220", "U221"}
	chr06Sources := 0
	for _, id := range chr06 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR06" || finding.Status == "planned" {
			return fmt.Errorf("CHR06 finding %s is not marked implemented", id)
		}
		chr06Sources += len(finding.SourceFindings)
	}
	if chr06Sources != 19 {
		return fmt.Errorf("CHR06 source-manifestation coverage=%d, want 19", chr06Sources)
	}
	chr07 := []string{"D04", "U149", "U150", "U151", "U152", "U153", "U154", "U155", "U156"}
	chr07Sources := 0
	for _, id := range chr07 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR07" || finding.Status == "planned" {
			return fmt.Errorf("CHR07 finding %s is not marked implemented", id)
		}
		chr07Sources += len(finding.SourceFindings)
	}
	if chr07Sources != 21 {
		return fmt.Errorf("CHR07 source-manifestation coverage=%d, want 21", chr07Sources)
	}
	if d04 := canonical["D04"]; !containsString(d04.SupportingOverlays, "CHR06") {
		return fmt.Errorf("CHR07 D04 closure must retain CHR06 mutation-engine foundation")
	}
	if d41 := canonical["D41"]; d41.OwnerOverlay != "CHR10" || d41.Status != "planned" || !containsString(d41.SupportingOverlays, "CHR07") {
		return fmt.Errorf("CHR07 must support D41 durability without prematurely closing CHR10-owned D41")
	}
	return nil
}

func containsString(values []string, want string) bool {
	for _, value := range values {
		if value == want {
			return true
		}
	}
	return false
}
