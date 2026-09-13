package contracts

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

const (
	ContractSchemaVersion              = 1
	ExpectedCommandNodeCount           = 69
	ExpectedAppBridgeCommandNodeCount  = 8
	ExpectedBridgeOperationCount       = 86
	ExpectedBridgeProtocolVersion      = 1
	ExpectedOperationSchemaVersion     = 2
	ExpectedCompatibilitySchemaVersion = 3
	ExpectedNativeRuntimeSchemaVersion = 2
)

type CLIContract struct {
	ContractSchemaVersion     int        `json:"contractSchemaVersion"`
	PythonBackendVersion      string     `json:"pythonBackendVersion"`
	Program                   string     `json:"program"`
	CommandNodeCount          int        `json:"commandNodeCount"`
	CommandNodes              []CLINode  `json:"commandNodes"`
	AppBridgeCommandNodeCount int        `json:"appBridgeCommandNodeCount"`
	AppBridgeCommandNodes     []CLINode  `json:"appBridgeCommandNodes"`
	GlobalArguments           []Argument `json:"globalArguments"`
}

type CLINode struct {
	Path        []string   `json:"path"`
	Command     string     `json:"command"`
	Prog        string     `json:"prog"`
	Description *string    `json:"description"`
	Epilog      *string    `json:"epilog"`
	Arguments   []Argument `json:"arguments"`
}

type Argument struct {
	Dest          string   `json:"dest"`
	OptionStrings []string `json:"optionStrings"`
	Required      bool     `json:"required"`
	Action        string   `json:"action"`
}

type BridgeContract struct {
	ContractSchemaVersion int               `json:"contractSchemaVersion"`
	ProtocolVersion       int               `json:"protocolVersion"`
	OperationCount        int               `json:"operationCount"`
	Operations            []BridgeOperation `json:"operations"`
	Request               BridgeRequestSpec `json:"request"`
	ResponseFields        []string          `json:"responseFields"`
	Transports            []string          `json:"transports"`
	ArbitraryShell        bool              `json:"arbitraryShell"`
}

type BridgeOperation struct {
	Name          string   `json:"name"`
	Mode          string   `json:"mode"`
	Description   string   `json:"description"`
	Destructive   bool     `json:"destructive"`
	LockScope     string   `json:"lockScope"`
	PayloadFields []string `json:"payloadFields"`
}

type BridgeRequestSpec struct {
	MaxBytes              int      `json:"maxBytes"`
	MaxJSONDepth          int      `json:"maxJsonDepth"`
	MaxStringLength       int      `json:"maxStringLength"`
	MaxArrayLength        int      `json:"maxArrayLength"`
	MaxObjectKeys         int      `json:"maxObjectKeys"`
	TopLevelKeys          []string `json:"topLevelKeys"`
	RequestIDPattern      string   `json:"requestIdPattern"`
	OperationPattern      string   `json:"operationPattern"`
	PreviewContractFields []string `json:"previewContractFields"`
}

type PersistenceContract struct {
	ContractSchemaVersion int `json:"contractSchemaVersion"`
	Operations            struct {
		SchemaVersion  int      `json:"schemaVersion"`
		ActiveStates   []string `json:"activeStates"`
		TerminalStates []string `json:"terminalStates"`
		JSONFields     []string `json:"jsonFields"`
	} `json:"operations"`
	SQLite struct {
		SchemaSQL string `json:"schemaSql"`
	} `json:"sqlite"`
}

type FoundationsContract struct {
	ContractSchemaVersion int `json:"contractSchemaVersion"`
	Models                struct {
		FieldNames map[string][]string `json:"fieldNames"`
	} `json:"models"`
	Validation struct {
		Cases []struct {
			Name string `json:"name"`
			OK   bool   `json:"ok"`
		} `json:"cases"`
	} `json:"validation"`
	Logging struct {
		LoggerName  string `json:"loggerName"`
		LoggerLevel string `json:"loggerLevel"`
		Propagate   bool   `json:"propagate"`
	} `json:"logging"`
}

