package cli

import (
	"fmt"
	"strconv"
	"strings"

	"chrootctl/internal/clicontract"
)

type ArgumentSpec = clicontract.ArgumentSpec
type CommandSpec = clicontract.CommandSpec

var GlobalArguments = clicontract.GlobalArguments
var CommandSpecs = clicontract.CommandSpecs

type Globals struct {
	ConfigPath     string
	DryRun         bool
	Verbose        bool
	JSON           bool
	NoSudo         bool
	Name           string
	NonInteractive bool
	Version        bool
}

type Invocation struct {
	Globals Globals
	Spec    CommandSpec
	Values  map[string]any
	Help    bool
}

func specMap() map[string]CommandSpec {
	out := make(map[string]CommandSpec, len(CommandSpecs))
	for _, s := range CommandSpecs {
		out[s.Command] = s
	}
	return out
}

func maxCommandDepth() int {
	max := 1
	for _, spec := range CommandSpecs {
		if len(spec.Path) > max {
			max = len(spec.Path)
		}
	}
	return max
}

func globalOptionMap() map[string]ArgumentSpec {
	out := map[string]ArgumentSpec{}
	for _, arg := range GlobalArguments {
		for _, option := range arg.Options {
			out[option] = arg
		}
	}
	return out
}

// HelpSpecForArgs finds the longest command path while ignoring globals on
// either side of the command. It never validates required command arguments.
func HelpSpecForArgs(args []string) (CommandSpec, bool) {
	_, spec, _, ok := locateCommand(args)
	return spec, ok
}

func locateCommand(args []string) (Globals, CommandSpec, int, bool) {
	globals := Globals{}
	gm := globalOptionMap()
	i := 0
	for i < len(args) {
		if args[i] == "-h" || args[i] == "--help" {
			i++
			continue
		}
		name, value, hasEq := splitOption(args[i])
		if g, ok := gm[name]; ok {
			consumed, err := applyGlobal(&globals, g, name, value, hasEq, args, i)
			if err != nil {
				return globals, CommandSpec{}, i, false
			}
			i += consumed
			continue
		}
		break
	}
	if i >= len(args) {
		return globals, CommandSpec{}, i, false
	}
	sm := specMap()
	max := maxCommandDepth()
	if len(args)-i < max {
		max = len(args) - i
	}
	for n := max; n >= 1; n-- {
		key := strings.Join(args[i:i+n], " ")
		if spec, ok := sm[key]; ok {
			return globals, spec, i + n, true
		}
	}
	return globals, CommandSpec{}, i, false
}

