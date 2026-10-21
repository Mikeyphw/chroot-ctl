package skybindr1

import (
	"context"
	"encoding/json"
	"net"
	"strings"
	"testing"
	"time"
)

func TestReadContractAndUnsafeRequestDenial(t *testing.T) {
	for _, tc := range []struct{ op, remote, path string }{
		{"rclone.rcat", "drive", "safe"}, {"rclone.moveto", "drive", "safe"}, {"rclone.lsjson", "drive", "../private"},
		{"rclone.lsjson", "drive", "/root"}, {"rclone.lsjson", "drive", "x:y"}, {"rclone.lsjson", "", "x"},
	} {
		if validateArgs(tc.op, tc.remote, tc.path) == nil {
			t.Fatalf("accepted unsafe request: %#v", tc)
		}
	}
	if validateArgs("rclone.lsjson", "drive", "safe/subdir") != nil {
		t.Fatal("valid read denied")
	}
}
func TestGrantReaderRejectsExpiredForgedAndMalformed(t *testing.T) {
	for _, tc := range []struct{ name, reply string }{
		{"expired", `{"version":1,"token":"` + strings.Repeat("a", 64) + `","expires_at":"2000-01-01T00:00:00Z"}`},
		{"forged token", `{"version":1,"token":"` + strings.Repeat("Z", 64) + `","expires_at":"2099-01-01T00:00:00Z"}`},
		{"unknown", `{"version":1,"token":"` + strings.Repeat("a", 64) + `","expires_at":"2099-01-01T00:00:00Z","scope":"evil"}`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			addr := "\x00chrootctl-r1-grant-test-" + tc.name
			l, e := net.Listen("unix", addr)
			if e != nil {
				t.Fatal(e)
			}
			defer l.Close()
			go func() {
				c, e := l.Accept()
				if e == nil {
					_, _ = c.Write([]byte(tc.reply + "\n"))
					_ = c.Close()
				}
			}()
			if _, e := receiveGrant(context.Background(), addr); e == nil {
				t.Fatal("forged grant accepted")
			}
		})
	}
}
func TestValidGrantAndReadOnlyReply(t *testing.T) {
	addr := "\x00chrootctl-r1-grant-valid"
	l, e := net.Listen("unix", addr)
	if e != nil {
		t.Fatal(e)
	}
	defer l.Close()
	expiration := time.Now().Add(time.Minute).UTC().Format(time.RFC3339Nano)
	go func() {
		c, e := l.Accept()
		if e == nil {
			reply, _ := json.Marshal(map[string]any{"version": 1, "token": strings.Repeat("b", 64), "expires_at": expiration})
			_, _ = c.Write(append(reply, '\n'))
			_ = c.Close()
		}
	}()
	g, e := receiveGrant(context.Background(), addr)
	if e != nil || len(g.Token) != 64 {
		t.Fatal(e)
	}
	endpoint := "\x00chrootctl-r1-read-valid"
	reader, e := net.Listen("unix", endpoint)
	if e != nil {
		t.Fatal(e)
	}
	defer reader.Close()
	go func() {
		c, e := reader.Accept()
		if e != nil {
			return
		}
		defer c.Close()
		buf := make([]byte, 2048)
		_, _ = c.Read(buf)
		_, _ = c.Write([]byte(`{"version":1,"ok":true,"result":{"bytes":4}}` + "\n"))
	}()
	result, e := readOnce(context.Background(), endpoint, g, "rclone.size", "drive", "safe")
	if e != nil || !json.Valid(result) {
		t.Fatalf("valid read failed: %s %v", result, e)
	}
}
