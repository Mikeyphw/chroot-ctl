package completion

import (
	"fmt"
	"sort"
	"strings"

	"chrootctl/internal/clicontract"
	"chrootctl/internal/registry"
)

var CommandNodes = func() []string {
	out := make([]string, 0, len(clicontract.CommandSpecs))
	for _, spec := range clicontract.CommandSpecs {
		out = append(out, spec.Command)
	}
	return out
}()

// GenerateZsh renders completion directly from the same generated command
// contract consumed by the parser. There is intentionally no fallback script:
// generator/contract defects are returned to the caller instead of producing a
// successful-looking but incomplete completion program.
func GenerateZsh() (string, error) {
	roots := []string{}
	rootSeen := map[string]bool{}
	children := map[string][]string{}
	byCommand := map[string]clicontract.CommandSpec{}
	for _, spec := range clicontract.CommandSpecs {
		if !spec.CompletionExposed || spec.Hidden || len(spec.Path) == 0 || spec.Command == "app" || spec.Command == "__complete" {
			continue
		}
		byCommand[spec.Command] = spec
		root := spec.Path[0]
		if !rootSeen[root] {
			roots = append(roots, root)
			rootSeen[root] = true
		}
		if len(spec.Path) > 1 {
			parent := strings.Join(spec.Path[:len(spec.Path)-1], " ")
			child := spec.Path[len(spec.Path)-1]
			children[parent] = appendUnique(children[parent], child)
		}
	}
	if len(roots) == 0 {
		return "", fmt.Errorf("CLI contract exposes no completion commands")
	}

	var b strings.Builder
	b.WriteString("#compdef chrootctl chc\n\n")
	b.WriteString("# Generated from migration/contracts/v1/cli.json. Do not edit.\n")
	b.WriteString("typeset -g _chrootctl_prog=\"chrootctl\"\n")
	b.WriteString("_chrootctl_dynamic() { \"${_chrootctl_prog}\" __complete \"$@\" 2>/dev/null }\n")
	b.WriteString("_chrootctl_complete_chroots() { local -a x; x=(${(f)\"$(_chrootctl_dynamic chroots)\"}); compadd -a x }\n")
	b.WriteString("_chrootctl_complete_installed_chroots() { local -a x; x=(${(f)\"$(_chrootctl_dynamic installed-chroots)\"}); compadd -a x }\n")
	b.WriteString("_chrootctl_complete_users() { local -a x; x=(${(f)\"$(_chrootctl_dynamic users)\"}); compadd -a x }\n")
	b.WriteString("_chrootctl_complete_tools() { local -a x; x=(${(f)\"$(_chrootctl_dynamic tools)\"}); compadd -a x }\n")
	b.WriteString("_chrootctl_complete_addons() { local -a x; x=(${(f)\"$(_chrootctl_dynamic addons)\"}); compadd -a x }\n")
	b.WriteString("_chrootctl_complete_tool_categories() { local -a x; x=(${(f)\"$(_chrootctl_dynamic tool-categories)\"}); compadd -a x }\n")
	b.WriteString("_chrootctl_complete_addon_categories() { local -a x; x=(${(f)\"$(_chrootctl_dynamic addon-categories)\"}); compadd -a x }\n\n")
	b.WriteString("_chrootctl() {\n  local curcontext=\"$curcontext\" state line\n  typeset -A opt_args\n  _chrootctl_prog=\"${words[1]:-chrootctl}\"\n")
	b.WriteString("  _arguments -C \\\n")
	for _, g := range clicontract.GlobalArguments {
		b.WriteString("    " + zshArgument(g) + " \\\n")
	}
	b.WriteString("    '1:command:(" + strings.Join(roots, " ") + ")' \\\n    '*::args:->args'\n")
	b.WriteString("  [[ $state == args ]] || return\n")
	b.WriteString("  local -a cmdwords\n  cmdwords=(${line:#-*})\n  local key=\"${(j: :)cmdwords}\"\n")
	// Prefer longest known command prefix. zsh line excludes already processed globals.
	commands := make([]string, 0, len(byCommand))
	for command := range byCommand {
		commands = append(commands, command)
	}
	sort.Slice(commands, func(i, j int) bool {
		ai, aj := len(strings.Fields(commands[i])), len(strings.Fields(commands[j]))
		if ai == aj {
			return commands[i] < commands[j]
		}
		return ai > aj
	})
	b.WriteString("  case \"$key\" in\n")
	for _, command := range commands {
		spec := byCommand[command]
		pattern := zshSingle(command + "*")
		b.WriteString("    " + pattern + ")\n")
		if kids := children[command]; len(kids) > 0 {
			sort.Strings(kids)
			b.WriteString("      if (( CURRENT <= " + fmt.Sprint(len(spec.Path)+2) + " )); then compadd " + strings.Join(kids, " ") + "; return; fi\n")
		}
		args := []string{}
		for _, a := range spec.Arguments {
			if a.Help != "<SUPPRESS>" {
				args = append(args, zshArgument(a))
			}
		}
		if len(args) > 0 {
			b.WriteString("      _arguments " + strings.Join(args, " ") + "\n")
		}
		b.WriteString("      ;;\n")
	}
	b.WriteString("  esac\n}\n\ncompdef _chrootctl chrootctl chc\n")
	return b.String(), nil
}

func zshArgument(a clicontract.ArgumentSpec) string {
	help := strings.ReplaceAll(strings.ReplaceAll(a.Help, "[", "("), "]", ")")
	if len(a.Options) == 0 {
		label := a.Dest
		suffix := zshCompletion(a)
		switch fmt.Sprint(a.NArgs) {
		case "*", "+", "...":
			return zshSingle("*:" + label + ":" + suffix)
		case "?":
			return zshSingle("1:" + label + ":" + suffix)
		default:
			return zshSingle("1:" + label + ":" + suffix)
		}
	}
	option := a.Options[0]
	value := ""
	if a.Action == "_StoreAction" || a.Action == "_AppendAction" {
		value = ":" + a.Dest + ":" + zshCompletion(a)
	}
	return zshSingle(option + "[" + help + "]" + value)
}

func zshCompletion(a clicontract.ArgumentSpec) string {
	if len(a.Choices) > 0 {
		return "(" + strings.Join(a.Choices, " ") + ")"
	}
	switch a.Completion {
	case "path":
		return "_files"
	case "chroots":
		return "_chrootctl_complete_chroots"
	case "installed-chroots":
		return "_chrootctl_complete_installed_chroots"
	case "users":
		return "_chrootctl_complete_users"
	case "tools":
		return "_chrootctl_complete_tools"
	case "addons":
		return "_chrootctl_complete_addons"
	case "tool-categories":
		return "_chrootctl_complete_tool_categories"
	case "addon-categories":
		return "_chrootctl_complete_addon_categories"
	}
	return ""
}

func zshSingle(value string) string { return "'" + strings.ReplaceAll(value, "'", "'\\''") + "'" }
func appendUnique(values []string, value string) []string {
	for _, current := range values {
		if current == value {
			return values
		}
	}
	return append(values, value)
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
