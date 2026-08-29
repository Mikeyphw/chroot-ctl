package bridge

import (
	"bytes"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"chrootctl/internal/redaction"
)

const (
	ProtocolVersion = 1
	MaxRequestBytes = 1024 * 1024
	MaxJSONDepth    = 24
	MaxStringLength = 16 * 1024
	MaxArrayLength  = 2048
	MaxObjectKeys   = 512
)

var requestIDRE = regexp.MustCompile(`^[A-Za-z0-9._:-]{1,128}$`)
var operationRE = regexp.MustCompile(`^[a-z][a-z0-9_.-]{1,80}$`)
var topLevelKeys = map[string]bool{"protocolVersion": true, "requestId": true, "operation": true, "payload": true}

// ProtocolError is deliberately stable because Android treats these codes as API.
type ProtocolError struct {
	ErrorCode string         `json:"-"`
	Message   string         `json:"-"`
	Details   map[string]any `json:"-"`
}

func (e ProtocolError) Error() string { return e.Message }
func (e ProtocolError) Code() string  { return e.ErrorCode }
func protocolError(code, message string, details map[string]any) error {
	return ProtocolError{ErrorCode: code, Message: message, Details: details}
}

type Request struct {
	ProtocolVersion int            `json:"protocolVersion"`
	RequestID       string         `json:"requestId"`
	Operation       string         `json:"operation"`
	Payload         map[string]any `json:"payload"`
}

