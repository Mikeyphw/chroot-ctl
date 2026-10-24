// Package skybindr1 is a strictly opt-in read-only Skybind R1 consumer.
// It never replaces chrootctl's sealed native rclone runtime or changes
// backup/archive/repository operations. All credentials stay in process RAM.
package skybindr1

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"strings"
	"time"
)

const grantEndpoint = "\x00skybind-r1-grant-handoff-v1"
const readEndpoint = "\x00skybind-r1-consumer-gateway-v1"
const responseLimit = 1 << 20

var readOps = map[string]bool{"system.capabilities": true, "rclone.version": true, "rclone.listremotes": true, "rclone.lsjson": true, "rclone.size": true}

type grant struct {
	Version   int       `json:"version"`
	Token     string    `json:"token"`
	ExpiresAt time.Time `json:"expires_at"`
}
type request struct {
	Version   int    `json:"version"`
	Token     string `json:"token"`
	Operation string `json:"operation"`
	Remote    string `json:"remote"`
	Path      string `json:"path"`
}
type response struct {
	Version int             `json:"version"`
	OK      bool            `json:"ok"`
	Error   string          `json:"error,omitempty"`
	Result  json.RawMessage `json:"result,omitempty"`
}

func validateArgs(op, remote, path string) error {
	if !readOps[op] || len(remote) == 0 || len(remote) > 63 || len(path) > 4096 || strings.ContainsAny(path, "\\:%?#\r\n\x00") || strings.HasPrefix(path, "/") {
		return errors.New("r1 unsafe read scope")
	}
	for _, c := range remote {
		if !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-') {
			return errors.New("r1 invalid remote")
		}
	}
	if path != "" {
		for _, p := range strings.Split(path, "/") {
			if p == "" || p == "." || p == ".." {
				return errors.New("r1 invalid path")
			}
		}
	}
	return nil
}
func endpoint(ctx context.Context, address string) (*net.UnixConn, error) {
	c, e := (&net.Dialer{Timeout: 3 * time.Second}).DialContext(ctx, "unix", address)
	if e != nil {
		return nil, e
	}
	u, ok := c.(*net.UnixConn)
	if !ok {
		c.Close()
		return nil, errors.New("r1 unix required")
	}
	d := time.Now().Add(8 * time.Second)
	if limit, ok := ctx.Deadline(); ok && limit.Before(d) {
		d = limit
	}
	_ = u.SetDeadline(d)
	return u, nil
}
func readLine(c *net.UnixConn) ([]byte, error) {
	result, e := bufio.NewReader(io.LimitReader(c, responseLimit+1)).ReadBytes('\n')
	if e != nil || len(result) > responseLimit {
		return nil, errors.New("r1 incomplete response")
	}
	return result, nil
}
func receiveGrant(ctx context.Context, address string) (grant, error) {
	var g grant
	c, e := endpoint(ctx, address)
	if e != nil {
		return g, e
	}
	defer c.Close()
	line, e := readLine(c)
	if e != nil {
		return g, e
	}
	d := json.NewDecoder(bytes.NewReader(line))
	d.DisallowUnknownFields()
	if d.Decode(&g) != nil || d.Decode(new(any)) != io.EOF || g.Version != 1 || len(g.Token) != 64 || !time.Now().Before(g.ExpiresAt) || g.ExpiresAt.After(time.Now().Add(5*time.Minute+time.Second)) {
		return grant{}, errors.New("r1 grant not approved")
	}
	for _, ch := range g.Token {
		if !((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')) {
			return grant{}, errors.New("r1 invalid token")
		}
	}
	return g, nil
}
func readOnce(ctx context.Context, addr string, g grant, op, remote, path string) (json.RawMessage, error) {
	var out response
	c, e := endpoint(ctx, addr)
	if e != nil {
		return nil, e
	}
	defer c.Close()
	req, e := json.Marshal(request{1, g.Token, op, remote, path})
	if e != nil {
		return nil, e
	}
	if len(req) > 16<<10 {
		return nil, errors.New("r1 oversized request")
	}
	if _, e = c.Write(req); e != nil {
		return nil, e
	}
	if e = c.CloseWrite(); e != nil {
		return nil, e
	}
	line, e := readLine(c)
	if e != nil {
		return nil, e
	}
	d := json.NewDecoder(bytes.NewReader(line))
	d.DisallowUnknownFields()
	if d.Decode(&out) != nil || d.Decode(new(any)) != io.EOF || out.Version != 1 || !out.OK || out.Error != "" || !json.Valid(out.Result) {
		return nil, errors.New("r1 remote read denied")
	}
	return out.Result, nil
}

// readVia keeps the production socket endpoints fixed while allowing an
// in-process gateway fixture to exercise the *whole* grant->read transaction.
// The only exported entry point (Read) always uses the constant Skybind R1
// abstract sockets, and never tries an unmanaged native-rclone fallback.
func readVia(ctx context.Context, grantAddress, readAddress, op, remote, path string) (json.RawMessage, error) {
	if e := validateArgs(op, remote, path); e != nil {
		return nil, e
	}
	// A chrootctl process must be alive before the operator can pin its PID.
	// Retry the unprivileged handoff for at most the caller's deadline; each
	// failed attempt is an independently denied socket, never implicit access.
	var g grant
	var e error
	for {
		g, e = receiveGrant(ctx, grantAddress)
		if e == nil {
			break
		}
		select {
		case <-ctx.Done():
			return nil, fmt.Errorf("r1 grant unavailable: %w", ctx.Err())
		case <-time.After(500 * time.Millisecond):
		}
	}
	return readOnce(ctx, readAddress, g, op, remote, path)
}

// Read is the strictly read-only, operator-approved Skybind R1 interface.
// Future streaming/mutation protocols must not be silently routed here.
func Read(ctx context.Context, op, remote, path string) (json.RawMessage, error) {
	return readVia(ctx, grantEndpoint, readEndpoint, op, remote, path)
}
