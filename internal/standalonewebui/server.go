package standalonewebui

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"
)

const cookieName = "chrootctl_webui"

type Config struct {
	IdleTimeout, SessionTTL time.Duration
	MaxBodyBytes            int64
}
type Server struct {
	cfg      Config
	token    string
	mu       sync.Mutex
	sessions map[string]session
	last     time.Time
	http     *http.Server
	ln       net.Listener
}
type session struct {
	expires time.Time
	csrf    string
}

type Info struct {
	URL          string `json:"url"`
	BootstrapURL string `json:"bootstrapUrl"`
}

func defaults(c Config) Config {
	if c.IdleTimeout <= 0 {
		c.IdleTimeout = 10 * time.Minute
	}
	if c.SessionTTL <= 0 {
		c.SessionTTL = 30 * time.Minute
	}
	if c.MaxBodyBytes <= 0 {
		c.MaxBodyBytes = 64 << 10
	}
	return c
}
func secret() (string, error) {
	b := make([]byte, 32)
	if _, e := rand.Read(b); e != nil {
		return "", e
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}
func New(c Config) (*Server, error) {
	t, e := secret()
	if e != nil {
		return nil, e
	}
	return &Server{cfg: defaults(c), token: t, sessions: map[string]session{}, last: time.Now()}, nil
}
func (s *Server) Start(ctx context.Context) (Info, error) {
	ln, e := net.Listen("tcp4", "127.0.0.1:0")
	if e != nil {
		return Info{}, e
	}
	s.ln = ln
	mux := http.NewServeMux()
	mux.HandleFunc("/bootstrap", s.bootstrap)
	mux.HandleFunc("/api/v1/health", s.auth(s.health))
	s.http = &http.Server{Handler: s.security(mux), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 10 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 16 << 10}
	go func() {
		<-ctx.Done()
		c, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = s.http.Shutdown(c)
	}()
	go s.idleWatch(ctx)
	go func() { _ = s.http.Serve(ln) }()
	base := "http://" + ln.Addr().String()
	return Info{URL: base, BootstrapURL: base + "/bootstrap?token=" + s.token}, nil
}
func (s *Server) idleWatch(ctx context.Context) {
	t := time.NewTicker(time.Second)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			s.mu.Lock()
			idle := time.Since(s.last) > s.cfg.IdleTimeout
			s.mu.Unlock()
			if idle {
				_ = s.http.Shutdown(context.Background())
				return
			}
		}
	}
}
func (s *Server) touch() { s.mu.Lock(); s.last = time.Now(); s.mu.Unlock() }
func (s *Server) security(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasPrefix(r.Host, "127.0.0.1:") && !strings.HasPrefix(r.Host, "localhost:") {
			http.Error(w, "invalid host", http.StatusForbidden)
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
		if r.ContentLength > s.cfg.MaxBodyBytes {
			http.Error(w, "request too large", http.StatusRequestEntityTooLarge)
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, s.cfg.MaxBodyBytes)
		s.touch()
		next.ServeHTTP(w, r)
	})
}
func (s *Server) bootstrap(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		http.Error(w, "method", 405)
		return
	}
	got := r.URL.Query().Get("token")
	s.mu.Lock()
	expected := s.token
	if expected != "" && subtle.ConstantTimeCompare([]byte(got), []byte(expected)) == 1 {
		s.token = ""
	} else {
		s.mu.Unlock()
		http.Error(w, "invalid or replayed bootstrap token", 401)
		return
	}
	sid, e := secret()
	if e != nil {
		s.mu.Unlock()
		http.Error(w, "entropy failure", 500)
		return
	}
	csrf, e := secret()
	if e != nil {
		s.mu.Unlock()
		http.Error(w, "entropy failure", 500)
		return
	}
	s.sessions[sid] = session{expires: time.Now().Add(s.cfg.SessionTTL), csrf: csrf}
	s.mu.Unlock()
	http.SetCookie(w, &http.Cookie{Name: cookieName, Value: sid, Path: "/", HttpOnly: true, SameSite: http.SameSiteStrictMode, MaxAge: int(s.cfg.SessionTTL.Seconds())})
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "api": "/api/v1"})
}
func (s *Server) auth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		c, e := r.Cookie(cookieName)
		if e != nil {
			http.Error(w, "authentication required", 401)
			return
		}
		s.mu.Lock()
		sess, ok := s.sessions[c.Value]
		if ok && time.Now().After(sess.expires) {
			delete(s.sessions, c.Value)
			ok = false
		}
		s.mu.Unlock()
		if !ok {
			http.Error(w, "authentication required", 401)
			return
		}
		if r.Method != "GET" && r.Method != "HEAD" {
			csrfCookie, _ := r.Cookie("chrootctl_csrf")
			if csrfCookie == nil || subtle.ConstantTimeCompare([]byte(r.Header.Get("X-CSRF-Token")), []byte(sess.csrf)) != 1 || subtle.ConstantTimeCompare([]byte(csrfCookie.Value), []byte(sess.csrf)) != 1 {
				http.Error(w, "csrf rejected", 403)
				return
			}
			origin := r.Header.Get("Origin")
			expected := "http://" + r.Host
			if origin != "" && origin != expected {
				http.Error(w, "invalid origin", 403)
				return
			}
		}
		next(w, r)
	}
}
func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		http.Error(w, "method", 405)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "transport": "standalone-loopback"})
}
func (s *Server) Addr() string {
	if s.ln == nil {
		return ""
	}
	return s.ln.Addr().String()
}
func (s *Server) String() string { return fmt.Sprintf("standalone webui %s", s.Addr()) }
