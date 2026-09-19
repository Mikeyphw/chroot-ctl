package zstd

import (
	"bytes"
	"io"
	"testing"
)

func TestBundledDecoderHelloWorldFrame(t *testing.T) {
	compressed := []byte("\x28\xb5\x2f\xfd\x24\x0d\x69\x00\x00\x68\x65\x6c\x6c\x6f\x2c\x20\x77\x6f\x72\x6c\x64\x0a\x4c\x1f\xf9\xf1")
	got, err := io.ReadAll(NewReader(bytes.NewReader(compressed)))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "hello, world\n" {
		t.Fatalf("decoded content = %q", got)
	}
}
