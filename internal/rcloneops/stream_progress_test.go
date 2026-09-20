package rcloneops

import (
	"encoding/json"
	"testing"
)

func TestProgressFromStatsCarriesRateETAAndObject(t *testing.T) {
	stats := statsDocument{
		Bytes:          8 * 1024,
		TotalBytes:     16 * 1024,
		Transfers:      1,
		TotalTransfers: 1,
		Speed:          4096.4,
		ETA:            json.RawMessage(`12.4`),
		Transferring:   []transferDocument{{Name: "chroots/androidos.tar.zst"}},
	}
	got := progressFromStats(stats, "fallback.tar.zst")
	if got.RateBytesPerSecond != 4096 || got.ETASeconds != 12 || got.CurrentObject != "chroots/androidos.tar.zst" {
		t.Fatalf("unexpected rich progress: %+v", got)
	}
}

func TestProgressFromStatsFallsBackToTransferDetailAndObject(t *testing.T) {
	stats := statsDocument{
		Bytes:      1,
		TotalBytes: 2,
		Transferring: []transferDocument{{
			Name:  "",
			Speed: 2048,
			ETA:   json.RawMessage(`"1m2s"`),
		}},
	}
	got := progressFromStats(stats, "androidos.tar.zst")
	if got.RateBytesPerSecond != 0 || got.ETASeconds != -1 || got.CurrentObject != "androidos.tar.zst" {
		t.Fatalf("unexpected fallback progress: %+v", got)
	}

	stats.Transferring[0].Name = "androidos.tar.zst"
	got = progressFromStats(stats, "fallback")
	if got.RateBytesPerSecond != 2048 || got.ETASeconds != 62 || got.CurrentObject != "androidos.tar.zst" {
		t.Fatalf("unexpected transfer progress: %+v", got)
	}
}
