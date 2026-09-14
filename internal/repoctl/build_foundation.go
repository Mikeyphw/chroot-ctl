package repoctl

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type behaviorOwnership struct {
	SchemaVersion int               `json:"schemaVersion"`
	Policy        string            `json:"policy"`
	Surfaces      []behaviorSurface `json:"surfaces"`
}

type behaviorSurface struct {
	Path      string             `json:"path"`
	Behaviors []behaviorContract `json:"behaviors"`
}

type behaviorContract struct {
	ID           string `json:"id"`
	OwnerOverlay string `json:"ownerOverlay"`
	DirectTest   string `json:"directTest"`
}

// ValidateBuildFoundation is the executable CHR01 regression contract.  It
// protects the build/Devtool decisions that are otherwise easy to regress by
// copying an old config snippet or re-splitting validation across processes.
func ValidateBuildFoundation(root string) error {
	read := func(rel string) (string, error) {
		raw, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(rel)))
		if err != nil {
			return "", fmt.Errorf("read CHR01 contract %s: %w", rel, err)
		}
		return string(raw), nil
	}

	devtool, err := read(".devtool.toml")
	if err != nil {
		return err
	}
	for _, required := range []string{
		"[project]\nrunner = \"go\"\nplatform = \"workspace\"",
		"[targets.chrootctl_go]\nrunner = \"go\"\nplatform = \"cli\"",
		"[targets.chrootctl_android]\nrunner = \"android\"\nplatform = \"android\"",
		"[targets.chrootctl]\nrunner = \"command\"\nplatform = \"release\"",
		"outputs = [",
		"split_gradle = false",
		"memory_guard_mb = 0",
		"preflight = [\":chrootctlAndroidAppSeal\"]",
		"dependencies = []",
		"compile = []",
		"resources = []",
		"test_command = \"go run ./cmd/repoctl validate\"",
		"run_command = \"go run ./cmd/repoctl host\"",
		"validate = [\"runner:command#test\"]",
	} {
		if !strings.Contains(devtool, required) {
			return fmt.Errorf("CHR01 Devtool contract missing %q", required)
		}
	}
	for _, forbidden := range []string{
		"kind = \"go\"",
		"type = \"go\"",
		"type = \"android\"",
		"type = \"command\"",
		"coalesce_validation",
		"--no-configuration-cache",
		"-Dorg.gradle.parallel=true",
		"-Pkotlin.incremental=true",
		"-Pkotlin.compiler.execution.strategy=in-process",
		"GOOS = \"android\"",
		"GOARCH = \"arm64\"",
	} {
		if strings.Contains(devtool, forbidden) {
			return fmt.Errorf("CHR01 Devtool contract contains retired/duplicated setting %q", forbidden)
		}
	}
	goSection := section(devtool, "[targets.chrootctl_go]", "[targets.chrootctl_go.go]")
	if strings.Contains(goSection, "root = \".\"") || !strings.Contains(goSection, "inputs = [") || !strings.Contains(goSection, "outputs = [") {
		return fmt.Errorf("CHR01 Go target must use explicit ownership/output scopes without root=\".\"")
	}

	gradleProperties, err := read("android/gradle.properties")
	if err != nil {
		return err
	}
	if !strings.Contains(gradleProperties, "org.gradle.configuration-cache=true") {
		return fmt.Errorf("CHR01 Gradle configuration cache is not enabled")
	}
	for _, forbidden := range []string{"ActiveProcessorCount", "org.gradle.workers.max="} {
		if strings.Contains(gradleProperties, forbidden) {
			return fmt.Errorf("CHR01 Gradle properties still hard-cap resources with %q", forbidden)
		}
	}

	rootBuild, err := read("android/build.gradle.kts")
	if err != nil {
		return err
	}
	for _, required := range []string{
		"inputs.files(",
		"outputs.file(baselineStampFile)",
		"outputs.cacheIf { true }",
		"tasks.register(\"chrootctlDebugValidation\")",
		"dependsOn(chrootctlAndroidLintConfigurationSeal)",
		"dependsOn(\":app:testDebugUnitTest\", \":app:assembleDebug\")",
		"tasks.register(\"chrootctlAndroidAppSeal\")",
		"dependsOn(chrootctlDebugValidation)",
	} {
		if !strings.Contains(rootBuild, required) {
			return fmt.Errorf("CHR01 Gradle build contract missing %q", required)
		}
	}

	ci, err := read(".github/workflows/ci.yml")
	if err != nil {
		return err
	}
	if strings.Count(ci, "./gradlew --no-daemon") != 1 || !strings.Contains(ci, "--continue :chrootctlAndroidAppSeal") {
		return fmt.Errorf("CHR01 CI must invoke one authoritative Android app seal graph")
	}

	finalSeal, err := read("internal/repoctl/final_seal.go")
	if err != nil {
		return err
	}
	if strings.Count(finalSeal, `run(androidRoot, nil, "./gradlew"`) != 1 || !strings.Contains(finalSeal, `":chrootctlAndroidAppSeal"`) {
		return fmt.Errorf("CHR01 repoctl final seal must invoke the authoritative Android app seal graph")
	}

	androidReadme, err := read("android/README.md")
	if err != nil {
		return err
	}
	for _, required := range []string{"Go-native chrootctl backend", "Home, Chroots, Install, Activity, and Tools", ":chrootctlAndroidAppSeal"} {
		if !strings.Contains(androidReadme, required) {
			return fmt.Errorf("CHR01 Android README is stale; missing %q", required)
		}
	}
	if strings.Contains(androidReadme, "Python backend remains authoritative") {
		return fmt.Errorf("CHR01 Android README still declares Python authoritative")
	}

	behaviorRaw, err := os.ReadFile(filepath.Join(root, "docs", "android", "behavior-ownership.json"))
	if err != nil {
		return fmt.Errorf("read Android behavior ownership: %w", err)
	}
	var ownership behaviorOwnership
	if err := json.Unmarshal(behaviorRaw, &ownership); err != nil {
		return fmt.Errorf("parse Android behavior ownership: %w", err)
	}
	if ownership.SchemaVersion != 1 || ownership.Policy != "behavior-not-file" || len(ownership.Surfaces) != 3 {
		return fmt.Errorf("CHR01 behavior ownership manifest is incomplete")
	}
	requiredSurfaces := map[string]bool{
		"android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/chroots/ChrootsScreen.kt":    false,
		"android/app/src/main/kotlin/com/mikeyphw/chrootctl/ui/MainViewModel.kt":            false,
		"android/app/src/main/kotlin/com/mikeyphw/chrootctl/repository/BridgeRepository.kt": false,
	}
	hasDirectHomeTest := false
	for _, surface := range ownership.Surfaces {
		if _, ok := requiredSurfaces[surface.Path]; !ok {
			return fmt.Errorf("CHR01 behavior ownership has unexpected high-risk surface %q", surface.Path)
		}
		requiredSurfaces[surface.Path] = true
		if len(surface.Behaviors) == 0 {
			return fmt.Errorf("CHR01 behavior ownership surface %q has no behavior slices", surface.Path)
		}
		for _, behavior := range surface.Behaviors {
			if behavior.ID == "" || behavior.OwnerOverlay == "" {
				return fmt.Errorf("CHR01 behavior ownership surface %q has incomplete behavior", surface.Path)
			}
			if behavior.DirectTest == "HomeRefreshCoordinatorTest" {
				hasDirectHomeTest = true
			}
		}
	}
	for path, found := range requiredSurfaces {
		if !found {
			return fmt.Errorf("CHR01 behavior ownership is missing %q", path)
		}
	}
	if !hasDirectHomeTest {
		return fmt.Errorf("CHR01 behavior ownership lacks direct Home orchestration coverage")
	}
	if _, err := os.Stat(filepath.Join(root, "android", "app", "src", "test", "kotlin", "com", "mikeyphw", "chrootctl", "repository", "HomeRefreshCoordinatorTest.kt")); err != nil {
		return fmt.Errorf("CHR01 direct repository orchestration test is missing: %w", err)
	}
	return nil
}

func section(text, start, end string) string {
	after := strings.SplitN(text, start, 2)
	if len(after) != 2 {
		return ""
	}
	body := after[1]
	if end != "" {
		body = strings.SplitN(body, end, 2)[0]
	}
	return body
}