type ReleaseContract struct {
	ContractSchemaVersion      int `json:"contractSchemaVersion"`
	BridgeProtocolVersion      int `json:"bridgeProtocolVersion"`
	CompatibilitySchemaVersion int `json:"compatibilitySchemaVersion"`
	Backend                    struct {
		Implementation string `json:"implementation"`
		Version        string `json:"version"`
	} `json:"backend"`
	NativeRuntime struct {
		SchemaVersion int    `json:"schemaVersion"`
		Kind          string `json:"kind"`
		Platform      string `json:"platform"`
		ABI           string `json:"abi"`
		Entrypoint    string `json:"entrypoint"`
	} `json:"nativeRuntime"`
}

type Bundle struct {
	CLI         CLIContract
	Bridge      BridgeContract
	Persistence PersistenceContract
	Foundations FoundationsContract
	Release     ReleaseContract
}

func LoadDir(dir string) (Bundle, error) {
	var bundle Bundle
	loads := []struct {
		name string
		dst  any
	}{
		{"cli.json", &bundle.CLI},
		{"bridge.json", &bundle.Bridge},
		{"persistence.json", &bundle.Persistence},
		{"foundations.json", &bundle.Foundations},
		{"release.json", &bundle.Release},
	}
	for _, item := range loads {
		path := filepath.Join(dir, item.name)
		data, err := os.ReadFile(path)
		if err != nil {
			return Bundle{}, fmt.Errorf("read %s: %w", path, err)
		}
		if err := json.Unmarshal(data, item.dst); err != nil {
			return Bundle{}, fmt.Errorf("decode %s: %w", path, err)
		}
	}
	return bundle, nil
}

