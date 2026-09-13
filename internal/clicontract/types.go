package clicontract

type ArgumentSpec struct {
	Dest       string
	Options    []string
	Action     string
	NArgs      any
	Default    any
	Choices    []string
	Type       string
	Required   bool
	Help       string
	Completion string
	Minimum    any
	Maximum    any
}

type PrivilegeRule struct {
	AnyTrue []string
	Level   string
}

type CommandSpec struct {
	Command            string
	Path               []string
	Description        string
	Epilog             string
	Arguments          []ArgumentSpec
	Handler            string
	Group              bool
	Hidden             bool
	CompletionExposed  bool
	OutputModes        []string
	StreamMode         string
	Privilege          string
	Mutability         string
	HealthExitPolicy   string
	ExclusiveGroups    [][]string
	RequireOneOfGroups [][]string
	JSONForbiddenWhen  []string
	PrivilegeRules     []PrivilegeRule
}

func (s CommandSpec) SupportsOutput(mode string) bool {
	for _, candidate := range s.OutputModes {
		if candidate == mode {
			return true
		}
	}
	return false
}

func (s CommandSpec) EffectivePrivilege(values map[string]any) string {
	for _, rule := range s.PrivilegeRules {
		for _, key := range rule.AnyTrue {
			if value, ok := values[key].(bool); ok && value {
				return rule.Level
			}
		}
	}
	return s.Privilege
}
