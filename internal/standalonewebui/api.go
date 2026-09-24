package standalonewebui

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"chrootctl/internal/bridge"
)

type Dispatcher interface {
	Capabilities() map[string]any
	State(context.Context, string) bridge.Response
	Query(context.Context, bridge.Request) bridge.Response
	Preview(context.Context, bridge.Request) bridge.Response
	Run(context.Context, bridge.Request, func(map[string]any) error) int
	Operation(string) bridge.Response
	Cancel(string) bridge.Response
	Reconcile(context.Context, string) bridge.Response
}

func requestID() string {
	b := make([]byte, 12)
	if _, err := rand.Read(b); err != nil {
		return "http-request"
	}
	return "http-" + hex.EncodeToString(b)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func decodePayload(w http.ResponseWriter, r *http.Request) (map[string]any, bool) {
	if r.Body == nil {
		return map[string]any{}, true
	}
	dec := json.NewDecoder(r.Body)
	dec.UseNumber()
	var p map[string]any
	if err := dec.Decode(&p); err != nil {
		http.Error(w, "invalid JSON payload", http.StatusBadRequest)
		return nil, false
	}
	if p == nil {
		p = map[string]any{}
	}
	return p, true
}

func bridgeRequest(op string, payload map[string]any, id string) (bridge.Request, error) {
	if strings.TrimSpace(id) == "" {
		id = requestID()
	}
	raw, err := json.Marshal(map[string]any{"protocolVersion": bridge.ProtocolVersion, "requestId": id, "operation": op, "payload": payload})
	if err != nil {
		return bridge.Request{}, err
	}
	return bridge.ParseRequest(raw)
}

func validatedRequest(w http.ResponseWriter, op string, payload map[string]any, id string) (bridge.Request, bool) {
	req, err := bridgeRequest(op, payload, id)
	if err != nil {
		http.Error(w, "invalid typed request: "+err.Error(), http.StatusBadRequest)
		return bridge.Request{}, false
	}
	return req, true
}

func requestIDHeader(r *http.Request) string {
	return strings.TrimSpace(r.Header.Get("X-Chrootctl-Request-ID"))
}

func eventString(v any) string {
	s, _ := v.(string)
	return s
}

func terminalEvent(v map[string]any) bool {
	switch strings.TrimSpace(eventString(v["type"])) {
	case "operation_succeeded", "operation_failed", "operation_cancelled", "operation_blocked", "bridge_error":
		return true
	default:
		return false
	}
}

// startOperation detaches a typed mutation from the lifetime of the HTTP
// request. Browser request cancellation must not consume a one-shot preview and
// then cause the WebUI to replay the mutation. Progress and terminal state are
// read back from the persistent operation journal.
func (s *Server) startOperation(d Dispatcher, req bridge.Request) map[string]any {
	events := make(chan map[string]any, 16)
	done := make(chan int, 1)
	go func() {
		s.beginOperation()
		defer s.endOperation()
		s.logf("operation start request_id=%s operation=%s", req.RequestID, req.Operation)
		code := d.Run(s.operationContext(), req, func(v map[string]any) error {
			select {
			case events <- v:
			default:
			}
			return nil
		})
		s.logf("operation finish request_id=%s operation=%s exit=%d", req.RequestID, req.Operation, code)
		done <- code
	}()

	ack := map[string]any{
		"accepted":    true,
		"requestId":   req.RequestID,
		"operationId": "",
		"events":      []map[string]any{},
	}
	collected := []map[string]any{}
	timer := time.NewTimer(2 * time.Second)
	defer timer.Stop()
	for {
		select {
		case event := <-events:
			collected = append(collected, event)
			if id := strings.TrimSpace(eventString(event["operationId"])); id != "" {
				ack["operationId"] = id
			}
			ack["events"] = collected
			if terminalEvent(event) || ack["operationId"] != "" {
				return ack
			}
		case code := <-done:
			for {
				select {
				case event := <-events:
					collected = append(collected, event)
					if id := strings.TrimSpace(eventString(event["operationId"])); id != "" {
						ack["operationId"] = id
					}
				default:
					ack["events"] = collected
					ack["exitCode"] = code
					ack["complete"] = true
					return ack
				}
			}
		case <-timer.C:
			ack["events"] = collected
			return ack
		}
	}
}

func (s *Server) apiHandler(d Dispatcher) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/health", s.auth(s.health))
	mux.HandleFunc("/api/v1/capabilities", s.auth(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method", 405)
			return
		}
		writeJSON(w, 200, bridge.Success(requestID(), d.Capabilities()))
	}))
	mux.HandleFunc("/api/v1/state", s.auth(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method", 405)
			return
		}
		writeJSON(w, 200, d.State(r.Context(), requestID()))
	}))
	mux.HandleFunc("/api/v1/query/", s.auth(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method", 405)
			return
		}
		p, ok := decodePayload(w, r)
		if !ok {
			return
		}
		op := strings.TrimPrefix(r.URL.Path, "/api/v1/query/")
		req, valid := validatedRequest(w, op, p, "")
		if !valid {
			return
		}
		writeJSON(w, 200, d.Query(r.Context(), req))
	}))
	mux.HandleFunc("/api/v1/preview/", s.auth(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method", 405)
			return
		}
		p, ok := decodePayload(w, r)
		if !ok {
			return
		}
		op := strings.TrimPrefix(r.URL.Path, "/api/v1/preview/")
		req, valid := validatedRequest(w, op, p, "")
		if !valid {
			return
		}
		writeJSON(w, 200, d.Preview(r.Context(), req))
	}))
	mux.HandleFunc("/api/v1/run/", s.auth(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method", 405)
			return
		}
		p, ok := decodePayload(w, r)
		if !ok {
			return
		}
		op := strings.TrimPrefix(r.URL.Path, "/api/v1/run/")
		req, valid := validatedRequest(w, op, p, requestIDHeader(r))
		if !valid {
			return
		}
		writeJSON(w, http.StatusAccepted, s.startOperation(d, req))
	}))
	mux.HandleFunc("/api/v1/operations/", s.auth(func(w http.ResponseWriter, r *http.Request) {
		tail := strings.TrimPrefix(r.URL.Path, "/api/v1/operations/")
		parts := strings.Split(strings.Trim(tail, "/"), "/")
		if len(parts) < 1 || parts[0] == "" {
			http.Error(w, "operation id required", 400)
			return
		}
		id := parts[0]
		if len(parts) == 1 && r.Method == http.MethodGet {
			writeJSON(w, 200, d.Operation(id))
			return
		}
		if len(parts) == 2 && r.Method == http.MethodPost && parts[1] == "cancel" {
			writeJSON(w, 200, d.Cancel(id))
			return
		}
		if len(parts) == 2 && r.Method == http.MethodPost && parts[1] == "reconcile" {
			writeJSON(w, 200, d.Reconcile(r.Context(), id))
			return
		}
		http.Error(w, "method or route", 405)
	}))
	return mux
}
