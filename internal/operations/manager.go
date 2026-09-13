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
	"chrootctl/internal/mutation"
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
	r.LockScope = o.LockScope
	r.CreatedAt = float64(m.Now().UnixNano()) / 1e9
	if e = m.Journal.ClearCancel(id); e != nil {
		return Record{}, fmt.Errorf("clear stale cancellation marker: %w", e)
	}
	if e = m.Journal.Save(&r); e != nil {
		return Record{}, e
	}
	if e = m.event(&r, "operation_queued", map[string]any{"state": r.State}, nil); e != nil {
		return Record{}, fmt.Errorf("persist queued operation event: %w", e)
	}
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
	var lease *mutation.Lease
	if r.LockScope != "" && r.LockScope != "none" {
		target := ""
		if r.TargetName != nil {
			target = *r.TargetName
		}
		var e error
		lease, _, e = mutation.AcquireScope(ctx, m.Journal.LocksDir, r.LockScope, target, r.OperationID)
		if e != nil {
			var b mutation.BlockedError
			if errors.As(e, &b) {
				rec, perr := m.finishBlocked(r, BlockedError{LockKey: b.LockKey, BlockingOperationID: b.BlockingOperationID}, emit)
				return rec, perr
			}
			return *r, e
		}
		defer lease.Release()
	}
	if e := m.setRunning(r); e != nil {
		return *r, e
	}
	if e := m.event(r, "operation_started", map[string]any{"state": r.State}, emit); e != nil {
		return *r, fmt.Errorf("persist operation start event: %w", e)
	}
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
		return m.finishCancelled(r, "Cancellation requested", emit)
	}
	result, e := runner(progress, func() bool { return m.cancelled(r.OperationID) || ctx.Err() != nil })
	if e != nil {
		if errors.Is(e, ErrCancelled) || m.cancelled(r.OperationID) || errors.Is(e, context.Canceled) {
			return m.finishCancelled(r, "Cancellation requested", emit)
		}
		return m.finishFailed(r, e, emit)
	}
	if m.cancelled(r.OperationID) || ctx.Err() != nil {
		return m.finishCancelled(r, "Cancellation requested", emit)
	}
	r.State = "succeeded"
	now := float64(m.Now().UnixNano()) / 1e9
	r.FinishedAt = &now
	r.ProgressText = "Completed"
	p := 100
	r.ProgressPercent = &p
	r.ResultPayload = redaction.Value(normalize(result))
	r.NextSteps = nextSteps(result)
	if e := m.persistTerminal(r, "operation_succeeded", map[string]any{"result": r.ResultPayload}, emit); e != nil {
		return *r, e
	}
	return *r, nil
}
func nextSteps(v any) []string {
	m, ok := normalize(v).(map[string]any)
	if !ok {
		return []string{}
	}
	return stringSlice(m["next_steps"])
}
func (m *Manager) finishBlocked(r *Record, e BlockedError, emit EventEmitter) (Record, error) {
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
	if err := m.persistTerminal(r, "operation_blocked", map[string]any{"message": msg}, emit); err != nil {
		return *r, err
	}
	return *r, nil
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
func (m *Manager) finishFailed(r *Record, e error, emit EventEmitter) (Record, error) {
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
	if err := m.persistTerminal(r, "operation_failed", map[string]any{"code": code, "message": msg}, emit); err != nil {
		return *r, errors.Join(e, err)
	}
	return *r, nil
}
func (m *Manager) finishCancelled(r *Record, msg string, emit EventEmitter) (Record, error) {
	r.State = "cancelled"
	now := float64(m.Now().UnixNano()) / 1e9
	r.FinishedAt = &now
	r.ProgressText = "Cancelled"
	code := "CANCELLED"
	r.ErrorCode = &code
	r.Error = &msg
	if err := m.persistTerminal(r, "operation_cancelled", map[string]any{"message": msg}, emit); err != nil {
		return *r, err
	}
	return *r, nil
}
func (m *Manager) persistTerminal(r *Record, kind string, payload map[string]any, emit EventEmitter) error {
	if err := m.Journal.Save(r); err != nil {
		return fmt.Errorf("persist terminal operation state: %w", err)
	}
	if err := m.event(r, kind, payload, emit); err != nil {
		return fmt.Errorf("persist terminal operation event: %w", err)
	}
	if err := m.Journal.ClearCancel(r.OperationID); err != nil {
		return fmt.Errorf("clear terminal cancellation marker: %w", err)
	}
	return nil
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
	if e = m.Journal.Save(&r); e != nil {
		return Record{}, fmt.Errorf("persist cancelling state: %w", e)
	}
	if e = m.event(&r, "operation_cancelling", map[string]any{}, nil); e != nil {
		return Record{}, fmt.Errorf("persist cancelling event: %w", e)
	}
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
		x, err := m.finishCancelled(&r, "Cancellation requested after the operation process exited", nil)
		return x, err
	}
	return r, nil
}
