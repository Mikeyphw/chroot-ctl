package bridge

import (
	"context"
	"encoding/json"
	"path/filepath"
	"strings"

	"chrootctl/internal/mutation"
	"chrootctl/internal/operations"
	"chrootctl/internal/services"
	"chrootctl/internal/version"
)

type Dispatcher struct {
	Backend          Backend
	Operations       *operations.Manager
	Mutations        *mutation.Engine
	Previews         *PreviewStore
	OperationLogPath string
}

func NewDispatcher(backend Backend, manager *operations.Manager, previews *PreviewStore) *Dispatcher {
	return &Dispatcher{Backend: backend, Operations: manager, Previews: previews}
}
func NewServicesDispatcher(s *services.Container) (*Dispatcher, error) {
	root := filepath.Join(filepath.Dir(s.BaseConfig.DatabasePath), "operations")
	m := s.Operations
	var p *PreviewStore
	if !s.DryRun {
		if m == nil {
			var e error
			m, e = operations.NewManager(root, false)
			if e != nil {
				return nil, e
			}
		}
		var e error
		p, e = NewPreviewStore(filepath.Join(filepath.Dir(root), "previews"))
		if e != nil {
			return nil, e
		}
	}
	d := NewDispatcher(NewServicesBackend(s), m, p)
	d.Mutations = s.Mutations
	d.OperationLogPath = s.BaseConfig.LogFile
	return d, nil
}
func (d *Dispatcher) Capabilities() map[string]any {
	root := ""
	if d.Operations != nil {
		root = d.Operations.Journal.Root
	}
	return map[string]any{"protocolVersion": ProtocolVersion, "backendVersion": version.Version, "operations": Capabilities(), "operationRoot": root, "transport": []string{"json", "ndjson"}, "arbitraryShell": false}
}
func (d *Dispatcher) State(ctx context.Context, id string) Response {
	v, e := d.Backend.State(ctx)
	if e != nil {
		return Failure(id, e)
	}
	return Success(id, v)
}
func (d *Dispatcher) Query(ctx context.Context, r Request) Response {
	if _, e := Resolve(r, "query"); e != nil {
		return Failure(r.RequestID, e)
	}
	v, e := d.Backend.Invoke(ctx, "query", r.Operation, r.Payload, nil, nil)
	if e != nil {
		return Failure(r.RequestID, asBridgeError(e))
	}
	return Success(r.RequestID, v)
}
func (d *Dispatcher) Preview(ctx context.Context, r Request) Response {
	if _, e := Resolve(r, "preview"); e != nil {
		return Failure(r.RequestID, e)
	}
	v, e := d.Backend.Invoke(ctx, "preview", r.Operation, r.Payload, nil, nil)
	if e != nil {
		return Failure(r.RequestID, asBridgeError(e))
	}
	action := ActionForPreview(r.Operation, r.Payload)
	if action != "" && previewRequired[action] && d.Previews != nil {
		contract, e := d.Previews.Issue(r.Operation, action, r.Payload, v)
		if e != nil {
			return Failure(r.RequestID, e)
		}
		if m, ok := v.(map[string]any); ok {
			for k, x := range contract {
				m[k] = x
			}
			v = m
		} else {
			v = map[string]any{"ok": true, "result": v}
			for k, x := range contract {
				v.(map[string]any)[k] = x
			}
		}
	}
	return Success(r.RequestID, v)
}
func (d *Dispatcher) verifyPreview(ctx context.Context, action string, p map[string]any) error {
	if !previewRequired[action] || d.Previews == nil {
		return nil
	}
	rec, e := d.Previews.Verify(action, p)
	if e != nil {
		return e
	}
	previewOp, previewPayload, ok := PreviewForAction(action, p, asString(rec["previewOperation"]))
	if !ok {
		return protocolError("PREVIEW_CONTRACT_UNSUPPORTED", "No preview contract is defined for "+action, nil)
	}
	req := Request{ProtocolVersion: ProtocolVersion, RequestID: "preview-verify", Operation: previewOp, Payload: previewPayload}
	if _, e = Resolve(req, "preview"); e != nil {
		return protocolError("PREVIEW_CONTRACT_UNSUPPORTED", "Preview operation "+previewOp+" is unavailable", nil)
	}
	current, e := d.Backend.Invoke(ctx, "preview", previewOp, previewPayload, nil, nil)
	if e != nil {
		return e
	}
	if resourceRevision(current) != asString(rec["resourceRevision"]) {
		return protocolError("PREVIEW_STALE", "Resource state changed after preview; review the updated preview before applying the action.", nil)
	}
	return nil
}
func (d *Dispatcher) Run(ctx context.Context, r Request, emit func(map[string]any) error) int {
	if _, e := Resolve(r, "operation"); e != nil {
		emitBridgeError(emit, r.RequestID, e)
		return 2
	}
	if d.Operations != nil {
		if _, e := d.Operations.Recover(ctx); e != nil {
			emitBridgeError(emit, r.RequestID, e)
			return 2
		}
	}
	if r.Operation == "operations.retry" {
		return d.runRetry(ctx, r, emit)
	}
	if e := d.verifyPreview(ctx, r.Operation, r.Payload); e != nil {
		if d.Operations != nil {
			spec := Specs[r.Operation]
			targetText := strings.TrimSpace(asString(r.Payload["name"]))
			var target *string
			if targetText != "" {
				target = &targetText
			}
			request := map[string]any{"protocolVersion": r.ProtocolVersion, "requestId": r.RequestID, "operation": r.Operation, "payload": r.Payload}
			rec, createErr := d.Operations.Create(operations.CreateOptions{Kind: r.Operation, Title: defaultTitle(r.Payload, spec.Description), TargetName: target, Request: request, Retry: request, LogPath: d.operationLogPath(), LockScope: spec.LockScope})
			if createErr == nil {
				eventSink := func(event map[string]any) error {
					event = cloneAnyMap(event)
					event["protocolVersion"] = r.ProtocolVersion
					event["requestId"] = r.RequestID
					if emit != nil {
						return emit(event)
					}
					return nil
				}
				if _, blockErr := d.Operations.BlockPreflight(&rec, asBridgeError(e), eventSink); blockErr == nil {
					return 2
				}
			}
		}
		emitBridgeError(emit, r.RequestID, e)
		return 2
	}
	return d.runSpec(ctx, r, r.Operation, r.Payload, emit, nil, "")
}
func (d *Dispatcher) runRetry(ctx context.Context, r Request, emit func(map[string]any) error) int {
	id := strings.TrimSpace(asString(r.Payload["operationId"]))
	if id == "" {
		id = strings.TrimSpace(asString(r.Payload["operation_id"]))
	}
	if id == "" {
		id = strings.TrimSpace(asString(r.Payload["id"]))
	}
	if id == "" {
		emitBridgeError(emit, r.RequestID, protocolError("MISSING_OPERATION_ID", "payload.operationId is required", nil))
		return 2
	}
	mode := strings.TrimSpace(asString(r.Payload["mode"]))
	if mode == "" {
		mode = "retry"
	}
	if mode != "retry" && mode != "repair" {
		emitBridgeError(emit, r.RequestID, protocolError("INVALID_RETRY_MODE", "Unsupported retry mode: "+mode, nil))
		return 2
	}
	parent, e := d.Operations.Get(id, 200)
	if e != nil {
		emitBridgeError(emit, r.RequestID, protocolError("UNKNOWN_OPERATION_ID", "Unknown operation: "+id, nil))
		return 2
	}
	stored := parent.Retry
	if len(stored) == 0 {
		stored = parent.Request
	}
	if len(stored) == 0 {
		emitBridgeError(emit, r.RequestID, protocolError("RETRY_REQUEST_UNAVAILABLE", "The operation journal does not contain a retry request", nil))
		return 2
	}
	if containsRedacted(stored) {
		emitBridgeError(emit, r.RequestID, protocolError("REDACTED_RETRY_REQUEST", "The stored retry request contains redacted secrets; re-enter the sensitive fields instead of replaying it.", nil))
		return 2
	}
	op := strings.TrimSpace(asString(stored["operation"]))
	payload, _ := stored["payload"].(map[string]any)
	if op == "" || op == "operations.retry" {
		emitBridgeError(emit, r.RequestID, protocolError("INVALID_RETRY_OPERATION", "The stored request cannot be replayed", nil))
		return 2
	}
	spec, ok := Specs[op]
	if !ok || spec.Mode != "operation" {
		emitBridgeError(emit, r.RequestID, protocolError("UNSUPPORTED_RETRY_OPERATION", "Cannot retry unsupported operation: "+op, nil))
		return 2
	}
	if previewRequired[op] {
		emitBridgeError(emit, r.RequestID, protocolError("PREVIEW_RETRY_REQUIRES_PREVIEW", "Preview-bound operations must be previewed again before retrying so stale approvals cannot be replayed.", nil))
		return 2
	}
	if mode == "repair" {
		if op != "install.run" {
			emitBridgeError(emit, r.RequestID, protocolError("RETRY_FIXES_UNSUPPORTED", "Retry with fixes is available only for install operations", nil))
			return 2
		}
		payload = cloneAnyMap(payload)
		payload["repair"] = true
		payload["resume"] = true
	}
	child := Request{ProtocolVersion: r.ProtocolVersion, RequestID: r.RequestID, Operation: op, Payload: payload}
	return d.runSpec(ctx, child, op, payload, emit, &id, mode)
}

