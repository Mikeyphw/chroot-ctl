// Package skybindfeature is the explicit root-only Skybind API-02 consumer.
// It invokes Skybind's own daemon-backed CLI; it is NOT a second mount engine
// or an Android-app credential / root elevation channel.
package skybindfeature

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
)

const SkybindBinary = "/data/adb/modules/skybind/system/bin/skybind"
const MaxRequest = 65536
const MaxResponse = 262144

var ErrDenied = errors.New("Skybind feature denied")

var idPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{1,80}$`)

// This catalog is a closed compatibility contract. Skybind itself performs
// operation implementation/version discovery and all authorization/proof
// checks. No raw process, shell, remote, PID or config access is exposed here.
var allowed = map[string]bool{
	"mount.list": true, "mount.status": true, "mount.health": true,
	"mount.start.preview": true, "mount.start": true, "mount.stop": true,
	"mount.restart": true, "mount.reconcile": true,
	"namespace.inspect": true, "namespace.preview": true,
	"namespace.apply": true, "namespace.rollback.preview": true,
	"namespace.rollback": true, "namespace.reconcile": true,
	"operation.status": true, "operation.events": true,
}

type request struct {
	APIVersion int             `json:"api_version"`
	RequestID  string          `json:"request_id"`
	Arguments  json.RawMessage `json:"arguments"`
}
type response struct {
	SchemaVersion int             `json:"schema_version"`
	RequestID     string          `json:"request_id"`
	OK            bool            `json:"ok"`
	Result        json.RawMessage `json:"result,omitempty"`
	Error         json.RawMessage `json:"error,omitempty"`
}

func decodeExact(data []byte, value any) error {
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err := d.Decode(value); err != nil {
		return errors.New("invalid Skybind envelope")
	}
	if d.Decode(new(any)) != io.EOF {
		return errors.New("extra Skybind envelope data")
	}
	return nil
}

// rejectAmbiguousJSON rejects duplicate object keys at every nesting level.
// Producer API-02 enforces the same rule; checking before execution avoids
// forwarding an ambiguous proof, request_id, or mutation argument.
func rejectAmbiguousJSON(data []byte) error {
	dec := json.NewDecoder(bytes.NewReader(data))
	var read func(int) error
	read = func(depth int) error {
		if depth > 40 {
			return errors.New("Skybind JSON nesting limit exceeded")
		}
		token, err := dec.Token()
		if err != nil {
			return errors.New("invalid Skybind JSON")
		}
		switch token {
		case json.Delim('{'):
			seen := make(map[string]bool)
			for dec.More() {
				keyToken, err := dec.Token()
				if err != nil {
					return errors.New("invalid Skybind JSON object")
				}
				key, ok := keyToken.(string)
				if !ok || seen[key] {
					return errors.New("ambiguous Skybind JSON object")
				}
				seen[key] = true
				if err := read(depth + 1); err != nil {
					return err
				}
			}
			end, err := dec.Token()
			if err != nil || end != json.Delim('}') {
				return errors.New("invalid Skybind JSON object")
			}
		case json.Delim('['):
			for dec.More() {
				if err := read(depth + 1); err != nil {
					return err
				}
			}
			end, err := dec.Token()
			if err != nil || end != json.Delim(']') {
				return errors.New("invalid Skybind JSON array")
			}
		case json.Delim('}'), json.Delim(']'):
			return errors.New("invalid Skybind JSON delimiter")
		}
		return nil
	}
	if err := read(0); err != nil {
		return err
	}
	if _, err := dec.Token(); err != io.EOF {
		return errors.New("trailing Skybind JSON")
	}
	return nil
}

// A denial may represent an ambiguous mount mutation. Only preserve it as a
// machine-readable receipt when the producer supplied a complete fault object.
func validDenialFault(raw json.RawMessage) bool {
	if len(raw) == 0 || string(bytes.TrimSpace(raw)) == "null" {
		return false
	}
	var fault struct {
		Code        string `json:"code"`
		Category    string `json:"category"`
		Stage       string `json:"stage"`
		Message     string `json:"message"`
		Retryable   *bool  `json:"retryable"`
		FieldErrors []struct {
			Index int    `json:"index"`
			Field string `json:"field"`
			Code  string `json:"code"`
		} `json:"field_errors,omitempty"`
	}
	if err := decodeExact(raw, &fault); err != nil {
		return false
	}
	return fault.Code != "" && fault.Category != "" && fault.Stage != "" && fault.Message != "" && fault.Retryable != nil
}

func validateRequest(data []byte) (string, error) {
	if len(data) == 0 || len(data) > MaxRequest {
		return "", errors.New("Skybind request size invalid")
	}
	if err := rejectAmbiguousJSON(data); err != nil {
		return "", err
	}
	var req request
	if err := decodeExact(data, &req); err != nil {
		return "", err
	}
	if req.APIVersion != 1 || !idPattern.MatchString(req.RequestID) || len(req.Arguments) == 0 || !json.Valid(req.Arguments) || strings.TrimSpace(string(req.Arguments))[0] != '{' {
		return "", errors.New("invalid Skybind feature request")
	}
	return req.RequestID, nil
}

// Runner makes the entire call contract testable without executing root code.
// The production runner always uses one fixed module-owned executable path.
type Runner func(ctx context.Context, args []string, stdin []byte) ([]byte, error)

func Call(ctx context.Context, args []string, input io.Reader, run Runner) ([]byte, error) {
	if len(args) == 0 {
		return nil, errors.New("missing feature action")
	}
	expectedID := "feature-capabilities-v1"
	var req []byte
	if len(args) == 1 && args[0] == "capabilities" {
		// Capability discovery takes no caller-selected operation, token or args.
	} else if len(args) == 3 && args[0] == "call" && args[2] == "--stdin" && allowed[args[1]] {
		var err error
		req, err = io.ReadAll(io.LimitReader(input, MaxRequest+1))
		if err != nil {
			return nil, errors.New("feature input unavailable")
		}
		expectedID, err = validateRequest(req)
		if err != nil {
			return nil, err
		}
	} else {
		return nil, errors.New("unsupported Skybind feature command")
	}
	out, execErr := run(ctx, args, req)
	if len(out) == 0 || len(out) > MaxResponse {
		return nil, errors.New("invalid Skybind feature response size")
	}
	if err := rejectAmbiguousJSON(out); err != nil {
		return nil, err
	}
	var responseKeys map[string]json.RawMessage
	if err := json.Unmarshal(out, &responseKeys); err != nil {
		return nil, errors.New("invalid Skybind feature response")
	}
	for _, key := range []string{"schema_version", "request_id", "ok"} {
		if _, present := responseKeys[key]; !present {
			return nil, errors.New("incomplete Skybind feature response")
		}
	}
	var resp response
	if err := decodeExact(out, &resp); err != nil {
		return nil, err
	}
	if resp.SchemaVersion != 1 || resp.RequestID != expectedID {
		return nil, errors.New("Skybind feature response identity mismatch")
	}
	if !resp.OK {
		if !validDenialFault(resp.Error) || len(resp.Result) != 0 {
			return nil, errors.New("incomplete Skybind denial receipt")
		}
		// Preserve the complete, validated daemon receipt for callers that
		// need to reconcile a failed/lost mutation by request ID.
		return append(bytes.TrimSpace(out), '\n'), ErrDenied
	}
	if execErr != nil {
		return nil, errors.New("Skybind process unavailable")
	}
	if len(resp.Result) == 0 || !json.Valid(resp.Result) || len(resp.Error) != 0 {
		return nil, errors.New("Skybind feature result invalid")
	}
	return append(bytes.TrimSpace(out), '\n'), nil
}

func trustedBinary(path string) error {
	// Check each module path component for symlinks, root owner and writable
	// ancestors. Treat missing/unsafe Skybind installation as an unavailable API.
	for p := path; p != "/"; p = filepath.Dir(p) {
		st, err := os.Lstat(p)
		if err != nil || st.Mode()&os.ModeSymlink != 0 || st.Mode().Perm()&0o022 != 0 {
			return errors.New("untrusted Skybind installation")
		}
		raw, ok := st.Sys().(*syscall.Stat_t)
		if !ok || raw.Uid != 0 {
			return errors.New("untrusted Skybind owner")
		}
		if p == path {
			if !st.Mode().IsRegular() || st.Mode().Perm()&0o100 == 0 {
				return errors.New("Skybind binary unavailable")
			}
		} else if !st.IsDir() {
			return errors.New("invalid Skybind module directory")
		}
	}
	return nil
}

func RunInstalled(ctx context.Context, args []string, stdin []byte) ([]byte, error) {
	if os.Geteuid() != 0 {
		return nil, errors.New("root required")
	}
	if err := trustedBinary(SkybindBinary); err != nil {
		return nil, err
	}
	cctx, cancel := context.WithTimeout(ctx, 120*time.Second)
	defer cancel()
	cmd := exec.CommandContext(cctx, SkybindBinary, append([]string{"feature"}, args...)...)
	cmd.Stdin = bytes.NewReader(stdin)
	// Never echo root daemon errors, arbitrary stderr or credentials.
	cmd.Stderr = io.Discard
	var buf boundedBuffer
	cmd.Stdout = &buf
	err := cmd.Run()
	return buf.Bytes(), err
}

type boundedBuffer struct{ bytes.Buffer }

func (b *boundedBuffer) Write(p []byte) (int, error) {
	if b.Len()+len(p) > MaxResponse {
		return 0, fmt.Errorf("Skybind response exceeds limit")
	}
	return b.Buffer.Write(p)
}
