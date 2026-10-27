package skybindfeature

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
)

func TestAPI03CapabilitiesAndNarrowCalls(t *testing.T) {
	called := 0
	runner := func(ctx context.Context, args []string, stdin []byte) ([]byte, error) {
		called++
		if len(args) == 1 && args[0] == "capabilities" {
			return []byte(`{"schema_version":1,"request_id":"feature-capabilities-v1","ok":true,"result":{"api_version":1,"operations":[]}}`), nil
		}
		if len(args) != 3 || args[1] != "mount.status" {
			t.Fatalf("unexpected argv: %v", args)
		}
		if !strings.Contains(string(stdin), `"request_id":"mine"`) {
			t.Fatal("stdin changed")
		}
		return []byte(`{"schema_version":1,"request_id":"mine","ok":true,"result":{"status":"STOPPED"}}`), nil
	}
	for _, item := range []struct {
		args []string
		in   string
	}{
		{[]string{"capabilities"}, ""},
		{[]string{"call", "mount.status", "--stdin"}, `{"api_version":1,"request_id":"mine","arguments":{"name":"test"}}`},
	} {
		res, err := Call(context.Background(), item.args, strings.NewReader(item.in), runner)
		if err != nil || !strings.Contains(string(res), `"ok":true`) {
			t.Fatalf("%s: %v", res, err)
		}
	}
	if called != 2 {
		t.Fatal(called)
	}
}
func TestAPI03DeniesShellVersionMutationAndForgedReply(t *testing.T) {
	called := 0
	runner := func(_ context.Context, _ []string, _ []byte) ([]byte, error) {
		called++
		return []byte(`{"schema_version":1,"request_id":"other","ok":true,"result":{}}`), nil
	}
	for _, item := range []struct {
		args []string
		in   string
	}{
		{[]string{"call", "shell.exec", "--stdin"}, `{"api_version":1,"request_id":"x","arguments":{}}`},
		{[]string{"call", "mount.start", "--stdin"}, `{"api_version":2,"request_id":"x","arguments":{}}`},
		{[]string{"call", "mount.start", "--stdin"}, `{"api_version":1,"request_id":"bad/id","arguments":{}}`},
		{[]string{"call", "mount.start", "--stdin"}, `{"api_version":1,"request_id":"mine","operation":"mount.stop","arguments":{}}`},
		{[]string{"call", "mount.start", "--stdin"}, `{"api_version":1,"request_id":"mine","arguments":[]}`},
		{[]string{"call", "mount.start", "--stdin", "--token"}, `{"api_version":1,"request_id":"mine","arguments":{}}`},
	} {
		if _, err := Call(context.Background(), item.args, strings.NewReader(item.in), runner); err == nil {
			t.Fatalf("accepted: %v", item.args)
		}
	}
	if called != 0 {
		t.Fatalf("executed malformed requests: %d", called)
	}
	if _, err := Call(context.Background(), []string{"call", "mount.start", "--stdin"}, strings.NewReader(`{"api_version":1,"request_id":"mine","arguments":{}}`), runner); err == nil {
		t.Fatal("forged response accepted")
	}
}
func TestAPI03FailClosedOnExecutionErrorAndLargeResponse(t *testing.T) {
	req := `{"api_version":1,"request_id":"mine","arguments":{}}`
	base := []string{"call", "namespace.apply", "--stdin"}
	runners := []Runner{
		func(context.Context, []string, []byte) ([]byte, error) {
			return []byte(`{"schema_version":1,"request_id":"mine","ok":false,"error":{"code":"denied"}}`), errors.New("failure")
		},
		func(context.Context, []string, []byte) ([]byte, error) {
			return []byte(strings.Repeat("z", MaxResponse+1)), nil
		},
		func(context.Context, []string, []byte) ([]byte, error) {
			return []byte(fmt.Sprintf(`{"schema_version":1,"request_id":"mine","ok":true,"result":{},"extra":1}`)), nil
		},
	}
	for _, runner := range runners {
		if _, err := Call(context.Background(), base, strings.NewReader(req), runner); err == nil {
			t.Fatal("unsafe response accepted")
		}
	}
}