func (d *Dispatcher) operationLogPath() *string {
	path := strings.TrimSpace(d.OperationLogPath)
	if path == "" {
		return nil
	}
	return &path
}

func (d *Dispatcher) runSpec(ctx context.Context, r Request, op string, p map[string]any, emit func(map[string]any) error, parent *string, retryMode string) int {
	spec := Specs[op]
	targetText := strings.TrimSpace(asString(p["name"]))
	var target *string
	if targetText != "" {
		target = &targetText
	}
	request := map[string]any{"protocolVersion": r.ProtocolVersion, "requestId": r.RequestID, "operation": op, "payload": p}
	if d.Operations == nil {
		if d.Mutations != nil {
			if _, recoveryErr := d.Mutations.RecoverLocked(ctx, targetText); recoveryErr != nil {
				emitBridgeError(emit, r.RequestID, recoveryErr)
				return 2
			}
		}
		_, invokeErr := d.Backend.Invoke(ctx, "operation", op, p, func(v any) error {
			if emit == nil {
				return nil
			}
			if m, ok := v.(map[string]any); ok {
				return emit(m)
			}
			return nil
		}, func() bool { return false })
		if invokeErr != nil {
			emitBridgeError(emit, r.RequestID, invokeErr)
			return 2
		}
		return 0
	}
	rec, e := d.Operations.Create(operations.CreateOptions{Kind: op, Title: defaultTitle(p, spec.Description), TargetName: target, Request: request, Retry: request, LogPath: d.operationLogPath(), LockScope: spec.LockScope, ParentOperationID: parent})
	if e != nil {
		emitBridgeError(emit, r.RequestID, e)
		return 2
	}
	eventSink := func(event map[string]any) error {
		event = cloneAnyMap(event)
		event["protocolVersion"] = r.ProtocolVersion
		event["requestId"] = r.RequestID
		if parent != nil {
			event["parentOperationId"] = *parent
		}
		if retryMode != "" {
			event["retryMode"] = retryMode
		}
		if emit != nil {
			return emit(event)
		}
		return nil
	}
	completed, e := d.Operations.Execute(ctx, &rec, func(progress operations.ProgressFunc, cancel func() bool) (any, error) {
		execCtx := services.WithOperationProvenance(ctx, rec.OperationID, op)
		if d.Mutations != nil {
			recoveryTarget := targetText
			if spec.LockScope == "global" {
				recoveryTarget = ""
			}
			if _, recoveryErr := d.Mutations.RecoverLocked(execCtx, recoveryTarget); recoveryErr != nil {
				return nil, recoveryErr
			}
		}
		return d.Backend.Invoke(execCtx, "operation", op, p, func(v any) error { return progress(v) }, cancel)
	}, eventSink)
	if e != nil {
		emitBridgeError(emit, r.RequestID, e)
		return 2
	}
	if completed.State == "succeeded" {
		return 0
	}
	return 2
}
func defaultTitle(p map[string]any, d string) string {
	if x := strings.TrimSpace(asString(p["title"])); x != "" {
		return x
	}
	return d
}
func cloneAnyMap(m map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range m {
		out[k] = v
	}
	return out
}
func emitBridgeError(emit func(map[string]any) error, id string, e error) {
	if emit == nil {
		return
	}
	v := responseMap(Failure(id, asBridgeError(e)))
	v["type"] = "bridge_error"
	v["operationId"] = ""
	_ = emit(v)
}
func responseMap(r Response) map[string]any {
	b, _ := jsonMarshal(r)
	var m map[string]any
	_ = jsonUnmarshal(b, &m)
	return m
}
func jsonMarshal(v any) ([]byte, error)   { return json.Marshal(v) }
func jsonUnmarshal(b []byte, v any) error { return json.Unmarshal(b, v) }

