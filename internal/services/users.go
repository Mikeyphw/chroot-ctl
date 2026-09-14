package services

import (
	"chrootctl/internal/model"
	"context"
	"errors"
	"fmt"
)

type UserService struct {
	C    *Container
	Name string
}

func (s *UserService) auditMutation(ctx context.Context, eventType, username string, operationErr error, metadata map[string]string) error {
	if s.C.DryRun {
		return nil
	}
	target := s.Name + ":" + username
	return s.C.Audit().RecordMutation(context.WithoutCancel(ctx), eventType, target, operationErr, metadata)
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
		out = append(out, map[string]any{"username": u.Username, "uid": u.UID, "gid": u.GID, "home": u.Home, "shell": u.Shell, "sudo": u.Sudo, "sudo_rule": u.SudoRule, "sudo_group": u.SudoGroup, "protected": u.Protected, "system": u.System, "login": u.Login, "mutable": u.Mutable, "policy_reasons": u.PolicyReasons})
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
func (s *UserService) Add(ctx context.Context, u, shell string, sudo bool) (result model.ChrootUserCreateResult, err error) {
	defer func() {
		err = errors.Join(err, s.auditMutation(ctx, "user.add", u, err, map[string]string{"shell": shell, "sudo": fmt.Sprint(sudo)}))
	}()
	rt, err := s.C.RuntimeFor(s.Name, "")
	if err != nil {
		return result, err
	}
	return rt.Users.Add(ctx, u, shell, sudo)
}
func (s *UserService) Remove(ctx context.Context, u string, deleteHome bool) (result model.ChrootUserRemoveResult, err error) {
	defer func() {
		err = errors.Join(err, s.auditMutation(ctx, "user.remove", u, err, map[string]string{"delete_home": fmt.Sprint(deleteHome)}))
	}()
	rt, err := s.C.RuntimeFor(s.Name, "")
	if err != nil {
		return result, err
	}
	return rt.Users.Remove(ctx, u, deleteHome)
}
func (s *UserService) SetPassword(ctx context.Context, u, password string) (result model.ChrootUserPasswordResult, err error) {
	defer func() { err = errors.Join(err, s.auditMutation(ctx, "user.set_password", u, err, nil)) }()
	if password == "" {
		return result, errors.New("non-interactive Go service requires an explicit password")
	}
	rt, err := s.C.RuntimeFor(s.Name, "")
	if err != nil {
		return result, err
	}
	return rt.Users.SetPasswordValue(ctx, u, password)
}
func (s *UserService) SetShell(ctx context.Context, u, shell string) (result model.ChrootUserShellResult, err error) {
	defer func() {
		err = errors.Join(err, s.auditMutation(ctx, "user.set_shell", u, err, map[string]string{"shell": shell}))
	}()
	rt, err := s.C.RuntimeFor(s.Name, "")
	if err != nil {
		return result, err
	}
	return rt.Users.SetShell(ctx, u, shell)
}
func (s *UserService) SetSudo(ctx context.Context, u string, enabled bool) (result model.ChrootUserSudoResult, err error) {
	defer func() {
		err = errors.Join(err, s.auditMutation(ctx, "user.set_sudo", u, err, map[string]string{"enabled": fmt.Sprint(enabled)}))
	}()
	rt, err := s.C.RuntimeFor(s.Name, "")
	if err != nil {
		return result, err
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
func (s *UserService) SyncID(ctx context.Context, u string, fix bool) (result model.UserIdSyncResult, err error) {
	defer func() {
		err = errors.Join(err, s.auditMutation(ctx, "user.sync_id", u, err, map[string]string{"fix": fmt.Sprint(fix)}))
	}()
	rt, err := s.C.RuntimeFor(s.Name, u)
	if err != nil {
		return result, err
	}
	return rt.Users.SyncID(ctx, u, fix, false)
}
