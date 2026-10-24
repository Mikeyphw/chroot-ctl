package skybindr1

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"strings"
	"testing"
	"time"
)

func consumerListener(t *testing.T, suffix string) (string, *net.UnixListener) {
	t.Helper()
	// Test-only abstract address; never replaces the hard-coded production R1 sockets.
	addr := fmt.Sprintf("\x00chrootctl-cc08-%s-%d", suffix, time.Now().UnixNano())
	l, err := net.Listen("unix", addr)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = l.Close() })
	return addr, l.(*net.UnixListener)
}

func TestCC08RealWireContractGrantedReadOnly(t *testing.T) {
	handoff, grants := consumerListener(t, "handoff")
	gateway, reads := consumerListener(t, "gateway")
	token := strings.Repeat("a", 64)
	requests := make(chan request, 1)
	go func() {
		conn, err := grants.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		_, _ = fmt.Fprintf(conn, `{"version":1,"token":"%s","expires_at":"%s"}`+"\n", token, time.Now().Add(time.Minute).UTC().Format(time.RFC3339Nano))
	}()
	go func() {
		conn, err := reads.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		var req request
		_ = json.NewDecoder(bufio.NewReader(conn)).Decode(&req)
		requests <- req
		_, _ = conn.Write([]byte(`{"version":1,"ok":true,"result":{"bytes":4}}` + "\n"))
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	result, err := readVia(ctx, handoff, gateway, "rclone.size", "drive", "safe/prefix")
	if err != nil || string(result) != `{"bytes":4}` {
		t.Fatalf("valid granted read failed: %s %v", result, err)
	}
	select {
	case req := <-requests:
		if req.Version != 1 || req.Token != token || req.Operation != "rclone.size" || req.Remote != "drive" || req.Path != "safe/prefix" {
			t.Fatalf("wire request mismatch: %#v", req)
		}
	case <-ctx.Done():
		t.Fatal("missing request")
	}
}

func TestCC08MutationRejectedBeforeAnyNetworkOrNativeFallback(t *testing.T) {
	// If the request were sent the gateway would be contacted. Rejection here
	// must happen *before* endpoint access for both module editions.
	for _, op := range []string{"rclone.rcat", "rclone.cat", "rclone.moveto", "rclone.deletefile", "rclone.copy", "rclone.sync", "rclone.serve"} {
		ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
		_, err := readVia(ctx, "\x00cc08-never-listening-handoff", "\x00cc08-never-listening-gateway", op, "drive", "a")
		cancel()
		if err == nil || !strings.Contains(err.Error(), "unsafe read scope") {
			t.Fatalf("operation %q not locally rejected: %v", op, err)
		}
	}
}

func TestCC08DeniedGatewayCannotBecomeSuccessfulRead(t *testing.T) {
	handoff, grants := consumerListener(t, "denied-grant")
	gateway, reads := consumerListener(t, "denied-read")
	go func() {
		conn, err := grants.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		_, _ = fmt.Fprintf(conn, `{"version":1,"token":"%s","expires_at":"%s"}`+"\n", strings.Repeat("c", 64), time.Now().Add(time.Minute).UTC().Format(time.RFC3339Nano))
	}()
	go func() {
		conn, err := reads.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		_, _ = bufio.NewReader(conn).ReadBytes('}')
		_, _ = conn.Write([]byte(`{"version":1,"ok":false,"error":"forbidden"}` + "\n"))
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if result, err := readVia(ctx, handoff, gateway, "rclone.lsjson", "drive", "safe"); err == nil || result != nil {
		t.Fatalf("denied gateway treated as usable: %q %v", result, err)
	}
}

func TestCC08CancelledGrantRequestDoesNotInventCredentials(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	result, err := readVia(ctx, "\x00cc08-not-a-grant", "\x00cc08-not-a-gateway", "rclone.size", "drive", "safe")
	if err == nil || result != nil {
		t.Fatalf("cancelled request succeeded: %q %v", result, err)
	}
}
