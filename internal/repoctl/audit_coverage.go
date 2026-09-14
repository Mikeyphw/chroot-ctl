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
	if d41 := canonical["D41"]; d41.OwnerOverlay != "CHR10" || !containsString(d41.SupportingOverlays, "CHR07") {
		return fmt.Errorf("CHR07 durability support must remain recorded on CHR10-owned D41")
	}

	chr08 := []string{"D13", "D25", "D26", "U116", "U117", "U118", "U119", "U120", "U121", "U122", "U123", "U124", "U125", "U126", "U127", "U128", "U129", "U130", "U131", "U132", "U225"}
	chr08Sources := 0
	for _, id := range chr08 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR08" || finding.Status == "planned" {
			return fmt.Errorf("CHR08 finding %s is not marked implemented", id)
		}
		chr08Sources += len(finding.SourceFindings)
	}
	if chr08Sources != 49 {
		return fmt.Errorf("CHR08 source-manifestation coverage=%d, want 49", chr08Sources)
	}
	if d12 := canonical["D12"]; d12.OwnerOverlay != "CHR16" || d12.Status == "planned" {
		return fmt.Errorf("CHR16 must close the log retrieval/retention root cause D12 before final roadmap seal")
	}

	chr09 := []string{"D16", "D17"}
	chr09Sources := 0
	for _, id := range chr09 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR09" || finding.Status == "planned" {
			return fmt.Errorf("CHR09 finding %s is not marked implemented", id)
		}
		chr09Sources += len(finding.SourceFindings)
	}
	if chr09Sources != 16 {
		return fmt.Errorf("CHR09 source-manifestation coverage=%d, want 16", chr09Sources)
	}
	for _, id := range []string{"U139", "U140", "U141"} {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR11" || !containsString(finding.SupportingOverlays, "CHR09") {
			return fmt.Errorf("CHR09 snapshot support must remain recorded on CHR11-owned %s", id)
		}
	}
	for _, id := range []string{"U010"} {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR19" || !containsString(finding.SupportingOverlays, "CHR09") {
			return fmt.Errorf("CHR09 Android snapshot support must remain recorded on CHR19-owned %s", id)
		}
	}
	chr10 := []string{"D18", "D19", "D39", "D41", "U054", "U055", "U056", "U057", "U058", "U059", "U060", "U157", "U158", "U159", "U160", "U161", "U162", "U163", "U164", "U165", "U166", "U167", "U168", "U169"}
	chr10Sources := 0
	for _, id := range chr10 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR10" || finding.Status == "planned" {
			return fmt.Errorf("CHR10 finding %s is not marked implemented", id)
		}
		chr10Sources += len(finding.SourceFindings)
	}
	if chr10Sources != 49 {
		return fmt.Errorf("CHR10 source-manifestation coverage=%d, want 49", chr10Sources)
	}
	chr11 := []string{"D20", "D21", "D22", "U028", "U029", "U030", "U031", "U032", "U033", "U034", "U035", "U036", "U133", "U134", "U135", "U136", "U137", "U138", "U139", "U140", "U141", "U142", "U143", "U144", "U145", "U146", "U147", "U148", "U177", "U224"}
	chr11Sources := 0
	for _, id := range chr11 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR11" || finding.Status == "planned" {
			return fmt.Errorf("CHR11 finding %s is not marked implemented", id)
		}
		chr11Sources += len(finding.SourceFindings)
	}
	if chr11Sources != 41 {
		return fmt.Errorf("CHR11 source-manifestation coverage=%d, want 41", chr11Sources)
	}
	chr12 := []string{"D24", "U020", "U021", "U022", "U023", "U024", "U170", "U171", "U172", "U173", "U174", "U175", "U176"}
	chr12Sources := 0
	for _, id := range chr12 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR12" || finding.Status == "planned" {
			return fmt.Errorf("CHR12 finding %s is not marked implemented", id)
		}
		chr12Sources += len(finding.SourceFindings)
	}
	if chr12Sources != 24 {
		return fmt.Errorf("CHR12 source-manifestation coverage=%d, want 24", chr12Sources)
	}

	chr13 := []string{"D23", "U047", "U048", "U049", "U050", "U051", "U052", "U053", "U178", "U179", "U180", "U181", "U182", "U183", "U184"}
	chr13Sources := 0
	for _, id := range chr13 {
		finding := canonical[id]
		if finding.OwnerOverlay != "CHR13" || finding.Status == "planned" {
			return fmt.Errorf("CHR13 finding %s is not marked implemented", id)
		}
		chr13Sources += len(finding.SourceFindings)
	}
	if chr13Sources != 26 {
		return fmt.Errorf("CHR13 source-manifestation coverage=%d, want 26", chr13Sources)
	}

	// CHR14-CHR20 closure is exact, not token-based. This deliberately checks
	// owner identity, canonical IDs, source manifestation counts, and final status
	// so an overlay-level "implemented" string cannot mask planned findings.
	type overlayClosureSpec struct {
		IDs         []string
		SourceCount int
	}
	closure := map[string]overlayClosureSpec{
		"CHR14": {IDs: []string{"D28"}, SourceCount: 20},
		"CHR15": {IDs: []string{"D27", "U190", "U191", "U192", "U193", "U194", "U195", "U196", "U197", "U198", "U199", "U200", "U201"}, SourceCount: 25},
		"CHR16": {IDs: []string{"D11", "D12", "D14", "D15", "D45", "U110", "U111", "U112", "U113", "U114", "U115", "U185", "U186", "U187", "U188", "U189"}, SourceCount: 42},
		"CHR17": {IDs: []string{"D29", "D30", "D44", "U061", "U062", "U063", "U064", "U065", "U066", "U067", "U068", "U069", "U070", "U071", "U072", "U073", "U074", "U075", "U076", "U077", "U078", "U079", "U080"}, SourceCount: 44},
		"CHR18": {IDs: []string{"D32", "D33", "D34", "U037", "U038", "U039", "U040", "U041", "U042", "U043", "U044", "U045", "U046", "U093", "U094", "U095", "U096"}, SourceCount: 41},
		"CHR19": {IDs: []string{"D40", "U001", "U002", "U003", "U004", "U005", "U006", "U007", "U008", "U009", "U010", "U011", "U012", "U013", "U014", "U015", "U016", "U017", "U018", "U019", "U025", "U026", "U027"}, SourceCount: 23},
		"CHR20": {IDs: []string{"D35", "D36", "D38"}, SourceCount: 19},
	}
	for overlayID, spec := range closure {
		if overlays[overlayID].Status == "planned" {
			return fmt.Errorf("audit overlay %s remains planned after final roadmap seal", overlayID)
		}
		ownedCount, sources := 0, 0
		for _, finding := range canonical {
			if finding.OwnerOverlay == overlayID {
				ownedCount++
			}
		}
		if ownedCount != len(spec.IDs) {
			return fmt.Errorf("%s canonical ownership count=%d, want %d", overlayID, ownedCount, len(spec.IDs))
		}
		for _, id := range spec.IDs {
			finding := canonical[id]
			if finding.OwnerOverlay != overlayID || finding.Status == "planned" {
				return fmt.Errorf("%s finding %s is not exactly closed", overlayID, id)
			}
			sources += len(finding.SourceFindings)
		}
		if sources != spec.SourceCount {
			return fmt.Errorf("%s source-manifestation coverage=%d, want %d", overlayID, sources, spec.SourceCount)
		}
	}
	for id, finding := range canonical {
		if finding.Status == "planned" {
			return fmt.Errorf("final roadmap seal leaves canonical finding %s planned", id)
		}
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
