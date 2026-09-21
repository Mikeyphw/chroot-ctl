package logging

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"chrootctl/internal/redaction"
)

const (
	LoggerName      = "chrootctl"
	PythonFormat    = "%(asctime)s %(levelname)s %(name)s: %(message)s"
	LoggerLevel     = "DEBUG"
	FileLevel       = "DEBUG"
	ConsoleLevel    = "INFO"
	VerboseConsole  = "DEBUG"
	MaxLogFileBytes = 4 * 1024 * 1024
	MaxLogBackups   = 5
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

// ConfigureReadOnly creates a console-only logger without touching log paths.
func ConfigureReadOnly(verbose bool, options ...Option) *Logger {
	cfg := settings{console: os.Stderr, now: time.Now, open: func(string) (io.WriteCloser, error) { return nil, os.ErrPermission }}
	for _, option := range options {
		option(&cfg)
	}
	level := Info
	if verbose {
		level = Debug
	}
	return &Logger{console: cfg.console, consoleLevel: level, now: cfg.now}
}

func Configure(logFile string, verbose bool, options ...Option) *Logger {
	cfg := settings{
		console: os.Stderr,
		now:     time.Now,
		open: func(path string) (io.WriteCloser, error) {
			return OpenRotatingFile(path, MaxLogFileBytes, MaxLogBackups)
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
		if err := os.MkdirAll(parent, 0o700); err != nil {
			logger.Warningf("File logging disabled for %s: %v", logFile, err)
			return logger
		}
		_ = os.Chmod(parent, 0o700)
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

type rotatingFile struct {
	path     string
	maxBytes int64
	backups  int
	file     *os.File
	size     int64
}

func OpenRotatingFile(path string, maxBytes int64, backups int) (io.WriteCloser, error) {
	if path == "" {
		return nil, fmt.Errorf("log path is empty")
	}
	if backups < 1 {
		backups = 1
	}
	if err := RotateFileIfNeeded(path, maxBytes, backups); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	_ = os.Chmod(path, 0o600)
	st, err := f.Stat()
	if err != nil {
		f.Close()
		return nil, err
	}
	return &rotatingFile{path: path, maxBytes: maxBytes, backups: backups, file: f, size: st.Size()}, nil
}
func (r *rotatingFile) Write(p []byte) (int, error) {
	if r.file == nil {
		return 0, os.ErrClosed
	}
	if r.maxBytes > 0 && r.size > 0 && r.size+int64(len(p)) > r.maxBytes {
		if err := r.rotate(); err != nil {
			return 0, err
		}
	}
	n, err := r.file.Write(p)
	r.size += int64(n)
	return n, err
}
func (r *rotatingFile) Close() error {
	if r.file == nil {
		return nil
	}
	err := r.file.Close()
	r.file = nil
	return err
}
func (r *rotatingFile) rotate() error {
	if r.file != nil {
		if err := r.file.Close(); err != nil {
			return err
		}
		r.file = nil
	}
	if err := rotateNow(r.path, r.backups); err != nil {
		return err
	}
	f, err := os.OpenFile(r.path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	r.file = f
	r.size = 0
	return nil
}
func RotateFileIfNeeded(path string, maxBytes int64, backups int) error {
	if path == "" || maxBytes <= 0 {
		return nil
	}
	st, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	if st.Mode()&os.ModeSymlink != 0 || !st.Mode().IsRegular() {
		return fmt.Errorf("unsafe log file: %s", path)
	}
	if st.Size() <= maxBytes {
		return nil
	}
	if backups < 1 {
		backups = 1
	}
	return rotateNow(path, backups)
}
func rotateNow(path string, backups int) error {
	for i := backups; i >= 1; i-- {
		dst := fmt.Sprintf("%s.%d", path, i)
		if i == backups {
			_ = os.Remove(dst)
		}
		src := path
		if i > 1 {
			src = fmt.Sprintf("%s.%d", path, i-1)
		}
		if _, err := os.Lstat(src); err == nil {
			if err := os.Rename(src, dst); err != nil {
				return err
			}
		} else if !os.IsNotExist(err) {
			return err
		}
	}
	return nil
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
	message = redaction.String(message)
	line := fmt.Sprintf("%s %s %s: %s\n", logger.now().Format("2006-01-02 15:04:05,000"), level.String(), LoggerName, message)
	if logger.console != nil && level >= logger.consoleLevel {
		_, _ = io.WriteString(logger.console, line)
	}
	if logger.file != nil && level >= Debug {
		_, _ = io.WriteString(logger.file, line)
	}
}
