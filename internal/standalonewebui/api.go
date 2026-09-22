package standalonewebui

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strings"

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

func bridgeRequest(op string, payload map[string]any) (bridge.Request, error) {
	raw, err := json.Marshal(map[string]any{"protocolVersion": bridge.ProtocolVersion, "requestId": requestID(), "operation": op, "payload": payload})
	if err != nil {
		return bridge.Request{}, err
	}
	return bridge.ParseRequest(raw)
}

func validatedRequest(w http.ResponseWriter, op string, payload map[string]any) (bridge.Request, bool) {
	req, err := bridgeRequest(op, payload)
	if err != nil {
		http.Error(w, "invalid typed request: "+err.Error(), http.StatusBadRequest)
		return bridge.Request{}, false
	}
	return req, true
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
		req, valid := validatedRequest(w, op, p)
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
		req, valid := validatedRequest(w, op, p)
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
		events := []map[string]any{}
		req, valid := validatedRequest(w, op, p)
		if !valid {
			return
		}
		code := d.Run(r.Context(), req, func(v map[string]any) error { events = append(events, v); return nil })
		// Reaching the typed operation endpoint is a successful HTTP transport.
		// Application-level failure is represented by exitCode + terminal events;
		// returning HTTP 4xx here makes the browser discard those diagnostics.
		writeJSON(w, http.StatusOK, map[string]any{"events": events, "exitCode": code})
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
