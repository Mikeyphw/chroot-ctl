package services

import "testing"

func TestCHR16LogSeverityThresholds(t *testing.T) {
	if logSeverityValue("DEBUG") >= logSeverityValue("INFO") || logSeverityValue("ERROR") <= logSeverityValue("WARNING") {
		t.Fatal("severity ordering is not a threshold")
	}
	if got := logLineSeverity("2026-01-01 00:00:00,000 ERROR chrootctl: failed"); got != "ERROR" {
		t.Fatalf("level=%q", got)
	}
	if !validLogLevel("CRITICAL") || validLogLevel("TRACE") {
		t.Fatal("log level validation mismatch")
	}
}