func ParseRequest(raw []byte) (Request, error) {
	if len(raw) > MaxRequestBytes {
		return Request{}, protocolError("REQUEST_TOO_LARGE", fmt.Sprintf("Bridge request must not exceed %d bytes", MaxRequestBytes), map[string]any{"maxBytes": MaxRequestBytes})
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var value any
	if err := dec.Decode(&value); err != nil {
		return Request{}, protocolError("INVALID_JSON", "Request is not valid JSON: "+jsonMessage(err), nil)
	}
	if dec.More() {
		return Request{}, protocolError("INVALID_JSON", "Request is not valid JSON", nil)
	}
	obj, ok := value.(map[string]any)
	if !ok {
		return Request{}, protocolError("INVALID_REQUEST", "Request must be a JSON object", nil)
	}
	if err := validateJSONShape(obj, "request", 0); err != nil {
		return Request{}, err
	}
	unknown := []string{}
	for key := range obj {
		if !topLevelKeys[key] {
			unknown = append(unknown, key)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return Request{}, protocolError("UNKNOWN_REQUEST_FIELD", "Request contains unknown top-level field(s)", map[string]any{"fields": unknown})
	}
	version, ok := asInt(obj["protocolVersion"])
	if !ok || version != ProtocolVersion {
		return Request{}, protocolError("UNSUPPORTED_PROTOCOL_VERSION", fmt.Sprintf("Protocol version %v is not supported", obj["protocolVersion"]), map[string]any{"supported": []int{ProtocolVersion}})
	}
	requestID := strings.TrimSpace(asString(obj["requestId"]))
	if !requestIDRE.MatchString(requestID) {
		return Request{}, protocolError("INVALID_REQUEST_ID", "requestId must contain 1-128 safe identifier characters", nil)
	}
	operation := strings.TrimSpace(asString(obj["operation"]))
	if operation == "" {
		return Request{}, protocolError("MISSING_OPERATION", "operation is required", nil)
	}
	if !operationRE.MatchString(operation) {
		return Request{}, protocolError("INVALID_OPERATION", "operation must be a safe allowlisted identifier", nil)
	}
	payload := map[string]any{}
	if p, exists := obj["payload"]; exists && p != nil {
		var ok bool
		payload, ok = p.(map[string]any)
		if !ok {
			return Request{}, protocolError("INVALID_PAYLOAD", "payload must be a JSON object", nil)
		}
	}
	return Request{ProtocolVersion: version, RequestID: requestID, Operation: operation, Payload: payload}, nil
}

func jsonMessage(err error) string {
	s := err.Error()
	if x := strings.Index(s, "invalid character"); x >= 0 {
		return s[x:]
	}
	return s
}
func asInt(v any) (int, bool) {
	switch x := v.(type) {
	case json.Number:
		i, e := x.Int64()
		return int(i), e == nil
	case float64:
		return int(x), x == float64(int(x))
	case int:
		return x, true
	}
	return 0, false
}
func asString(v any) string {
	if v == nil {
		return ""
	}
	if s, ok := v.(string); ok {
		return s
	}
	return fmt.Sprint(v)
}

func validateJSONShape(v any, field string, depth int) error {
	if depth > MaxJSONDepth {
		return protocolError("REQUEST_TOO_DEEP", field+" exceeds maximum JSON nesting depth", nil)
	}
	switch x := v.(type) {
	case nil, bool, json.Number, float64, int, int64:
		return nil
	case string:
		if len([]rune(x)) > MaxStringLength {
			return protocolError("REQUEST_STRING_TOO_LONG", field+" exceeds maximum string length", nil)
		}
		return nil
	case map[string]any:
		if len(x) > MaxObjectKeys {
			return protocolError("REQUEST_OBJECT_TOO_LARGE", field+" has too many keys", nil)
		}
		for k, item := range x {
			if len(k) > 256 {
				return protocolError("REQUEST_KEY_TOO_LONG", field+" contains an overlong key", nil)
			}
			if err := validateJSONShape(item, field+"."+k, depth+1); err != nil {
				return err
			}
		}
		return nil
	case []any:
		if len(x) > MaxArrayLength {
			return protocolError("REQUEST_ARRAY_TOO_LARGE", field+" has too many array items", nil)
		}
		for i, item := range x {
			if err := validateJSONShape(item, fmt.Sprintf("%s[%d]", field, i), depth+1); err != nil {
				return err
			}
		}
		return nil
	default:
		return protocolError("INVALID_JSON_VALUE", field+" contains unsupported JSON value type", nil)
	}
}

type ErrorPayload struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Details any    `json:"details"`
}
type Response struct {
	ProtocolVersion int           `json:"protocolVersion"`
	RequestID       string        `json:"requestId"`
	OK              bool          `json:"ok"`
	Data            any           `json:"data"`
	Error           *ErrorPayload `json:"error"`
	Warnings        []string      `json:"warnings"`
	NextSteps       []string      `json:"nextSteps"`
}

func Success(id string, data any) Response {
	return Response{ProtocolVersion: ProtocolVersion, RequestID: id, OK: true, Data: data, Warnings: []string{}, NextSteps: []string{}}
}
func Failure(id string, err error) Response {
	p := &ErrorPayload{Code: "INTERNAL_ERROR", Message: safeError(err), Details: map[string]any{}}
	var pe ProtocolError
	if ok := asProtocolError(err, &pe); ok {
		p.Code = pe.ErrorCode
		p.Message = safeMessage(pe.Message)
		if pe.Details != nil {
			p.Details = redaction.Value(pe.Details)
		}
	}
	return Response{ProtocolVersion: ProtocolVersion, RequestID: id, OK: false, Data: nil, Error: p, Warnings: []string{}, NextSteps: []string{}}
}
func asProtocolError(err error, target *ProtocolError) bool {
	if err == nil {
		return false
	}
	if v, ok := err.(ProtocolError); ok {
		*target = v
		return true
	}
	if p, ok := err.(*ProtocolError); ok {
		*target = *p
		return true
	}
	return false
}
func safeError(err error) string {
	if err == nil {
		return "Bridge request failed"
	}
	return safeMessage(err.Error())
}
func safeMessage(s string) string {
	s = fmt.Sprint(redaction.Value(s))
	s = strings.Join(strings.Fields(s), " ")
	if s == "" {
		s = "Bridge request failed"
	}
	r := []rune(s)
	if len(r) > 512 {
		s = string(r[:512])
	}
	return s
}

func ExtractRequestIDSafely(raw []byte) string {
	if len(raw) > MaxRequestBytes {
		raw = raw[:MaxRequestBytes]
	}
	var m map[string]any
	if json.Unmarshal(raw, &m) != nil {
		return ""
	}
	id := strings.TrimSpace(asString(m["requestId"]))
	if requestIDRE.MatchString(id) {
		return id
	}
	return ""
}
func EventPayload(eventType, operationID, requestID string, payload map[string]any) map[string]any {
	return map[string]any{"protocolVersion": ProtocolVersion, "type": eventType, "operationId": operationID, "requestId": requestID, "timestamp": float64(time.Now().UnixNano()) / 1e9, "payload": payload}
}
