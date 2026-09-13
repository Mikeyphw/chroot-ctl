package services

import (
	"bytes"
	"context"
	"errors"
	"testing"
)

func TestCHR05TransferControlCancelsCopyBeforeMutation(t *testing.T) {
	var dst bytes.Buffer
	control := TransferControl{Cancelled: func() bool { return true }}
	_, err := copyWithControl(context.Background(), control, &dst, bytes.NewBufferString("payload"))
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("err=%v", err)
	}
	if dst.Len() != 0 {
		t.Fatalf("cancelled copy wrote %d bytes", dst.Len())
	}
}

func TestCHR05TransferProgressFailsClosedOnCancellation(t *testing.T) {
	called := false
	control := TransferControl{
		Cancelled: func() bool { return true },
		Progress:  func(any) error { called = true; return nil },
	}
	if err := control.emit(context.Background(), "extract", 50, "extracting"); !errors.Is(err, context.Canceled) {
		t.Fatalf("err=%v", err)
	}
	if called {
		t.Fatal("progress callback ran after cancellation")
	}
}
