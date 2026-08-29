package services

import (
	"chrootctl/internal/model"
	"context"
	"errors"
)

type UserService struct {
	C    *Container
	Name string
}

func (s *UserService) manager(username string) (*Runtime, error) {
	rt, e := s.C.RuntimeFor(s.Name, username)
	return &rt, e
}
func (s *UserService) List(ctx context.Context) ([]map[string]any, error) {
	rt, e := s.C.RuntimeFor(s.Name, "")
	if e != nil {
		return nil, e
	}
	rows, e := rt.Users.List()
	out := []map[string]any{}
	for _, u := range rows {
		out = append(out, map[string]any{"username": u.Username, "uid": u.UID, "gid": u.GID, "home": u.Home, "shell": u.Shell, "sudo": false})
	}
	return out, e
}
func (s *UserService) Show(ctx context.Context, u string) (model.ChrootUserDetails, error) {
	rt, e := s.C.RuntimeFor(s.Name, "")
	if e != nil {
		return model.ChrootUserDetails{}, e
	}
	return rt.Users.Show(u)
}
func (s *UserService) Add(ctx context.Context, u, shell string, sudo bool) (model.ChrootUserCreateResult, error) {
	rt, e := s.C.RuntimeFor(s.Name, "")
	if e != nil {
		return model.ChrootUserCreateResult{}, e
	}
	return rt.Users.Add(ctx, u, shell, sudo)
}
func (s *UserService) Remove(ctx context.Context, u string, deleteHome bool) (model.ChrootUserRemoveResult, error) {
	rt, e := s.C.RuntimeFor(s.Name, "")
	if e != nil {
		return model.ChrootUserRemoveResult{}, e
	}
	return rt.Users.Remove(ctx, u, deleteHome)
}
func (s *UserService) SetPassword(ctx context.Context, u, password string) (model.ChrootUserPasswordResult, error) {
	if password == "" {
		return model.ChrootUserPasswordResult{}, errors.New("non-interactive Go service requires an explicit password")
	}
	rt, e := s.C.RuntimeFor(s.Name, "")
	if e != nil {
		return model.ChrootUserPasswordResult{}, e
	}
	return rt.Users.SetPasswordValue(ctx, u, password)
}
func (s *UserService) SetShell(ctx context.Context, u, shell string) (model.ChrootUserShellResult, error) {
	rt, e := s.C.RuntimeFor(s.Name, "")
	if e != nil {
		return model.ChrootUserShellResult{}, e
	}
	return rt.Users.SetShell(ctx, u, shell)
}
func (s *UserService) SetSudo(ctx context.Context, u string, enabled bool) (model.ChrootUserSudoResult, error) {
	rt, e := s.C.RuntimeFor(s.Name, "")
	if e != nil {
		return model.ChrootUserSudoResult{}, e
	}
	return rt.Users.SetSudo(ctx, u, enabled)
}
func (s *UserService) ShowID(ctx context.Context, u string) (model.UserIdStatus, error) {
	rt, e := s.C.RuntimeFor(s.Name, u)
	if e != nil {
		return model.UserIdStatus{}, e
	}
	return rt.Users.ShowID(u)
}
func (s *UserService) SyncID(ctx context.Context, u string, fix bool) (model.UserIdSyncResult, error) {
	rt, e := s.C.RuntimeFor(s.Name, u)
	if e != nil {
		return model.UserIdSyncResult{}, e
	}
	return rt.Users.SyncID(ctx, u, fix, false)
}
