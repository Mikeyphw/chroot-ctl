package logging

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const (
	LoggerName     = "chrootctl"
	PythonFormat   = "%(asctime)s %(levelname)s %(name)s: %(message)s"
	LoggerLevel    = "DEBUG"
	FileLevel      = "DEBUG"
	ConsoleLevel   = "INFO"
	VerboseConsole = "DEBUG"
)

type Level int

const (
	Debug Level = iota
	Info
	Warning
	Error
)

func (level Level) String() string {
	switch level {
	case Debug:
		return "DEBUG"
	case Info:
		return "INFO"
	case Warning:
		return "WARNING"
	case Error:
		return "ERROR"
	default:
		return "INFO"
	}
}

type Logger struct {
	mu           sync.Mutex
	console      io.Writer
	file         io.WriteCloser
	consoleLevel Level
	now          func() time.Time
}

type settings struct {
	console io.Writer
	now     func() time.Time
	open    func(string) (io.WriteCloser, error)
}

type Option func(*settings)

func WithConsole(writer io.Writer) Option {
	return func(settings *settings) { settings.console = writer }
}

func WithClock(clock func() time.Time) Option {
	return func(settings *settings) { settings.now = clock }
}

func WithFileOpener(opener func(string) (io.WriteCloser, error)) Option {
	return func(settings *settings) { settings.open = opener }
}

func Configure(logFile string, verbose bool, options ...Option) *Logger {
	cfg := settings{
		console: os.Stderr,
		now:     time.Now,
		open: func(path string) (io.WriteCloser, error) {
			return os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		},
	}
	for _, option := range options {
		option(&cfg)
	}
	level := Info
	if verbose {
		level = Debug
	}
	logger := &Logger{console: cfg.console, consoleLevel: level, now: cfg.now}

	if parent := filepath.Dir(logFile); parent != "." && parent != "" {
		if err := os.MkdirAll(parent, 0o755); err != nil {
			logger.Warningf("File logging disabled for %s: %v", logFile, err)
			return logger
		}
	}
	file, err := cfg.open(logFile)
	if err != nil {
		logger.Warningf("File logging disabled for %s: %v", logFile, err)
		return logger
	}
	logger.file = file
	return logger
}

func (logger *Logger) Close() error {
	logger.mu.Lock()
	defer logger.mu.Unlock()
	if logger.file == nil {
		return nil
	}
	err := logger.file.Close()
	logger.file = nil
	return err
}

func (logger *Logger) Debugf(format string, args ...any)   { logger.logf(Debug, format, args...) }
func (logger *Logger) Infof(format string, args ...any)    { logger.logf(Info, format, args...) }
func (logger *Logger) Warningf(format string, args ...any) { logger.logf(Warning, format, args...) }
func (logger *Logger) Errorf(format string, args ...any)   { logger.logf(Error, format, args...) }

func (logger *Logger) Debug(message string)   { logger.logf(Debug, "%s", message) }
func (logger *Logger) Info(message string)    { logger.logf(Info, "%s", message) }
func (logger *Logger) Warning(message string) { logger.logf(Warning, "%s", message) }
func (logger *Logger) Error(message string)   { logger.logf(Error, "%s", message) }

func (logger *Logger) logf(level Level, format string, args ...any) {
	logger.mu.Lock()
	defer logger.mu.Unlock()
	message := fmt.Sprintf(format, args...)
	message = strings.TrimSuffix(message, "\n")
	line := fmt.Sprintf("%s %s %s: %s\n", logger.now().Format("2006-01-02 15:04:05,000"), level.String(), LoggerName, message)
	if logger.console != nil && level >= logger.consoleLevel {
		_, _ = io.WriteString(logger.console, line)
	}
	if logger.file != nil && level >= Debug {
		_, _ = io.WriteString(logger.file, line)
	}
}
