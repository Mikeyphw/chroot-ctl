package services

import (
	"testing"

	"chrootctl/internal/rcloneops"
)

func TestRcloneProgressDetailCarriesRichTransferFields(t *testing.T) {
	detail := rcloneProgressDetail(rcloneops.Progress{
		BytesDone: 7 << 30, BytesTotal: 9 << 30,
		FilesDone: 1, FilesTotal: 2,
		RateBytesPerSecond: 25 << 20,
		ETASeconds:         99,
		CurrentObject:      "drive:chroots/androidos.tar.zst",
	}, "fallback")
	checks := map[string]any{
		"bytes_done":            int64(7 << 30),
		"bytes_total":           int64(9 << 30),
		"rate_bytes_per_second": int64(25 << 20),
		"eta_seconds":           int64(99),
		"current_object":        "drive:chroots/androidos.tar.zst",
	}
	for key, want := range checks {
		if got := detail[key]; got != want {
			t.Fatalf("%s=%v want %v", key, got, want)
		}
	}
	if got := rcloneProgressPercent(rcloneops.Progress{BytesDone: 3, BytesTotal: 4}, 20, 60); got != 50 {
		t.Fatalf("percent=%d want 50", got)
	}
}