func (b Bundle) Validate() error {
	if b.CLI.ContractSchemaVersion != ContractSchemaVersion ||
		b.Bridge.ContractSchemaVersion != ContractSchemaVersion ||
		b.Persistence.ContractSchemaVersion != ContractSchemaVersion ||
		b.Foundations.ContractSchemaVersion != ContractSchemaVersion ||
		b.Release.ContractSchemaVersion != ContractSchemaVersion {
		return fmt.Errorf("unsupported migration contract schema: expected %d", ContractSchemaVersion)
	}
	if b.CLI.CommandNodeCount != ExpectedCommandNodeCount || len(b.CLI.CommandNodes) != ExpectedCommandNodeCount {
		return fmt.Errorf("CLI command-node count drift: expected %d, declared %d, decoded %d", ExpectedCommandNodeCount, b.CLI.CommandNodeCount, len(b.CLI.CommandNodes))
	}
	if b.CLI.AppBridgeCommandNodeCount != ExpectedAppBridgeCommandNodeCount || len(b.CLI.AppBridgeCommandNodes) != ExpectedAppBridgeCommandNodeCount {
		return fmt.Errorf("app bridge CLI node count drift: expected %d, declared %d, decoded %d", ExpectedAppBridgeCommandNodeCount, b.CLI.AppBridgeCommandNodeCount, len(b.CLI.AppBridgeCommandNodes))
	}
	if b.Bridge.ProtocolVersion != ExpectedBridgeProtocolVersion || b.Release.BridgeProtocolVersion != ExpectedBridgeProtocolVersion {
		return fmt.Errorf("bridge protocol drift: expected %d", ExpectedBridgeProtocolVersion)
	}
	if b.Bridge.OperationCount != ExpectedBridgeOperationCount || len(b.Bridge.Operations) != ExpectedBridgeOperationCount {
		return fmt.Errorf("bridge operation count drift: expected %d, declared %d, decoded %d", ExpectedBridgeOperationCount, b.Bridge.OperationCount, len(b.Bridge.Operations))
	}
	if b.Persistence.Operations.SchemaVersion != ExpectedOperationSchemaVersion {
		return fmt.Errorf("operation journal schema drift: expected %d, got %d", ExpectedOperationSchemaVersion, b.Persistence.Operations.SchemaVersion)
	}
	if b.Release.CompatibilitySchemaVersion != ExpectedCompatibilitySchemaVersion {
		return fmt.Errorf("compatibility manifest schema drift: expected %d, got %d", ExpectedCompatibilitySchemaVersion, b.Release.CompatibilitySchemaVersion)
	}
	if b.Release.Backend.Implementation != "go" || b.Release.Backend.Version == "" {
		return fmt.Errorf("GO13 backend identity drift: implementation=%q version=%q", b.Release.Backend.Implementation, b.Release.Backend.Version)
	}
	if b.Release.NativeRuntime.SchemaVersion != ExpectedNativeRuntimeSchemaVersion {
		return fmt.Errorf("native runtime schema drift: expected %d, got %d", ExpectedNativeRuntimeSchemaVersion, b.Release.NativeRuntime.SchemaVersion)
	}
	if len(b.Foundations.Models.FieldNames) != 40 {
		return fmt.Errorf("GO03 model contract drift: expected 40 dataclass models, got %d", len(b.Foundations.Models.FieldNames))
	}
	if len(b.Foundations.Validation.Cases) != 23 {
		return fmt.Errorf("GO03 validation contract drift: expected 23 cases, got %d", len(b.Foundations.Validation.Cases))
	}
	if b.Foundations.Logging.LoggerName != "chrootctl" || b.Foundations.Logging.LoggerLevel != "DEBUG" || b.Foundations.Logging.Propagate {
		return errors.New("GO03 logging contract drift")
	}
	if b.Release.NativeRuntime.Kind != "go-native" {
		return fmt.Errorf("GO12 runtime contract must describe go-native runtime, got %q", b.Release.NativeRuntime.Kind)
	}
	if b.Release.NativeRuntime.Platform != "android" || b.Release.NativeRuntime.ABI != "arm64-v8a" || b.Release.NativeRuntime.Entrypoint != "chrootctl" {
		return errors.New("native runtime platform/ABI/entrypoint baseline drift")
	}
	if b.Bridge.ArbitraryShell {
		return errors.New("bridge contract unexpectedly permits arbitrary shell")
	}

	commands := make(map[string]struct{}, len(b.CLI.CommandNodes))
	for _, node := range b.CLI.CommandNodes {
		if node.Command == "" {
			return errors.New("CLI contract contains empty command")
		}
		if _, exists := commands[node.Command]; exists {
			return fmt.Errorf("duplicate CLI command %q", node.Command)
		}
		commands[node.Command] = struct{}{}
	}

	operations := make(map[string]struct{}, len(b.Bridge.Operations))
	modeCounts := map[string]int{"query": 0, "preview": 0, "operation": 0}
	lockScopes := map[string]struct{}{"none": {}, "target": {}, "global": {}}
	for _, operation := range b.Bridge.Operations {
		if _, exists := operations[operation.Name]; exists {
			return fmt.Errorf("duplicate bridge operation %q", operation.Name)
		}
		operations[operation.Name] = struct{}{}
		if _, ok := modeCounts[operation.Mode]; !ok {
			return fmt.Errorf("unsupported bridge operation mode %q for %s", operation.Mode, operation.Name)
		}
		modeCounts[operation.Mode]++
		if _, ok := lockScopes[operation.LockScope]; !ok {
			return fmt.Errorf("unsupported lock scope %q for %s", operation.LockScope, operation.Name)
		}
		if err := uniqueStrings(operation.PayloadFields); err != nil {
			return fmt.Errorf("payload fields for %s: %w", operation.Name, err)
		}
	}
	if modeCounts["query"] != 36 || modeCounts["preview"] != 16 || modeCounts["operation"] != 34 {
		return fmt.Errorf("bridge mode distribution drift: %#v", modeCounts)
	}
	return nil
}

func uniqueStrings(values []string) error {
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		if _, ok := seen[value]; ok {
			return fmt.Errorf("duplicate value %q", value)
		}
		seen[value] = struct{}{}
	}
	return nil
}
