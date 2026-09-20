package services

import (
	"context"
	"strings"

	"chrootctl/internal/rcloneops"
)

func rcloneProgressPercent(progress rcloneops.Progress, start, end int) int {
	if end < start {
		end = start
	}
	if progress.BytesTotal <= 0 || progress.BytesDone < 0 {
		return start
	}
	span := end - start
	if span <= 0 {
		return start
	}
	done := progress.BytesDone
	if done > progress.BytesTotal {
		done = progress.BytesTotal
	}
	return start + int((done*int64(span))/progress.BytesTotal)
}

func rcloneProgressDetail(progress rcloneops.Progress, fallbackObject string) map[string]any {
	current := strings.TrimSpace(progress.CurrentObject)
	if current == "" {
		current = strings.TrimSpace(fallbackObject)
	}
	detail := map[string]any{
		"live":        true,
		"bytes_done":  progress.BytesDone,
		"bytes_total": progress.BytesTotal,
		"files_done":  progress.FilesDone,
		"files_total": progress.FilesTotal,
	}
	if progress.RateBytesPerSecond > 0 {
		detail["rate_bytes_per_second"] = progress.RateBytesPerSecond
	}
	if progress.ETASeconds >= 0 {
		detail["eta_seconds"] = progress.ETASeconds
	}
	if current != "" {
		detail["current_object"] = current
		detail["current_path"] = current
	}
	return detail
}

func emitRcloneProgress(ctx context.Context, control TransferControl, phase string, start, end int, message, fallbackObject string, progress rcloneops.Progress) {
	_ = control.emitDetail(ctx, phase, rcloneProgressPercent(progress, start, end), message, rcloneProgressDetail(progress, fallbackObject))
}