func Parse(args []string) (Invocation, error) {
	inv := Invocation{Values: map[string]any{}}
	if len(args) == 0 {
		return inv, fmt.Errorf("command is required")
	}

	// Parse leading globals while locating the command.
	gm := globalOptionMap()
	i := 0
	for i < len(args) {
		if args[i] == "-h" || args[i] == "--help" {
			inv.Help = true
			i++
			continue
		}
		name, value, hasEq := splitOption(args[i])
		g, ok := gm[name]
		if !ok {
			break
		}
		consumed, err := applyGlobal(&inv.Globals, g, name, value, hasEq, args, i)
		if err != nil {
			return inv, err
		}
		i += consumed
	}
	if inv.Globals.Version && i >= len(args) {
		inv.Spec = specMap()["version"]
		return inv, nil
	}
	if i >= len(args) {
		if inv.Help {
			return inv, nil
		}
		return inv, fmt.Errorf("command is required")
	}

	sm := specMap()
	max := maxCommandDepth()
	if len(args)-i < max {
		max = len(args) - i
	}
	consumed := 0
	for n := max; n >= 1; n-- {
		key := strings.Join(args[i:i+n], " ")
		if spec, ok := sm[key]; ok {
			inv.Spec = spec
			consumed = n
			break
		}
	}
	if consumed == 0 {
		return inv, fmt.Errorf("unknown command: %s", args[i])
	}
	i += consumed
	if inv.Globals.Version {
		// --version is an early global action regardless of the command token that follows.
		inv.Spec = sm["version"]
		return inv, nil
	}
	if inv.Spec.Command == "app" {
		if inv.Globals.JSON {
			return inv, fmt.Errorf("--json is not supported for command: app")
		}
		inv.Values["bridge_args"] = append([]string(nil), args[i:]...)
		return inv, nil
	}

	for _, a := range inv.Spec.Arguments {
		setDefault(inv.Values, a)
	}
	optionByName := map[string]ArgumentSpec{}
	positionals := []ArgumentSpec{}
	for _, a := range inv.Spec.Arguments {
		if len(a.Options) == 0 {
			positionals = append(positionals, a)
			continue
		}
		for _, option := range a.Options {
			optionByName[option] = a
		}
	}
	positionalTokens := []string{}
	hasRemainder := false
	for _, p := range positionals {
		if fmt.Sprint(p.NArgs) == "..." {
			hasRemainder = true
		}
	}
	remainderStarted := false

	for i < len(args) {
		tok := args[i]
		if !remainderStarted && (tok == "-h" || tok == "--help") {
			inv.Help = true
			i++
			continue
		}
		if tok == "--" {
			positionalTokens = append(positionalTokens, args[i+1:]...)
			i = len(args)
			remainderStarted = true
			break
		}
		name, value, hasEq := splitOption(tok)
		if !remainderStarted {
			// Command-local options intentionally win collisions with globals.
			if a, ok := optionByName[name]; ok {
				used, err := applyArgument(inv.Values, a, name, value, hasEq, args, i)
				if err != nil {
					return inv, err
				}
				i += used
				continue
			}
			if g, ok := gm[name]; ok {
				used, err := applyGlobal(&inv.Globals, g, name, value, hasEq, args, i)
				if err != nil {
					return inv, err
				}
				i += used
				if inv.Globals.Version {
					inv.Spec = sm["version"]
					return inv, nil
				}
				continue
			}
		}
		if strings.HasPrefix(tok, "-") && tok != "-" && !(hasRemainder && remainderStarted) {
			return inv, fmt.Errorf("unrecognized argument: %s", tok)
		}
		if hasRemainder {
			remainderStarted = true
			positionalTokens = append(positionalTokens, args[i:]...)
			i = len(args)
			break
		}
		positionalTokens = append(positionalTokens, tok)
		i++
	}

	// Help is deliberately usable even when required values/groups are absent.
	if inv.Help {
		return inv, nil
	}
	if err := bindPositionals(&inv, positionals, positionalTokens); err != nil {
		return inv, err
	}
	for _, a := range inv.Spec.Arguments {
		if !a.Required {
			continue
		}
		if _, ok := inv.Values[a.Dest]; !ok {
			return inv, fmt.Errorf("%s is required", a.Dest)
		}
	}
	if err := validateGroups(inv.Spec, inv.Values); err != nil {
		return inv, err
	}
	if inv.Globals.JSON {
		if !inv.Spec.SupportsOutput("json") {
			return inv, fmt.Errorf("--json is not supported for command: %s", inv.Spec.Command)
		}
		for _, key := range inv.Spec.JSONForbiddenWhen {
			if truthy(inv.Values[key]) {
				return inv, fmt.Errorf("--json cannot be combined with %s for command: %s", optionLabel(inv.Spec, key), inv.Spec.Command)
			}
		}
	}
	return inv, nil
}

func splitOption(token string) (name, value string, hasEq bool) {
	name = token
	if strings.HasPrefix(token, "--") {
		if j := strings.IndexByte(token, '='); j > 2 {
			return token[:j], token[j+1:], true
		}
	}
	return name, "", false
}

func setDefault(values map[string]any, a ArgumentSpec) {
	if a.Default == nil {
		return
	}
	switch v := a.Default.(type) {
	case []any:
		ss := make([]string, 0, len(v))
		for _, x := range v {
			ss = append(ss, fmt.Sprint(x))
		}
		values[a.Dest] = ss
	default:
		values[a.Dest] = v
	}
}

func applyGlobal(globals *Globals, a ArgumentSpec, name, value string, hasEq bool, args []string, i int) (int, error) {
	used := 1
	if a.Action == "_StoreAction" {
		if !hasEq {
			if i+1 >= len(args) {
				return 0, fmt.Errorf("%s requires a value", name)
			}
			value = args[i+1]
			used = 2
		}
	}
	if (a.Action == "_StoreTrueAction" || a.Action == "_VersionAction") && hasEq {
		return 0, fmt.Errorf("%s does not take a value", name)
	}
	switch a.Dest {
	case "config":
		globals.ConfigPath = value
	case "dry_run":
		globals.DryRun = true
	case "verbose":
		globals.Verbose = true
	case "json":
		globals.JSON = true
	case "no_sudo":
		globals.NoSudo = true
	case "name":
		globals.Name = value
	case "non_interactive":
		globals.NonInteractive = true
	case "version":
		globals.Version = true
	default:
		return 0, fmt.Errorf("unsupported global argument: %s", a.Dest)
	}
	return used, nil
}

func applyArgument(values map[string]any, a ArgumentSpec, name, value string, hasEq bool, args []string, i int) (int, error) {
	switch a.Action {
	case "_StoreTrueAction":
		if hasEq {
			return 0, fmt.Errorf("%s does not take a value", name)
		}
		values[a.Dest] = true
		return 1, nil
	case "_StoreFalseAction":
		if hasEq {
			return 0, fmt.Errorf("%s does not take a value", name)
		}
		values[a.Dest] = false
		return 1, nil
	case "_StoreAction", "_AppendAction":
		used := 1
		if !hasEq {
			if i+1 >= len(args) {
				return 0, fmt.Errorf("%s requires a value", name)
			}
			value = args[i+1]
			used = 2
		}
		parsed, err := parseScalar(a, value)
		if err != nil {
			return 0, err
		}
		if a.Action == "_AppendAction" {
			xs, _ := values[a.Dest].([]string)
			values[a.Dest] = append(xs, fmt.Sprint(parsed))
		} else {
			values[a.Dest] = parsed
		}
		return used, nil
	default:
		return 0, fmt.Errorf("unsupported argument action %s", a.Action)
	}
}

