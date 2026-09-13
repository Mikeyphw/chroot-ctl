package mutation

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

type BlockedError struct{ LockKey, BlockingOperationID string }

func (e BlockedError) Error() string {
	suffix := ""
	if e.BlockingOperationID != "" {
		suffix = " by operation " + e.BlockingOperationID
	}
	return fmt.Sprintf("operation lock %q is already held%s", e.LockKey, suffix)
}

type heldKey struct{}
type heldLocks map[string]bool // true means exclusive, false means shared

func withHeldMode(ctx context.Context, key string, exclusive bool) context.Context {
	current, _ := ctx.Value(heldKey{}).(heldLocks)
	next := heldLocks{}
	for k, v := range current {
		next[k] = v
	}
	if key != "" {
		if existing, ok := next[key]; !ok || exclusive || !existing {
			next[key] = exclusive
		}
	}
	return context.WithValue(ctx, heldKey{}, next)
}
func heldMode(ctx context.Context, key string) (exclusive bool, ok bool) {
	m, _ := ctx.Value(heldKey{}).(heldLocks)
	exclusive, ok = m[key]
	return exclusive, ok
}

func safeKey(v string) string {
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

type fileLock struct {
	path, id string
	shared   bool
	file     *os.File
}

func newFileLock(dir, key, id string, shared bool) *fileLock {
	return &fileLock{path: filepath.Join(dir, safeKey(key)+".lock"), id: id, shared: shared}
}
func (l *fileLock) acquire() error {
	if err := os.MkdirAll(filepath.Dir(l.path), 0755); err != nil {
		return err
	}
	f, err := os.OpenFile(l.path, os.O_CREATE|os.O_RDWR, 0644)
	if err != nil {
		return err
	}
	mode := syscall.LOCK_EX | syscall.LOCK_NB
	if l.shared {
		mode = syscall.LOCK_SH | syscall.LOCK_NB
	}
	if err = syscall.Flock(int(f.Fd()), mode); err != nil {
		b, _ := os.ReadFile(l.path)
		_ = f.Close()
		if err == syscall.EWOULDBLOCK || err == syscall.EAGAIN {
			return BlockedError{LockKey: strings.TrimSuffix(filepath.Base(l.path), ".lock"), BlockingOperationID: strings.TrimSpace(string(b))}
		}
		return err
	}
	if !l.shared {
		if err = f.Truncate(0); err == nil {
			_, err = f.Seek(0, 0)
		}
		if err == nil {
			_, err = f.WriteString(l.id)
		}
		if err == nil {
			err = f.Sync()
		}
		if err != nil {
			_ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
			_ = f.Close()
			return err
		}
	}
	l.file = f
	return nil
}
func (l *fileLock) release() error {
	if l == nil || l.file == nil {
		return nil
	}
	if !l.shared {
		_ = l.file.Truncate(0)
		_ = l.file.Sync()
	}
	err := syscall.Flock(int(l.file.Fd()), syscall.LOCK_UN)
	cerr := l.file.Close()
	l.file = nil
	if err != nil {
		return err
	}
	return cerr
}

type Lease struct {
	locks []*fileLock
	Keys  []string
}

func (l *Lease) Release() error {
	var first error
	for i := len(l.locks) - 1; i >= 0; i-- {
		if err := l.locks[i].release(); first == nil && err != nil {
			first = err
		}
	}
	return first
}

func AcquireScope(ctx context.Context, dir, scope, target, id string) (*Lease, context.Context, error) {
	if scope == "" || scope == "none" {
		return &Lease{}, ctx, nil
	}
	if id == "" {
		id = fmt.Sprintf("pid-%d", os.Getpid())
	}
	specs := []struct {
		key    string
		shared bool
	}{}
	switch scope {
	case "global":
		specs = append(specs, struct {
			key    string
			shared bool
		}{"global-mutating", false})
	case "target":
		if strings.TrimSpace(target) == "" {
			return nil, ctx, fmt.Errorf("target-scoped mutation requires target")
		}
		specs = append(specs, struct {
			key    string
			shared bool
		}{"global-mutating", true}, struct {
			key    string
			shared bool
		}{"target-" + target, false})
	default:
		return nil, ctx, fmt.Errorf("unknown mutation lock scope: %s", scope)
	}
	lease := &Lease{}
	lockedCtx := ctx
	for _, s := range specs {
		wantExclusive := !s.shared
		if heldExclusive, ok := heldMode(lockedCtx, s.key); ok {
			if wantExclusive && !heldExclusive {
				_ = lease.Release()
				return nil, ctx, fmt.Errorf("cannot upgrade held shared mutation lock %q to exclusive", s.key)
			}
			lease.Keys = append(lease.Keys, s.key)
			continue
		}
		l := newFileLock(dir, s.key, id, s.shared)
		if err := l.acquire(); err != nil {
			_ = lease.Release()
			return nil, ctx, err
		}
		lease.locks = append(lease.locks, l)
		lease.Keys = append(lease.Keys, s.key)
		lockedCtx = withHeldMode(lockedCtx, s.key, wantExclusive)
	}
	return lease, lockedCtx, nil
}
