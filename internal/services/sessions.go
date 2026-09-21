package services

import (
	"context"
	"fmt"

	"chrootctl/internal/tmuxruntime"
	"chrootctl/internal/validation"
)

type SessionService struct {
	C       *Container
	Manager *tmuxruntime.SessionManager
}

func (s *SessionService) manager() *tmuxruntime.SessionManager {
	if s.Manager != nil {
		return s.Manager
	}
	return tmuxruntime.NewSessionManager()
}
func (s *SessionService) List(ctx context.Context) ([]tmuxruntime.Session, error) {
	return s.manager().List(ctx)
}
func (s *SessionService) Get(ctx context.Context, id string) (*tmuxruntime.Session, error) {
	return s.manager().Get(ctx, id)
}
func (s *SessionService) Create(ctx context.Context, name, username string, width, height int) (tmuxruntime.Session, error) {
	if s.C == nil {
		return tmuxruntime.Session{}, fmt.Errorf("services container is nil")
	}
	n, e := validation.ChrootNameField(name, "chroot name")
	if e != nil {
		return tmuxruntime.Session{}, e
	}
	u, e := validation.Username(username)
	if e != nil {
		return tmuxruntime.Session{}, e
	}
	target, e := s.C.ResolveTarget(ctx, n, true)
	if e != nil {
		return tmuxruntime.Session{}, e
	}
	if target == nil {
		return tmuxruntime.Session{}, fmt.Errorf("chroot %s is not registered", n)
	}
	rt, e := s.C.RuntimeFor(n, u)
	if e != nil {
		return tmuxruntime.Session{}, e
	}
	argv, env, e := rt.Controller.LoginInvocation(false, false, u)
	if e != nil {
		return tmuxruntime.Session{}, e
	}
	id, e := tmuxruntime.SessionID(n, u)
	if e != nil {
		return tmuxruntime.Session{}, e
	}
	if existing, ge := s.manager().Get(ctx, id); ge != nil {
		return tmuxruntime.Session{}, ge
	} else if existing != nil {
		return *existing, nil
	}
	sess, e := s.manager().Create(ctx, tmuxruntime.CreateRequest{Target: n, Username: u, Width: width, Height: height, Command: argv, Environment: env})
	if e != nil {
		return tmuxruntime.Session{}, e
	}
	store := tmuxruntime.NewJobStore()
	store.Paths = s.manager().Paths
	if e = store.LinkSession(sess); e != nil {
		_ = s.manager().Kill(ctx, sess.ID)
		return tmuxruntime.Session{}, e
	}
	return sess, nil
}
func (s *SessionService) Capture(ctx context.Context, id string, lines int) (string, error) {
	return s.manager().Capture(ctx, id, lines)
}
func (s *SessionService) Detach(ctx context.Context, id string) error {
	return s.manager().Detach(ctx, id)
}
func (s *SessionService) Input(ctx context.Context, id, text string) error {
	return s.manager().Input(ctx, id, text)
}
func (s *SessionService) Kill(ctx context.Context, id string) error {
	store := tmuxruntime.NewJobStore()
	store.Paths = s.manager().Paths
	j, _ := store.Get(id)
	if j != nil {
		if ev, e := s.manager().Capture(ctx, id, 200); e == nil {
			j.Evidence = ev
		}
	}
	if e := s.manager().Kill(ctx, id); e != nil {
		return e
	}
	if j != nil {
		j.State = tmuxruntime.JobKilled
		return store.Save(*j)
	}
	return nil
}
func (s *SessionService) Resize(ctx context.Context, id string, width, height int) error {
	return s.manager().Resize(ctx, id, width, height)
}
func (s *SessionService) Reconcile(ctx context.Context, expected map[string]bool) (tmuxruntime.ReconcileResult, error) {
	r, e := s.manager().Reconcile(ctx, expected)
	if e != nil {
		return r, e
	}
	store := tmuxruntime.NewJobStore()
	store.Paths = s.manager().Paths
	if _, e = store.Reconcile(ctx, s.manager()); e != nil {
		return r, e
	}
	return r, nil
}