func TestAPI03DeniedReceiptPreservedForReconcile(t *testing.T) {
	runner := func(context.Context, []string, []byte) ([]byte, error) {
		return []byte(`{"schema_version":1,"request_id":"lost_reply_1","ok":false,"error":{"code":"duplicate_request","category":"policy","stage":"admission","message":"duplicate_request","retryable":false}}`), errors.New("exit 1")
	}
	body := `{"api_version":1,"request_id":"lost_reply_1","arguments":{"name":"Demo"}}`
	out, err := Call(context.Background(), []string{"call", "mount.stop", "--stdin"}, strings.NewReader(body), runner)
	if !errors.Is(err, ErrDenied) || !strings.Contains(string(out), `"request_id":"lost_reply_1"`) || !strings.Contains(string(out), "duplicate_request") {
		t.Fatalf("receipt lost: %q: %v", out, err)
	}
}

// These cases were previously forwarded to Skybind or mislabeled as durable
// negative receipts by the consumer. Do not weaken either validation gate.
func TestAPI03RejectAmbiguousProofAndIncompleteDenial(t *testing.T) {
	invoked := 0
	runner := func(context.Context, []string, []byte) ([]byte, error) {
		invoked++
		return []byte(`{"schema_version":1,"request_id":"mine","ok":true,"result":{}}`), nil
	}
	inputs := []string{
		`{"api_version":1,"request_id":"mine","request_id":"other","arguments":{}}`,
		`{"api_version":1,"request_id":"mine","arguments":{"proof":"a","proof":"b"}}`,
		`{"api_version":1,"request_id":"mine","arguments":{"nested":{"name":"one","name":"two"}}}`,
		`{"api_version":1,"request_id":"mine","arguments":{"nested":[{"name":"one","name":"two"}]}}`,
	}
	for _, raw := range inputs {
		if _, err := Call(context.Background(), []string{"call", "mount.start", "--stdin"}, strings.NewReader(raw), runner); err == nil {
			t.Fatalf("ambiguous mutation accepted: %s", raw)
		}
	}
	if invoked != 0 {
		t.Fatalf("invalid input reached Skybind: %d", invoked)
	}
	request := `{"api_version":1,"request_id":"mine","arguments":{}}`
	incomplete := []string{
		`{"schema_version":1,"request_id":"mine","error":{"code":"x","category":"policy","stage":"admission","message":"x","retryable":false}}`,
		`{"schema_version":1,"request_id":"mine","ok":false}`,
		`{"schema_version":1,"request_id":"mine","ok":false,"error":{}}`,
		`{"schema_version":1,"request_id":"mine","ok":false,"error":{"code":"blocked"}}`,
		`{"schema_version":1,"request_id":"mine","ok":false,"error":{"code":"x","category":"policy","stage":"admission","message":"x","retryable":false},"result":{}}`,
		`{"schema_version":1,"request_id":"mine","ok":false,"error":{"code":"x","code":"y","category":"policy","stage":"admission","message":"x","retryable":false}}`,
		`{"schema_version":1,"request_id":"mine","ok":true,"result":{},"result":{}}`,
	}
	for _, raw := range incomplete {
		callback := func(context.Context, []string, []byte) ([]byte, error) { return []byte(raw), errors.New("exit 1") }
		out, err := Call(context.Background(), []string{"call", "mount.stop", "--stdin"}, strings.NewReader(request), callback)
		if err == nil || errors.Is(err, ErrDenied) || len(out) != 0 {
			t.Fatalf("untrusted receipt was preserved: %q %v", out, err)
		}
	}
	// A complete negative receipt must still round-trip on stdout.
	good := func(context.Context, []string, []byte) ([]byte, error) {
		return []byte(`{"schema_version":1,"request_id":"mine","ok":false,"error":{"code":"duplicate_request","category":"policy","stage":"admission","message":"duplicate_request","retryable":false}}`), errors.New("exit 1")
	}
	out, err := Call(context.Background(), []string{"call", "mount.stop", "--stdin"}, strings.NewReader(request), good)
	if !errors.Is(err, ErrDenied) || !strings.Contains(string(out), "duplicate_request") {
		t.Fatalf("valid denial lost: %q %v", out, err)
	}
	fieldFailure := func(context.Context, []string, []byte) ([]byte, error) {
		return []byte(`{"schema_version":1,"request_id":"mine","ok":false,"error":{"code":"invalid_field","category":"validation","stage":"admission","message":"invalid_field","retryable":false,"field_errors":[{"index":1,"field":"name","code":"invalid"}]}}`), errors.New("exit 1")
	}
	out, err = Call(context.Background(), []string{"call", "mount.stop", "--stdin"}, strings.NewReader(request), fieldFailure)
	if !errors.Is(err, ErrDenied) || !strings.Contains(string(out), "field_errors") {
		t.Fatalf("valid field-level denial lost: %q %v", out, err)
	}

}
