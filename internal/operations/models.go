package operations

import (
	"encoding/json"
	"fmt"
	"strconv"
	"time"
)

const SchemaVersion = 2

var terminalStates = map[string]bool{"cancelled": true, "succeeded": true, "failed": true, "interrupted": true, "blocked": true}
var activeStates = map[string]bool{"queued": true, "running": true, "cancelling": true}

type Record struct {
	SchemaVersion     int              `json:"schemaVersion"`
	OperationID       string           `json:"operationId"`
	Kind              string           `json:"kind"`
	Title             string           `json:"title"`
	State             string           `json:"state"`
	TargetName        *string          `json:"targetName"`
	ParentOperationID *string          `json:"parentOperationId"`
	CreatedAt         float64          `json:"createdAt"`
	StartedAt         *float64         `json:"startedAt"`
	FinishedAt        *float64         `json:"finishedAt"`
	Phase             *string          `json:"phase"`
	ProgressPercent   *int             `json:"progressPercent"`
	ProgressText      string           `json:"progressText"`
	PID               *int             `json:"pid"`
	ProcessGroupID    *int             `json:"processGroupId"`
	ProcessStartTime  *int64           `json:"processStartTime"`
	ProcessBootID     *string          `json:"processBootId"`
	ChildProcesses    []map[string]any `json:"childProcesses"`
	Request           map[string]any   `json:"request"`
	ResultPayload     any              `json:"resultPayload"`
	Error             *string          `json:"error"`
	ErrorCode         *string          `json:"errorCode"`
	Warnings          []string         `json:"warnings"`
	NextSteps         []string         `json:"nextSteps"`
	Retry             map[string]any   `json:"retry"`
	LogPath           *string          `json:"logPath"`
	LockKey           *string          `json:"lockKey"`
	LockScope         string           `json:"lockScope"`
	ProgressDetail    map[string]any   `json:"progressDetail"`
	ProgressEvents    []map[string]any `json:"progressEvents"`
	EventSequence     int              `json:"eventSequence"`
	Corrupt           bool             `json:"corrupt"`
	RepairNeeded      bool             `json:"repairNeeded"`
	RepairReason      *string          `json:"repairReason"`
	Complete          bool             `json:"complete"`
}

func NewRecord(id, kind, title string) Record {
	return Record{SchemaVersion: SchemaVersion, OperationID: id, Kind: kind, Title: title, State: "queued", CreatedAt: float64(time.Now().UnixNano()) / 1e9, ProgressText: "Queued", ChildProcesses: []map[string]any{}, Request: map[string]any{}, Warnings: []string{}, NextSteps: []string{}, ProgressDetail: map[string]any{}, ProgressEvents: []map[string]any{}}
}
func (r *Record) RefreshComplete() { r.Complete = terminalStates[r.State] }
func (r Record) IsComplete() bool  { return terminalStates[r.State] }
func IsActive(state string) bool   { return activeStates[state] }

