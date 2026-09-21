package module

import (
	"strings"
	"testing"
)

func TestCustomizeLiveUpdatesExistingActiveModuleTransactionally(t *testing.T) {
	s := customize()
	required := []string{
		`ACTIVE_MODULE="/data/adb/modules/chrootctl-magisk"`,
		`.chrootctl-magisk.live-new.$$`, `.chrootctl-magisk.live-old.$$`,
		`cp -a "$ACTIVE_MODULE/." "$LIVE_NEXT/"`,
		`for rel in module.prop customize.sh post-fs-data.sh service.sh action.sh uninstall.sh bin system config runtime webroot`,
		`mv "$ACTIVE_MODULE" "$LIVE_OLD" && mv "$LIVE_NEXT" "$ACTIVE_MODULE"`,
		`mv "$LIVE_OLD" "$ACTIVE_MODULE"`,
		`"$ACTIVE_MODULE/post-fs-data.sh"`, `"$ACTIVE_MODULE/service.sh"`,
		`staged update is preserved for reboot activation`,
	}
	for _, want := range required {
		if !strings.Contains(s, want) {
			t.Fatalf("live update installer missing %q", want)
		}
	}
}

func TestCustomizeLiveUpdatePreservesManagerMarkersAndRequiresSealedRuntime(t *testing.T) {
	s := customize()
	if strings.Contains(s, `rm -rf "$ACTIVE_MODULE"`) {
		t.Fatal("live update must not destroy the active module before rollback backup")
	}
	for _, want := range []string{`cp -a "$ACTIVE_MODULE/." "$LIVE_NEXT/"`, `config/chrootctl/module-package-manifest.json`, `runtime/arm64-v8a/runtime-manifest.json`, `runtime/arm64-v8a/chrootctl`, `[ ! -e "$ACTIVE_MODULE/disable" ]`, `[ ! -e "$ACTIVE_MODULE/remove" ]`} {
		if !strings.Contains(s, want) {
			t.Fatalf("live update safety contract missing %q", want)
		}
	}
}
