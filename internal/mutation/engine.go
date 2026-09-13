package mutation

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"chrootctl/internal/registry"
)

var ErrDryRun = errors.New("mutation blocked by dry-run policy")

type Engine struct {
	Registry *registry.Registry
	LocksDir string
	DryRun   bool
	Now      func() time.Time
}

func New(reg *registry.Registry, operationRoot string, dry bool) *Engine {
	return &Engine{Registry: reg, LocksDir: filepath.Join(operationRoot, "locks"), DryRun: dry, Now: time.Now}
}
func (e *Engine) Guard(ctx context.Context, scope, target, label string) (context.Context, func() error, error) {
	if e == nil || e.DryRun {
		return ctx, func() error { return nil }, nil
	}
	id := label + "-" + shortID()
	lease, locked, err := AcquireScope(ctx, e.LocksDir, scope, target, id)
	if err != nil {
		return ctx, nil, err
	}
	return locked, lease.Release, nil
}
func shortID() string {
	b := make([]byte, 6)
	if _, err := rand.Read(b); err == nil {
		return hex.EncodeToString(b)
	}
	return fmt.Sprintf("%x", time.Now().UnixNano())
}

type Spec struct {
	Kind, Target, Source, Destination, Scope string
	Detail                                   map[string]any
}
type Tx struct {
	engine *Engine
	ID     string
	Spec   Spec
	DryRun bool
}

func (e *Engine) Begin(ctx context.Context, s Spec) (*Tx, error) {
	if e == nil {
		return nil, errors.New("mutation engine is nil")
	}
	tx := &Tx{engine: e, Spec: s, DryRun: e.DryRun}
	if e.DryRun {
		return tx, nil
	}
	id, err := e.Registry.BeginFSMutation(ctx, s.Kind, s.Target, s.Source, s.Destination, s.Detail)
	if err != nil {
		return nil, err
	}
	tx.ID = id
	return tx, nil
}
func (t *Tx) Transition(ctx context.Context, state string, detail map[string]any) error {
	if t == nil || t.DryRun {
		return nil
	}
	return t.engine.Registry.UpdateFSMutation(ctx, t.ID, state, detail)
}
func (t *Tx) Fail(ctx context.Context, err error, detail map[string]any) error {
	if t == nil || t.DryRun {
		return err
	}
	d := clone(detail)
	if err != nil {
		d["error"] = err.Error()
	}
	if u := t.Transition(context.WithoutCancel(ctx), registry.FSMutationFailed, d); u != nil {
		if err != nil {
			return errors.Join(err, u)
		}
		return u
	}
	return err
}
func (t *Tx) Complete(ctx context.Context, detail map[string]any) error {
	return t.Transition(context.WithoutCancel(ctx), registry.FSMutationComplete, detail)
}
func clone(m map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range m {
		out[k] = v
	}
	return out
}

func SyncDir(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return f.Sync()
}