func bindPositionals(inv *Invocation, positionals []ArgumentSpec, tokens []string) error {
	pi := 0
	for idx, a := range positionals {
		last := idx == len(positionals)-1
		switch fmt.Sprint(a.NArgs) {
		case "...", "*":
			inv.Values[a.Dest] = append([]string(nil), tokens[pi:]...)
			pi = len(tokens)
		case "+":
			if pi >= len(tokens) {
				return fmt.Errorf("%s is required", a.Dest)
			}
			inv.Values[a.Dest] = append([]string(nil), tokens[pi:]...)
			pi = len(tokens)
		case "?":
			if pi < len(tokens) {
				v, err := parseScalar(a, tokens[pi])
				if err != nil {
					return err
				}
				inv.Values[a.Dest] = v
				pi++
			}
		default:
			if pi >= len(tokens) {
				if a.Required {
					return fmt.Errorf("%s is required", a.Dest)
				}
			} else {
				v, err := parseScalar(a, tokens[pi])
				if err != nil {
					return err
				}
				inv.Values[a.Dest] = v
				pi++
			}
		}
		if last && pi < len(tokens) {
			return fmt.Errorf("unexpected argument: %s", tokens[pi])
		}
	}
	if len(positionals) == 0 && len(tokens) > 0 {
		return fmt.Errorf("unexpected argument: %s", tokens[0])
	}
	return nil
}

func validateGroups(spec CommandSpec, values map[string]any) error {
	for _, group := range spec.ExclusiveGroups {
		set := []string{}
		for _, key := range group {
			if truthy(values[key]) {
				set = append(set, optionLabel(spec, key))
			}
		}
		if len(set) > 1 {
			return fmt.Errorf("arguments %s are mutually exclusive", strings.Join(set, ", "))
		}
	}
	for _, group := range spec.RequireOneOfGroups {
		ok := false
		labels := []string{}
		for _, key := range group {
			labels = append(labels, optionLabel(spec, key))
			if truthy(values[key]) {
				ok = true
			}
		}
		if !ok {
			return fmt.Errorf("one of %s is required", strings.Join(labels, ", "))
		}
	}
	return nil
}

func optionLabel(spec CommandSpec, dest string) string {
	for _, a := range spec.Arguments {
		if a.Dest == dest {
			if len(a.Options) > 0 {
				return a.Options[0]
			}
			return a.Dest
		}
	}
	return dest
}

func truthy(v any) bool {
	switch x := v.(type) {
	case bool:
		return x
	case string:
		return x != ""
	case []string:
		return len(x) > 0
	case int:
		return x != 0
	default:
		return v != nil
	}
}

func parseScalar(a ArgumentSpec, raw string) (any, error) {
	var v any = raw
	switch a.Type {
	case "int":
		n, err := strconv.Atoi(raw)
		if err != nil {
			return nil, fmt.Errorf("%s must be an integer", a.Dest)
		}
		if a.Minimum != nil {
			min, _ := strconv.Atoi(fmt.Sprint(a.Minimum))
			if n < min {
				return nil, fmt.Errorf("%s must be at least %d", a.Dest, min)
			}
		}
		if a.Maximum != nil {
			max, _ := strconv.Atoi(fmt.Sprint(a.Maximum))
			if n > max {
				return nil, fmt.Errorf("%s must be at most %d", a.Dest, max)
			}
		}
		v = n
	case "upper":
		v = strings.ToUpper(raw)
	}
	if len(a.Choices) > 0 {
		s := fmt.Sprint(v)
		ok := false
		for _, c := range a.Choices {
			if s == c {
				ok = true
				break
			}
		}
		if !ok {
			return nil, fmt.Errorf("invalid %s %q (choose from %s)", a.Dest, s, strings.Join(a.Choices, ", "))
		}
	}
	return v, nil
}

func (i Invocation) String(key string) string {
	if v, ok := i.Values[key]; ok && v != nil {
		return fmt.Sprint(v)
	}
	return ""
}
func (i Invocation) Bool(key string) bool { v, ok := i.Values[key].(bool); return ok && v }
func (i Invocation) Int(key string, fallback int) int {
	if v, ok := i.Values[key].(int); ok {
		return v
	}
	return fallback
}
func (i Invocation) Strings(key string) []string {
	if v, ok := i.Values[key].([]string); ok {
		return append([]string(nil), v...)
	}
	return nil
}
