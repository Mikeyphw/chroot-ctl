package bridge

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"chrootctl/internal/config"
	"chrootctl/internal/services"
	"chrootctl/internal/version"
)

type AppOptions struct {
	ConfigPath      string
	DryRun, Verbose bool
	Command         string
	RequestFile     string
	RequestJSON     string
	OperationID     string
	Events          string
}

func ParseAppArgs(args []string) (AppOptions, error) {
	o := AppOptions{RequestFile: "-", Events: "ndjson"}
	i := 0
	for i < len(args) {
		a := args[i]
		if a == "--config" {
			if i+1 >= len(args) {
				return o, fmt.Errorf("--config requires a value")
			}
			o.ConfigPath = args[i+1]
			i += 2
			continue
		}
		if a == "--dry-run" {
			o.DryRun = true
			i++
			continue
		}
		if a == "--verbose" {
			o.Verbose = true
			i++
			continue
		}
		break
	}
	if i >= len(args) {
		return o, fmt.Errorf("app command is required")
	}
	o.Command = args[i]
	i++
	switch o.Command {
	case "capabilities", "state":
		if i != len(args) {
			return o, fmt.Errorf("unexpected app argument: %s", args[i])
		}
	case "query", "preview", "run":
		for i < len(args) {
			switch args[i] {
			case "--request-file":
				if i+1 >= len(args) {
					return o, fmt.Errorf("--request-file requires a value")
				}
				if o.RequestJSON != "" {
					return o, fmt.Errorf("--request-file and --request-json are mutually exclusive")
				}
				o.RequestFile = args[i+1]
				i += 2
			case "--request-json":
				if i+1 >= len(args) {
					return o, fmt.Errorf("--request-json requires a value")
				}
				if o.RequestFile != "-" {
					return o, fmt.Errorf("--request-file and --request-json are mutually exclusive")
				}
				o.RequestJSON = args[i+1]
				i += 2
			case "--events":
				if o.Command != "run" || i+1 >= len(args) {
					return o, fmt.Errorf("invalid --events usage")
				}
				o.Events = args[i+1]
				i += 2
			default:
				return o, fmt.Errorf("unexpected app argument: %s", args[i])
			}
		}
		if o.Command == "run" && o.Events != "ndjson" {
			return o, fmt.Errorf("--events must be ndjson")
		}
	case "operation", "cancel", "reconcile":
		if i >= len(args) {
			return o, fmt.Errorf("%s requires operation_id", o.Command)
		}
		o.OperationID = args[i]
		i++
		if i != len(args) {
			return o, fmt.Errorf("unexpected app argument: %s", args[i])
		}
	default:
		return o, fmt.Errorf("unsupported app command: %s", o.Command)
	}
	return o, nil
}

func RunApp(ctx context.Context, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	o, e := ParseAppArgs(args)
	if e != nil {
		fmt.Fprintln(stderr, "chrootctl app:", e)
		return 2
	}
	if o.Command == "capabilities" {
		cfg := config.Default(config.DetectRuntime())
		root := filepath.Join(filepath.Dir(cfg.DatabasePath), "operations")
		payload := Success("capabilities", map[string]any{"protocolVersion": ProtocolVersion, "backendVersion": version.Version, "operations": Capabilities(), "operationRoot": root, "transport": []string{"json", "ndjson"}, "arbitraryShell": false, "runtimeHealth": map[string]any{"status": "ready"}})
		writeJSON(stdout, payload)
		return 0
	}
	var parsed *Request
	var raw []byte
	if o.Command == "query" || o.Command == "preview" || o.Command == "run" {
		if o.RequestJSON != "" {
			raw, e = readInlineRequest(o.RequestJSON)
		} else {
			raw, e = readRequest(stdin, o.RequestFile)
		}
		if e != nil {
			id := ExtractRequestIDSafely(raw)
			if id == "" {
				id = "unknown"
			}
			writeJSON(stdout, Failure(id, e))
			return 2
		}
		r, pe := ParseRequest(raw)
		if pe != nil {
			id := ExtractRequestIDSafely(raw)
			if id == "" {
				id = "unknown"
			}
			writeJSON(stdout, Failure(id, pe))
			return 2
		}
		parsed = &r
	}
	s, e := services.New(o.ConfigPath, o.DryRun, o.Verbose)
	if e != nil {
		id := "unknown"
		if parsed != nil {
			id = parsed.RequestID
		}
		writeJSON(stdout, Failure(id, e))
		return 2
	}
	defer s.Close()
	d, e := NewServicesDispatcher(s)
	if e != nil {
		writeJSON(stdout, Failure("unknown", e))
		return 2
	}
	switch o.Command {
	case "state":
		r := d.State(ctx, "state")
		writeJSON(stdout, r)
		if r.OK {
			return 0
		}
		return 2
	case "query":
		r := d.Query(ctx, *parsed)
		writeJSON(stdout, r)
		if r.OK {
			return 0
		}
		return 2
	case "preview":
		r := d.Preview(ctx, *parsed)
		writeJSON(stdout, r)
		if r.OK {
			return 0
		}
		return 2
	case "run":
		return d.Run(ctx, *parsed, func(v map[string]any) error { return writeJSON(stdout, v) })
	case "operation":
		r := d.Operation(o.OperationID)
		writeJSON(stdout, r)
		if r.OK {
			return 0
		}
		return 2
	case "cancel":
		r := d.Cancel(o.OperationID)
		writeJSON(stdout, r)
		if r.OK {
			return 0
		}
		return 2
	case "reconcile":
		r := d.Reconcile(ctx, o.OperationID)
		writeJSON(stdout, r)
		if r.OK {
			return 0
		}
		return 2
	}
	return 2
}
func readInlineRequest(value string) ([]byte, error) {
	b := []byte(value)
	if len(b) > MaxRequestBytes {
		return b, protocolError("REQUEST_TOO_LARGE", fmt.Sprintf("Bridge request must not exceed %d bytes", MaxRequestBytes), nil)
	}
	return b, nil
}

func readRequest(stdin io.Reader, path string) ([]byte, error) {
	if path == "-" {
		lr := io.LimitReader(stdin, MaxRequestBytes+1)
		b, e := io.ReadAll(lr)
		if e != nil {
			return b, e
		}
		if len(b) > MaxRequestBytes {
			return b, protocolError("REQUEST_TOO_LARGE", fmt.Sprintf("Bridge request must not exceed %d bytes", MaxRequestBytes), nil)
		}
		return b, nil
	}
	st, e := os.Stat(path)
	if e != nil {
		return nil, e
	}
	if st.Size() > MaxRequestBytes {
		return nil, protocolError("REQUEST_TOO_LARGE", fmt.Sprintf("Bridge request must not exceed %d bytes", MaxRequestBytes), nil)
	}
	return os.ReadFile(path)
}
func writeJSON(w io.Writer, v any) error {
	b, e := json.Marshal(v)
	if e != nil {
		return e
	}
	bw := bufio.NewWriter(w)
	if _, e = bw.Write(b); e != nil {
		return e
	}
	if e = bw.WriteByte('\n'); e != nil {
		return e
	}
	return bw.Flush()
}
func AppHelp() string {
	return strings.TrimSpace(`chrootctl app [--config PATH] [--dry-run] [--verbose] COMMAND

Commands:
  capabilities
  state
  query (--request-file FILE | --request-json JSON)
  preview (--request-file FILE | --request-json JSON)
  run (--request-file FILE | --request-json JSON) --events ndjson
  operation OPERATION_ID
  cancel OPERATION_ID
  reconcile OPERATION_ID`) + "\n"
}
