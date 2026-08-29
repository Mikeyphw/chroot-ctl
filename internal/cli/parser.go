package cli

import (
	"fmt"
	"strconv"
	"strings"
)

type ArgumentSpec struct {
	Dest     string
	Options  []string
	Action   string
	NArgs    any
	Default  any
	Choices  []string
	Type     string
	Required bool
	Help     string
}

type CommandSpec struct {
	Command     string
	Path        []string
	Description string
	Epilog      string
	Arguments   []ArgumentSpec
}

type Globals struct {
	ConfigPath     string
	DryRun         bool
	Verbose        bool
	JSON           bool
	NoSudo         bool
	Name           string
	NonInteractive bool
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

func Parse(args []string) (Invocation, error) {
	inv := Invocation{Values: map[string]any{}}
	if len(args) == 0 {
		return inv, fmt.Errorf("command is required")
	}
	i := 0
	for i < len(args) {
		a := args[i]
		switch a {
		case "--config":
			if i+1 >= len(args) {
				return inv, fmt.Errorf("--config requires a value")
			}
			inv.Globals.ConfigPath = args[i+1]
			i += 2
		case "--dry-run":
			inv.Globals.DryRun = true
			i++
		case "--verbose":
			inv.Globals.Verbose = true
			i++
		case "--json":
			inv.Globals.JSON = true
			i++
		case "--no-sudo":
			inv.Globals.NoSudo = true
			i++
		case "--name":
			if i+1 >= len(args) {
				return inv, fmt.Errorf("--name requires a value")
			}
			inv.Globals.Name = args[i+1]
			i += 2
		case "--non-interactive":
			inv.Globals.NonInteractive = true
			i++
		case "-h", "--help":
			inv.Help = true
			i++
		default:
			goto command
		}
	}
command:
	if i >= len(args) {
		if inv.Help {
			return inv, nil
		}
		return inv, fmt.Errorf("command is required")
	}
	sm := specMap()
	var selected CommandSpec
	consumed := 0
	max := 3
	if len(args)-i < max {
		max = len(args) - i
	}
	for n := max; n >= 1; n-- {
		key := strings.Join(args[i:i+n], " ")
		if s, ok := sm[key]; ok {
			selected = s
			consumed = n
			break
		}
	}
	if consumed == 0 {
		return inv, fmt.Errorf("unknown command: %s", args[i])
	}
	inv.Spec = selected
	i += consumed
	if selected.Command == "app" {
		rest := append([]string(nil), args[i:]...)
		inv.Values["bridge_args"] = rest
		return inv, nil
	}
	for _, a := range selected.Arguments {
		if a.Default == nil {
			continue
		}
		switch v := a.Default.(type) {
		case []any:
			ss := make([]string, 0, len(v))
			for _, x := range v {
				ss = append(ss, fmt.Sprint(x))
			}
			inv.Values[a.Dest] = ss
		default:
			inv.Values[a.Dest] = v
		}
	}
	optionByName := map[string]ArgumentSpec{}
	positionals := []ArgumentSpec{}
	for _, a := range selected.Arguments {
		if len(a.Options) == 0 {
			positionals = append(positionals, a)
			continue
		}
		for _, o := range a.Options {
			optionByName[o] = a
		}
	}
	positionalTokens := []string{}
	hasRemainder := false
	for _, p := range positionals {
		if fmt.Sprint(p.NArgs) == "..." {
			hasRemainder = true
		}
	}
	for i < len(args) {
		tok := args[i]
		if tok == "-h" || tok == "--help" {
			inv.Help = true
			i++
			continue
		}
		if tok == "--" {
			positionalTokens = append(positionalTokens, args[i+1:]...)
			i = len(args)
			break
		}
		name, value, hasEq := tok, "", false
		if strings.HasPrefix(tok, "--") {
			if j := strings.IndexByte(tok, '='); j > 2 {
				name, value, hasEq = tok[:j], tok[j+1:], true
			}
		}
		if a, ok := optionByName[name]; ok {
			switch a.Action {
			case "_StoreTrueAction":
				if hasEq {
					return inv, fmt.Errorf("%s does not take a value", name)
				}
				inv.Values[a.Dest] = true
				i++
			case "_StoreFalseAction":
				if hasEq {
					return inv, fmt.Errorf("%s does not take a value", name)
				}
				inv.Values[a.Dest] = false
				i++
			case "_StoreAction", "_AppendAction":
				if !hasEq {
					if i+1 >= len(args) {
						return inv, fmt.Errorf("%s requires a value", name)
					}
					value = args[i+1]
					i += 2
				} else {
					i++
				}
				parsed, e := parseScalar(a, value)
				if e != nil {
					return inv, e
				}
				if a.Action == "_AppendAction" {
					xs, _ := inv.Values[a.Dest].([]string)
					xs = append(xs, fmt.Sprint(parsed))
					inv.Values[a.Dest] = xs
				} else {
					inv.Values[a.Dest] = parsed
				}
			default:
				return inv, fmt.Errorf("unsupported argument action %s", a.Action)
			}
			continue
		}
		if strings.HasPrefix(tok, "-") && tok != "-" {
			return inv, fmt.Errorf("unrecognized argument: %s", tok)
		}
		if hasRemainder {
			positionalTokens = append(positionalTokens, args[i:]...)
			i = len(args)
			break
		}
		positionalTokens = append(positionalTokens, tok)
		i++
	}
	pi := 0
	for idx, a := range positionals {
		last := idx == len(positionals)-1
		switch fmt.Sprint(a.NArgs) {
		case "...", "*":
			inv.Values[a.Dest] = append([]string(nil), positionalTokens[pi:]...)
			pi = len(positionalTokens)
		case "+":
			if pi >= len(positionalTokens) {
				return inv, fmt.Errorf("%s is required", a.Dest)
			}
			inv.Values[a.Dest] = append([]string(nil), positionalTokens[pi:]...)
			pi = len(positionalTokens)
		case "?":
			if pi < len(positionalTokens) {
				v, e := parseScalar(a, positionalTokens[pi])
				if e != nil {
					return inv, e
				}
				inv.Values[a.Dest] = v
				pi++
			}
		default:
			if pi >= len(positionalTokens) {
				if a.Required {
					return inv, fmt.Errorf("%s is required", a.Dest)
				}
			} else {
				v, e := parseScalar(a, positionalTokens[pi])
				if e != nil {
					return inv, e
				}
				inv.Values[a.Dest] = v
				pi++
			}
		}
		if last && pi < len(positionalTokens) {
			return inv, fmt.Errorf("unexpected argument: %s", positionalTokens[pi])
		}
	}
	if len(positionals) == 0 && len(positionalTokens) > 0 {
		return inv, fmt.Errorf("unexpected argument: %s", positionalTokens[0])
	}
	for _, a := range selected.Arguments {
		if !a.Required {
			continue
		}
		if _, ok := inv.Values[a.Dest]; !ok {
			return inv, fmt.Errorf("%s is required", a.Dest)
		}
	}
	return inv, nil
}

func parseScalar(a ArgumentSpec, raw string) (any, error) {
	var v any = raw
	switch a.Type {
	case "int":
		n, e := strconv.Atoi(raw)
		if e != nil {
			return nil, fmt.Errorf("%s must be an integer", a.Dest)
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