func (d *Dispatcher) Operation(id string) Response {
	if d.Operations == nil {
		return Failure(id, protocolError("DRY_RUN_NO_JOURNAL", "Dry-run operations are not persisted", nil))
	}
	r, e := d.Operations.Get(id, 200)
	if e != nil {
		return Failure(id, protocolError("UNKNOWN_OPERATION_ID", "Unknown operation: "+id, nil))
	}
	return Success(id, r)
}
func (d *Dispatcher) Cancel(id string) Response {
	if d.Operations == nil {
		return Failure(id, protocolError("DRY_RUN_NO_JOURNAL", "Dry-run operations are not persisted", nil))
	}
	r, e := d.Operations.Cancel(id)
	if e != nil {
		return Failure(id, protocolError("UNKNOWN_OPERATION_ID", "Unknown operation: "+id, nil))
	}
	return Success(id, r)
}
func (d *Dispatcher) Reconcile(ctx context.Context, id string) Response {
	if d.Operations == nil {
		return Failure(id, protocolError("DRY_RUN_NO_JOURNAL", "Dry-run operations are not persisted", nil))
	}
	r, e := d.Operations.Reconcile(ctx, id)
	if e != nil {
		return Failure(id, protocolError("UNKNOWN_OPERATION_ID", "Unknown operation: "+id, nil))
	}
	return Success(id, r)
}
func asBridgeError(e error) error {
	if e == nil {
		return nil
	}
	var pe ProtocolError
	if asProtocolError(e, &pe) {
		return pe
	}
	text := e.Error()
	lower := strings.ToLower(text)
	if strings.Contains(lower, "unknown chroot") || strings.Contains(lower, "not found") {
		return protocolError("NOT_FOUND", text, nil)
	}
	if strings.Contains(lower, "invalid") || strings.Contains(lower, "required") || strings.Contains(lower, "must ") {
		return protocolError("INVALID_ARGUMENT", text, nil)
	}
	return e
}
