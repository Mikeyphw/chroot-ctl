package completion

import (
	"fmt"
	"sort"
	"strings"

	"chrootctl/internal/registry"
	resourceassets "chrootctl/resources"
)

var CommandNodes = []string{"status", "mount", "unmount", "fix-tty", "doctor", "logs", "start", "restart", "exec", "run", "enable", "disable", "journal", "install", "upgrade", "completion", "completion zsh", "chroots", "chroots list", "chroots show", "chroots remove", "chroots rename", "chroots export", "chroots import", "chroots diff", "chroots validate-import", "transfer", "transfer export", "transfer inspect", "transfer import", "events", "events list", "support-bundle", "clipboard", "clipboard daemon", "clipboard daemon start", "clipboard daemon stop", "clipboard daemon status", "clipboard daemon run", "clipboard set", "clipboard get", "clipboard doctor", "users", "users list", "users show", "users add", "users remove", "users password", "users shell", "users sudo", "users show-id", "users sync-id", "tools", "tools categories", "tools list", "tools show", "tools apply", "addons", "addons categories", "addons list", "addons show", "addons apply", "__complete", "magisk", "magisk render", "app"}

// GenerateZsh returns the exact completion program frozen from the Python
// implementation at GO07. It is embedded in the native binary, so completion
// generation has no Python/runtime filesystem dependency.
func GenerateZsh() string {
	data, err := resourceassets.FS.ReadFile("completion/chrootctl.zsh")
	if err != nil {
		return "#compdef chrootctl\n"
	}
	return string(data)
}

func ChrootNames(rows []registry.Chroot, installedOnly bool) string {
	names := []string{}
	for _, r := range rows {
		if installedOnly && !r.Installed {
			continue
		}
		names = append(names, r.Name)
	}
	sort.Strings(names)
	return strings.Join(names, "\n")
}
func ChrootDetails(rows []registry.Chroot) string {
	sort.Slice(rows, func(i, j int) bool { return rows[i].Name < rows[j].Name })
	out := []string{}
	for _, r := range rows {
		out = append(out, fmt.Sprintf("%s\t%s\t%s\t%s", r.Name, r.Distro, r.Phase, r.Path))
	}
	return strings.Join(out, "\n")
}
