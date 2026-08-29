package operations

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

type BlockedError struct{ LockKey, BlockingOperationID string }

func (e BlockedError) Error() string {
	s := ""
	if e.BlockingOperationID != "" {
		s = " by operation " + e.BlockingOperationID
	}
	return fmt.Sprintf("Operation lock %q is already held%s", e.LockKey, s)
}

type Lock struct {
	path, id string
	file     *os.File
}

func SafeLockKey(v string) string {
	var b strings.Builder
	for _, c := range v {
		if c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || strings.ContainsRune("._-", c) {
			b.WriteRune(c)
		} else {
			b.WriteByte('_')
		}
	}
	return b.String()
}
func LockKeyFor(scope string, target *string) (*string, error) {
	switch scope {
	case "none", "":
		return nil, nil
	case "global":
		s := "global-mutating"
		return &s, nil
	case "target":
		if target == nil || *target == "" {
			return nil, fmt.Errorf("target-scoped operation requires a target name")
		}
		s := "target-" + *target
		return &s, nil
	default:
		return nil, fmt.Errorf("unknown lock scope: %s", scope)
	}
}
func NewLock(dir, key, id string) *Lock {
	return &Lock{path: filepath.Join(dir, SafeLockKey(key)+".lock"), id: id}
}
func (l *Lock) Acquire() error {
	if e := os.MkdirAll(filepath.Dir(l.path), 0755); e != nil {
		return e
	}
	f, e := os.OpenFile(l.path, os.O_CREATE|os.O_RDWR, 0644)
	if e != nil {
		return e
	}
	if e = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); e != nil {
		b, _ := os.ReadFile(l.path)
		f.Close()
		if e == syscall.EWOULDBLOCK || e == syscall.EAGAIN {
			return BlockedError{LockKey: strings.TrimSuffix(filepath.Base(l.path), ".lock"), BlockingOperationID: strings.TrimSpace(string(b))}
		}
		return e
	}
	if e = f.Truncate(0); e == nil {
		_, e = f.Seek(0, 0)
	}
	if e == nil {
		_, e = f.WriteString(l.id)
	}
	if e == nil {
		e = f.Sync()
	}
	if e != nil {
		syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
		f.Close()
		return e
	}
	l.file = f
	return nil
}
func (l *Lock) Release() error {
	if l == nil || l.file == nil {
		return nil
	}
	_ = l.file.Truncate(0)
	_ = l.file.Sync()
	e := syscall.Flock(int(l.file.Fd()), syscall.LOCK_UN)
	ce := l.file.Close()
	l.file = nil
	if e != nil {
		return e
	}
	return ce
}