func DecodeRecord(data []byte) (Record, error) {
	var raw map[string]any
	if err := json.Unmarshal(data, &raw); err != nil {
		return Record{}, err
	}
	return RecordFromMap(raw), nil
}
func RecordFromMap(v map[string]any) Record {
	r := NewRecord(text(v, "operationId", "operation_id"), textDefault(v, "kind", "unknown"), textDefault(v, "title", textDefault(v, "kind", "Operation")))
	r.SchemaVersion = intDefault(v, 1, "schemaVersion", "schema_version")
	r.State = textDefault(v, "state", "queued")
	r.TargetName = optText(v, "targetName", "target_name")
	r.ParentOperationID = optText(v, "parentOperationId", "parent_operation_id")
	r.CreatedAt = floatDefault(v, float64(time.Now().UnixNano())/1e9, "createdAt", "created_at")
	r.StartedAt = optFloat(v, "startedAt", "started_at")
	r.FinishedAt = optFloat(v, "finishedAt", "finished_at")
	r.Phase = optText(v, "phase")
	r.ProgressPercent = optInt(v, "progressPercent", "progress_percent")
	r.ProgressText = textDefaultAny(v, "Queued", "progressText", "progress_text")
	r.PID = optInt(v, "pid")
	r.ProcessGroupID = optInt(v, "processGroupId", "process_group_id")
	r.ProcessStartTime = optInt64(v, "processStartTime", "process_start_time")
	r.ProcessBootID = optText(v, "processBootId", "process_boot_id")
	r.ChildProcesses = mapSlice(v, "childProcesses", "child_processes")
	r.Request = mapValue(v, "request")
	r.ResultPayload = first(v, "resultPayload", "result_payload")
	r.Error = optText(v, "error")
	r.ErrorCode = optText(v, "errorCode", "error_code")
	r.Warnings = stringSlice(first(v, "warnings"))
	r.NextSteps = stringSlice(first(v, "nextSteps", "next_steps"))
	r.Retry = optionalMap(first(v, "retry"))
	r.LogPath = optText(v, "logPath", "log_path")
	r.LockKey = optText(v, "lockKey", "lock_key")
	r.LockScope = textDefaultAny(v, "", "lockScope", "lock_scope")
	r.ProgressDetail = mapValueKeys(v, "progressDetail", "progress_detail")
	r.ProgressEvents = mapSlice(v, "progressEvents", "progress_events")
	r.EventSequence = intDefault(v, 0, "eventSequence", "event_sequence")
	r.Corrupt = boolDefault(v, false, "corrupt")
	r.RepairNeeded = boolDefault(v, false, "repairNeeded", "repair_needed")
	r.RepairReason = optText(v, "repairReason", "repair_reason")
	r.RefreshComplete()
	return r
}
func CorruptPlaceholder(id, reason string) Record {
	r := NewRecord(id, "journal.corrupt", "Corrupt operation record")
	r.State = "blocked"
	r.ProgressText = "Repair required"
	c := "CORRUPT_OPERATION_RECORD"
	r.ErrorCode = &c
	r.Error = &reason
	r.NextSteps = []string{"Inspect or remove the corrupt operation record before retrying the action."}
	r.Corrupt = true
	r.RepairNeeded = true
	r.RepairReason = &reason
	r.RefreshComplete()
	return r
}
func first(m map[string]any, keys ...string) any {
	for _, k := range keys {
		if x, ok := m[k]; ok {
			return x
		}
	}
	return nil
}
func text(m map[string]any, keys ...string) string {
	x := first(m, keys...)
	if x == nil {
		return ""
	}
	return fmt.Sprint(x)
}
func textDefault(m map[string]any, key, def string) string {
	if x, ok := m[key]; ok && x != nil && fmt.Sprint(x) != "" {
		return fmt.Sprint(x)
	}
	return def
}
func textDefaultAny(m map[string]any, def string, keys ...string) string {
	if x := first(m, keys...); x != nil {
		return fmt.Sprint(x)
	}
	return def
}
func optText(m map[string]any, keys ...string) *string {
	x := first(m, keys...)
	if x == nil {
		return nil
	}
	s := fmt.Sprint(x)
	return &s
}
func number(v any) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, true
	case int:
		return float64(x), true
	case int64:
		return float64(x), true
	case json.Number:
		f, e := x.Float64()
		return f, e == nil
	case string:
		f, e := strconv.ParseFloat(x, 64)
		return f, e == nil
	}
	return 0, false
}
func optFloat(m map[string]any, keys ...string) *float64 {
	if n, ok := number(first(m, keys...)); ok {
		return &n
	}
	return nil
}
func floatDefault(m map[string]any, d float64, keys ...string) float64 {
	if n, ok := number(first(m, keys...)); ok {
		return n
	}
	return d
}
func optInt(m map[string]any, keys ...string) *int {
	if n, ok := number(first(m, keys...)); ok {
		i := int(n)
		return &i
	}
	return nil
}
func optInt64(m map[string]any, keys ...string) *int64 {
	if n, ok := number(first(m, keys...)); ok {
		i := int64(n)
		return &i
	}
	return nil
}
func intDefault(m map[string]any, d int, keys ...string) int {
	if p := optInt(m, keys...); p != nil {
		return *p
	}
	return d
}
func boolDefault(m map[string]any, d bool, keys ...string) bool {
	if x := first(m, keys...); x != nil {
		if b, ok := x.(bool); ok {
			return b
		}
	}
	return d
}
func stringSlice(v any) []string {
	out := []string{}
	switch x := v.(type) {
	case []any:
		for _, i := range x {
			out = append(out, fmt.Sprint(i))
		}
	case []string:
		out = append(out, x...)
	}
	return out
}
func optionalMap(v any) map[string]any {
	if v == nil {
		return nil
	}
	if x, ok := v.(map[string]any); ok {
		return x
	}
	return nil
}
func mapValue(m map[string]any, key string) map[string]any { return mapValueKeys(m, key) }
func mapValueKeys(m map[string]any, keys ...string) map[string]any {
	if x, ok := first(m, keys...).(map[string]any); ok {
		return x
	}
	return map[string]any{}
}
func mapSlice(m map[string]any, keys ...string) []map[string]any {
	out := []map[string]any{}
	if a, ok := first(m, keys...).([]any); ok {
		for _, v := range a {
			if x, ok := v.(map[string]any); ok {
				out = append(out, x)
			}
		}
	}
	if a, ok := first(m, keys...).([]map[string]any); ok {
		return append(out, a...)
	}
	return out
}
