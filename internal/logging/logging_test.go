package logging

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

type loggingFixture struct {
	Logging struct {
		LoggerName          string `json:"loggerName"`
		LoggerLevel         string `json:"loggerLevel"`
		Propagate           bool   `json:"propagate"`
		VerboseConsoleLevel string `json:"verboseConsoleLevel"`
		Handlers            []struct {
			Type   string `json:"type"`
			Level  string `json:"level"`
			Format string `json:"format"`
		} `json:"handlers"`
	} `json:"logging"`
}

func loggingFixturePath(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", "migration", "contracts", "v1", "foundations.json"))
}

func TestLoggingContractAndFiltering(t *testing.T) {
	data, err := os.ReadFile(loggingFixturePath(t))
	if err != nil {
		t.Fatal(err)
	}
	var fixture loggingFixture
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	if fixture.Logging.LoggerName != LoggerName || fixture.Logging.LoggerLevel != LoggerLevel || fixture.Logging.Propagate {
		t.Fatalf("logger contract drift: %#v", fixture.Logging)
	}
	if len(fixture.Logging.Handlers) != 2 || fixture.Logging.Handlers[0].Level != ConsoleLevel || fixture.Logging.Handlers[1].Level != FileLevel {
		t.Fatalf("handler levels drift: %#v", fixture.Logging.Handlers)
	}
	if fixture.Logging.Handlers[0].Format != PythonFormat || fixture.Logging.VerboseConsoleLevel != VerboseConsole {
		t.Fatalf("formatter/verbose contract drift")
	}

	var console bytes.Buffer
	path := filepath.Join(t.TempDir(), "chrootctl.log")
	fixed := time.Date(2026, 8, 28, 22, 30, 45, 123_000_000, time.Local)
	logger := Configure(path, false, WithConsole(&console), WithClock(func() time.Time { return fixed }))
	logger.Debug("hidden console debug")
	logger.Info("hello")
	if err := logger.Close(); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(console.String(), "hidden console debug") || !strings.Contains(console.String(), "2026-08-28 22:30:45,123 INFO chrootctl: hello") {
		t.Fatalf("console output = %q", console.String())
	}
	fileData, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(fileData), "DEBUG chrootctl: hidden console debug") || !strings.Contains(string(fileData), "INFO chrootctl: hello") {
		t.Fatalf("file output = %q", fileData)
	}
}

func TestFileFailureFallsBackToConsole(t *testing.T) {
	var console bytes.Buffer
	logPath := filepath.Join(t.TempDir(), "chrootctl.log")
	logger := Configure(logPath, false,
		WithConsole(&console),
		WithFileOpener(func(string) (io.WriteCloser, error) { return nil, errors.New("boom") }),
	)
	defer logger.Close()
	if !strings.Contains(console.String(), "WARNING chrootctl: File logging disabled for "+logPath+": boom") {
		t.Fatalf("fallback warning = %q", console.String())
	}
}
