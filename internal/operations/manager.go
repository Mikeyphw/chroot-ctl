package operations

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"syscall"
	"time"

	"chrootctl/internal/apperrors"
	"chrootctl/internal/redaction"
	sys "chrootctl/internal/system"
)

type ProgressFunc func(any) error
type RunnerFunc func(ProgressFunc, func() bool) (any, error)
type EventEmitter func(map[string]any) error

var ErrCancelled = errors.New("Cancellation requested")

type Manager struct {
	Journal *Journal
	Now     func() time.Time
}

func NewManager(root string, recover bool) (*Manager, error) {
	j, e := NewJournal(root)
	if e != nil {
		return nil, e
	}
	m := &Manager{Journal: j, Now: time.Now}
	if recover {
		_, e = m.Recover(context.Background())
	}
	return m, e
}
func randomID() string {
	b := make([]byte, 8)
	if _, e := rand.Read(b); e != nil {
		return fmt.Sprintf("%016x", time.Now().UnixNano())
	}
	return hex.EncodeToString(b)
}

type CreateOptions struct {
	Kind, Title       string
	TargetName        *string
	Request           map[string]any
	Retry             map[string]any
	LogPath           *string
	LockScope         string
	OperationID       string
	ParentOperationID *string
}

func redactedMap(v map[string]any) map[string]any {
	if v == nil {
		return map[string]any{}
	}
	x := redaction.Value(normalize(v))
	if m, ok := x.(map[string]any); ok {
		return m
	}
	return map[string]any{}
}
func (m *Manager) Create(o CreateOptions) (Record, error) {
	id := o.OperationID
	if id == "" {
		id = randomID()
	}
	if _, e := ValidateID(id); e != nil {
		return Record{}, e
	}
	key, e := LockKeyFor(o.LockScope, o.TargetName)
	if e != nil {
		return Record{}, e
	}
	r := NewRecord(id, o.Kind, o.Title)
	r.TargetName = o.TargetName
	r.ParentOperationID = o.ParentOperationID
	r.Request = redactedMap(o.Request)
	if o.Retry != nil {
		r.Retry = redactedMap(o.Retry)
	}
	r.LogPath = o.LogPath
	r.LockKey = key
	r.CreatedAt = float64(m.Now().UnixNano()) / 1e9
	_ = m.Journal.ClearCancel(id)
	if e = m.Journal.Save(&r); e != nil {
		return Record{}, e
	}
	_ = m.event(&r, "operation_queued", map[string]any{"state": r.State}, nil)
	return r, nil
}
func (m *Manager) cancelled(id string) bool { return m.Journal.CancellationRequested(id) }
func (m *Manager) setRunning(r *Record) error {
	r.State = "running"
	now := float64(m.Now().UnixNano()) / 1e9
	r.StartedAt = &now
	r.ProgressText = "Starting"
	if id := sys.CaptureProcessIdentity(os.Getpid()); id != nil {
		r.PID = &id.PID
		r.ProcessGroupID = &id.ProcessGroupID
		r.ProcessStartTime = id.StartTimeTicks
		r.ProcessBootID = id.BootID
	} else {
		pid := os.Getpid()
		pg := syscall.Getpgrp()
		r.PID = &pid
		r.ProcessGroupID = &pg
	}
	return m.Journal.Save(r)
}
func (m *Manager) RegisterProcess(r *Record, id sys.ProcessIdentity, emit EventEmitter) error {
	v := map[string]any{"pid": id.PID, "processGroupId": id.ProcessGroupID, "processStartTime": id.StartTimeTicks, "processBootId": id.BootID}
	for _, x := range r.ChildProcesses {
		if fmt.Sprint(x) == fmt.Sprint(v) {
			return nil
		}
	}
	r.ChildProcesses = append(r.ChildProcesses, v)
	if len(r.ChildProcesses) > 64 {
		r.ChildProcesses = r.ChildProcesses[len(r.ChildProcesses)-64:]
	}
	if e := m.Journal.Save(r); e != nil {
		return e
	}
	return m.event(r, "operation_process_started", v, emit)
}
func (m *Manager) Execute(ctx context.Context, r *Record, runner RunnerFunc, emit EventEmitter) (Record, error) {
	var lock *Lock
	if r.LockKey != nil {
		lock = NewLock(m.Journal.LocksDir, *r.LockKey, r.OperationID)
		if e := lock.Acquire(); e != nil {
			var b BlockedError
			if errors.As(e, &b) {
				return m.finishBlocked(r, b, emit), nil
			}
			return *r, e
		}
		defer lock.Release()
	}
	if e := m.setRunning(r); e != nil {
		return *r, e
	}
	_ = m.event(r, "operation_started", map[string]any{"state": r.State}, emit)
	progress := func(update any) error {
		if m.cancelled(r.OperationID) {
			return ErrCancelled
		}
		detail := map[string]any{"message": fmt.Sprint(update)}
		if x, ok := normalize(update).(map[string]any); ok {
			detail = x
		}
		text := fmt.Sprint(detail["message"])
		if text == "<nil>" || text == "" {
			text = fmt.Sprint(detail["phase"])
		}
		if text == "<nil>" || text == "" {
			text = "Working"
		}
		r.ProgressText = text
		if p := detail["phase"]; p != nil {
			s := fmt.Sprint(p)
			r.Phase = &s
		}
		if n, ok := number(detail["percent"]); ok {
			i := int(n)
			if i < 0 {
				i = 0
			}
			if i > 100 {
				i = 100
			}
			r.ProgressPercent = &i
		} else {
			r.ProgressPercent = nil
		}
		x := redaction.Value(normalize(detail))
		event, _ := x.(map[string]any)
		if event == nil {
			event = map[string]any{"message": fmt.Sprint(x)}
		}
		if _, ok := event["message"]; !ok {
			event["message"] = text
		}
		event["timestamp"] = float64(m.Now().UnixNano()) / 1e9
		r.ProgressDetail = event
		r.ProgressEvents = append(r.ProgressEvents, event)
		if len(r.ProgressEvents) > 80 {
			r.ProgressEvents = r.ProgressEvents[len(r.ProgressEvents)-80:]
		}
		if e := m.Journal.Save(r); e != nil {
			return e
		}
		return m.event(r, "operation_progress", event, emit)
	}
	if m.cancelled(r.OperationID) {
		return m.finishCancelled(r, "Cancellation requested", emit), nil
	}
	result, e := runner(progress, func() bool { return m.cancelled(r.OperationID) || ctx.Err() != nil })
	if e != nil {
		if errors.Is(e, ErrCancelled) || m.cancelled(r.OperationID) || errors.Is(e, context.Canceled) {
			return m.finishCancelled(r, "Cancellation requested", emit), nil
		}
		return m.finishFailed(r, e, emit), nil
	}
	if m.cancelled(r.OperationID) || ctx.Err() != nil {
		return m.finishCancelled(r, "Cancellation requested", emit), nil
	}
	r.State = "succeeded"
	now := float64(m.Now().UnixNano()) / 1e9
	r.FinishedAt = &now
	r.ProgressText = "Completed"
	p := 100
	r.ProgressPercent = &p
	r.ResultPayload = redaction.Value(normalize(result))
	r.NextSteps = nextSteps(result)
	_ = m.Journal.Save(r)
	_ = m.event(r, "operation_succeeded", map[string]any{"result": r.ResultPayload}, emit)
	_ = m.Journal.ClearCancel(r.OperationID)
	return *r, nil
}
func nextSteps(v any) []string {
	m, ok := normalize(v).(map[string]any)
	if !ok {
		return []string{}
	}
	return stringSlice(m["next_steps"])
}
func (m *Manager) finishBlocked(r *Record, e BlockedError, emit EventEmitter) Record {
	r.State = "blocked"
	now := float64(m.Now().UnixNano()) / 1e9
	r.FinishedAt = &now
	r.ProgressText = "Blocked"
	code := "OPERATION_BLOCKED"
	msg := e.Error()
	r.ErrorCode = &code
	r.Error = &msg
	r.NextSteps = []string{}
	if e.BlockingOperationID != "" {
		r.NextSteps = append(r.NextSteps, "Review operation "+e.BlockingOperationID+".")
	}
	r.NextSteps = append(r.NextSteps, "Retry after the conflicting operation finishes.")
	_ = m.Journal.Save(r)
	_ = m.event(r, "operation_blocked", map[string]any{"message": msg}, emit)
	_ = m.Journal.ClearCancel(r.OperationID)
	return *r
}
func errorCode(e error) string {
	var app apperrors.AppError
	if errors.As(e, &app) && app.Code != "" {
		return app.Code
	}
	type coder interface{ Code() string }
	var c coder
	if errors.As(e, &c) && c.Code() != "" {
		return c.Code()
	}
	return "OPERATION_FAILED"
}
func (m *Manager) finishFailed(r *Record, e error, emit EventEmitter) Record {
	r.State = "failed"
	now := float64(m.Now().UnixNano()) / 1e9
	r.FinishedAt = &now
	r.ProgressText = "Failed"
	code := errorCode(e)
	msg := e.Error()
	if msg == "" {
		msg = fmt.Sprintf("%T", e)
	}
	r.ErrorCode = &code
	r.Error = &msg
	_ = m.Journal.Save(r)
	_ = m.event(r, "operation_failed", map[string]any{"code": code, "message": msg}, emit)
	_ = m.Journal.ClearCancel(r.OperationID)
	return *r
}
func (m *Manager) finishCancelled(r *Record, msg string, emit EventEmitter) Record {
	r.State = "cancelled"
	now := float64(m.Now().UnixNano()) / 1e9
	r.FinishedAt = &now
	r.ProgressText = "Cancelled"
	code := "CANCELLED"
	r.ErrorCode = &code
	r.Error = &msg
	_ = m.Journal.Save(r)
	_ = m.event(r, "operation_cancelled", map[string]any{"message": msg}, emit)
	_ = m.Journal.ClearCancel(r.OperationID)
	return *r
}
func (m *Manager) event(r *Record, kind string, payload map[string]any, emit EventEmitter) error {
	r.EventSequence++
	event := map[string]any{"schemaVersion": r.SchemaVersion, "sequence": r.EventSequence, "type": kind, "operationId": r.OperationID, "timestamp": float64(m.Now().UnixNano()) / 1e9, "payload": redaction.Value(normalize(payload))}
	if e := m.Journal.Save(r); e != nil {
		return e
	}
	if e := m.Journal.AppendEvent(r.OperationID, event); e != nil {
		return e
	}
	if emit != nil {
		_ = emit(event)
	}
	return nil
}
func (m *Manager) Get(id string, eventLimit int) (Record, error) {
	r, e := m.Journal.Load(id)
	if e != nil {
		return Record{}, e
	}
	events, e := m.Journal.ReadEvents(id, eventLimit)
	if e != nil {
		return Record{}, e
	}
	r.ProgressEvents = events
	return r, nil
}
func (m *Manager) ListRecent(limit int, target *string) ([]Record, error) {
	return m.Journal.ListRecent(limit, target)
}
func identity(r Record) *sys.ProcessIdentity {
	if r.PID == nil || r.ProcessGroupID == nil {
		return nil
	}
	return &sys.ProcessIdentity{PID: *r.PID, ProcessGroupID: *r.ProcessGroupID, StartTimeTicks: r.ProcessStartTime, BootID: r.ProcessBootID}
}
func (m *Manager) Cancel(id string) (Record, error) {
	r, e := m.Journal.Load(id)
	if e != nil {
		return Record{}, e
	}
	if r.IsComplete() {
		return r, nil
	}
	if e = m.Journal.RequestCancel(id); e != nil {
		return Record{}, e
	}
	r.State = "cancelling"
	r.ProgressText = "Cancelling"
	_ = m.Journal.Save(&r)
	_ = m.event(&r, "operation_cancelling", map[string]any{}, nil)
	signalled := false
	for i := len(r.ChildProcesses) - 1; i >= 0; i-- {
		if p := sys.ProcessIdentityFromMap(r.ChildProcesses[i]); p != nil {
			signalled = sys.SignalProcessIdentity(*p, syscall.SIGTERM) || signalled
		}
	}
	host := identity(r)
	if host != nil && host.PID != os.Getpid() {
		pg := syscall.Getpgrp()
		if host.ProcessGroupID != pg {
			signalled = sys.SignalProcessIdentity(*host, syscall.SIGTERM) || signalled
		}
	}
	if !signalled && host != nil && !sys.ProcessIdentityMatches(*host) {
		x := m.finishCancelled(&r, "Cancellation requested after the operation process exited", nil)
		return x, nil
	}
	return r, nil
}
