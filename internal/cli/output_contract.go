package cli

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"reflect"
	"sort"
	"strings"

	"chrootctl/internal/apperrors"
	"chrootctl/internal/redaction"
)

const responseSchemaVersion = 1

type responseEnvelope struct {
	SchemaVersion int                      `json:"schema_version"`
	OK            bool                     `json:"ok"`
	Command       string                   `json:"command"`
	Data          any                      `json:"data,omitempty"`
	Error         *apperrors.ErrorResponse `json:"error,omitempty"`
	Warnings      []string                 `json:"warnings"`
	NextSteps     []string                 `json:"next_steps"`
	Partial       bool                     `json:"partial"`
}

type PartialResultError struct {
	Err      error
	Partial  any
	ExitCode int
}

func (e *PartialResultError) Error() string {
	if e == nil || e.Err == nil {
		return "partial failure"
	}
	return e.Err.Error()
}
func (e *PartialResultError) Unwrap() error {
	if e == nil {
		return nil
	}
	return e.Err
}

func emitJSONEnvelope(w io.Writer, command string, ok bool, data any, err error, partial bool) error {
	env := responseEnvelope{SchemaVersion: responseSchemaVersion, OK: ok, Command: command, Data: data, Warnings: []string{}, NextSteps: extractNextSteps(data), Partial: partial}
	if err != nil {
		resp := appErrorResponse(err)
		env.Error = &resp
	}
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	return enc.Encode(env)
}

func appErrorResponse(err error) apperrors.ErrorResponse {
	var response apperrors.ErrorResponse
	var ae apperrors.AppError
	if errors.As(err, &ae) {
		response = ae.ToResponse()
	} else {
		var aep *apperrors.AppError
		if errors.As(err, &aep) && aep != nil {
			response = aep.ToResponse()
		} else {
			response = apperrors.AppError{Code: "command_failed", Title: "Command failed", Message: err.Error(), Details: map[string]any{}, StatusCode: 400}.ToResponse()
		}
	}
	response.Title = redaction.String(response.Title)
	response.Message = redaction.String(response.Message)
	if clean, ok := redaction.Value(response.Details).(map[string]any); ok {
		response.Details = clean
	}
	for i := range response.Hints {
		response.Hints[i] = redaction.String(response.Hints[i])
	}
	for i := range response.Actions {
		response.Actions[i].Label = redaction.String(response.Actions[i].Label)
		if response.Actions[i].Href != nil {
			clean := redaction.String(*response.Actions[i].Href)
			response.Actions[i].Href = &clean
		}
		if response.Actions[i].Command != nil {
			clean := redaction.String(*response.Actions[i].Command)
			response.Actions[i].Command = &clean
		}
	}
	return response
}

func extractNextSteps(value any) []string {
	if value == nil {
		return []string{}
	}
	raw, err := json.Marshal(value)
	if err != nil {
		return []string{}
	}
	var obj map[string]any
	if json.Unmarshal(raw, &obj) != nil {
		return []string{}
	}
	v, ok := obj["next_steps"]
	if !ok {
		return []string{}
	}
	arr, ok := v.([]any)
	if !ok {
		return []string{}
	}
	out := make([]string, 0, len(arr))
	for _, x := range arr {
		out = append(out, fmt.Sprint(x))
	}
	return out
}

func writeHuman(w io.Writer, title string, value any) error {
	if title != "" {
		if _, err := fmt.Fprintln(w, title); err != nil {
			return err
		}
	}
	return renderHumanValue(w, value, 0)
}

func renderHumanValue(w io.Writer, value any, indent int) error {
	if value == nil {
		_, err := fmt.Fprintln(w, "-")
		return err
	}
	if text, ok := value.(string); ok {
		if _, err := io.WriteString(w, text); err != nil {
			return err
		}
		if !strings.HasSuffix(text, "\n") {
			_, err := io.WriteString(w, "\n")
			return err
		}
		return nil
	}
	if display, ok := value.(interface{ DisplayMap() map[string]string }); ok {
		return writeStringMap(w, display.DisplayMap(), indent)
	}
	rv := reflect.ValueOf(value)
	for rv.IsValid() && (rv.Kind() == reflect.Pointer || rv.Kind() == reflect.Interface) {
		if rv.IsNil() {
			_, err := fmt.Fprintln(w, "-")
			return err
		}
		rv = rv.Elem()
	}
	if !rv.IsValid() {
		_, err := fmt.Fprintln(w, "-")
		return err
	}
	switch rv.Kind() {
	case reflect.Slice, reflect.Array:
		for i := 0; i < rv.Len(); i++ {
			if i > 0 {
				if _, err := fmt.Fprintln(w); err != nil {
					return err
				}
			}
			if err := renderHumanValue(w, rv.Index(i).Interface(), indent); err != nil {
				return err
			}
		}
		if rv.Len() == 0 {
			_, err := fmt.Fprintln(w, "(none)")
			return err
		}
		return nil
	case reflect.Map, reflect.Struct:
		raw, err := json.Marshal(value)
		if err != nil {
			return err
		}
		var object map[string]any
		if json.Unmarshal(raw, &object) != nil {
			_, err = fmt.Fprintln(w, fmt.Sprint(value))
			return err
		}
		return writeAnyMap(w, object, indent)
	default:
		_, err := fmt.Fprintln(w, fmt.Sprint(value))
		return err
	}
}

func writeStringMap(w io.Writer, values map[string]string, indent int) error {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	pad := strings.Repeat(" ", indent)
	for _, key := range keys {
		if _, err := fmt.Fprintf(w, "%s%s: %s\n", pad, key, values[key]); err != nil {
			return err
		}
	}
	return nil
}

func writeAnyMap(w io.Writer, values map[string]any, indent int) error {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	pad := strings.Repeat(" ", indent)
	for _, key := range keys {
		v := values[key]
		rv := reflect.ValueOf(v)
		if !rv.IsValid() {
			if _, err := fmt.Fprintf(w, "%s%s: -\n", pad, key); err != nil {
				return err
			}
			continue
		}
		switch rv.Kind() {
		case reflect.Map, reflect.Slice, reflect.Array:
			b, _ := json.Marshal(v)
			if _, err := fmt.Fprintf(w, "%s%s: %s\n", pad, key, b); err != nil {
				return err
			}
		default:
			if _, err := fmt.Fprintf(w, "%s%s: %v\n", pad, key, v); err != nil {
				return err
			}
		}
	}
	return nil
}

func requestedJSON(args []string) bool {
	for _, arg := range args {
		if arg == "--" {
			return false
		}
		if arg == "--json" || strings.HasPrefix(arg, "--json=") {
			return true
		}
	}
	return false
}
