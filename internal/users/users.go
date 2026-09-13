package users

import (
	"chrootctl/internal/config"
	"chrootctl/internal/model"
	"chrootctl/internal/registry"
	sys "chrootctl/internal/system"
	"chrootctl/internal/validation"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type User struct{ Username, UID, GID, Home, Shell string }
type Manager struct {
	Config   config.ChrootConfig
	Runner   *sys.Runner
	Registry *registry.Registry
}

func (u User) Display() map[string]string {
	return map[string]string{"username": u.Username, "uid": u.UID, "gid": u.GID, "home": u.Home, "shell": u.Shell}
}
func (m *Manager) List() ([]User, error) {
	data, e := os.ReadFile(filepath.Join(m.Config.ChrootBase(), "etc/passwd"))
	if os.IsNotExist(e) {
		return []User{}, nil
	}
	if e != nil {
		return nil, e
	}
	out := []User{}
	for _, line := range strings.Split(string(data), "\n") {
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		p := strings.Split(line, ":")
		if len(p) >= 7 {
			out = append(out, User{p[0], p[2], p[3], p[5], p[6]})
		}
	}
	return out, nil
}
func (m *Manager) find(name string) (User, error) {
	name, e := validation.Username(name)
	if e != nil {
		return User{}, e
	}
	users, e := m.List()
	if e != nil {
		return User{}, e
	}
	for _, u := range users {
		if u.Username == name {
			return u, nil
		}
	}
	return User{}, fmt.Errorf("unknown chroot user: %s", name)
}
func validShell(s string) (string, error) {
	if !strings.HasPrefix(s, "/") || strings.Contains(s, "..") || strings.ContainsAny(s, "\n\r") {
		return "", fmt.Errorf("invalid shell path: %q", s)
	}
	return s, nil
}
func ValidatePassword(p string) (string, error) {
	if p == "" {
		return "", errors.New("password must not be empty")
	}
	if len(p) > 4096 {
		return "", errors.New("password is too long")
	}
	if strings.ContainsAny(p, "\x00\n\r:") {
		return "", errors.New("password contains a value that cannot be passed to chpasswd")
	}
	return p, nil
}
func (m *Manager) installed(ctx context.Context) error {
	if e := m.Runner.RequireRoot(); e != nil {
		return e
	}
	if m.Registry == nil {
		return errors.New("registry is nil")
	}
	r, e := m.Registry.Get(ctx, m.Config.DistroName)
	if e != nil {
		return e
	}
	if r == nil || !r.Installed {
		return errors.New("chroot must be installed first")
	}
	return nil
}
func (m *Manager) sh(ctx context.Context, cmd string) (sys.RunResult, error) {
	return m.Runner.Run(ctx, []string{"busybox", "chroot", m.Config.ChrootBase(), "/bin/bash", "-lc", cmd}, sys.RunOptions{ChrootEnv: true})
}
func q(s string) string { return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'" }
func (m *Manager) Show(name string) (model.ChrootUserDetails, error) {
	u, e := m.find(name)
	if e != nil {
		return model.ChrootUserDetails{}, e
	}
	return model.ChrootUserDetails{Username: u.Username, Uid: u.UID, Gid: u.GID, Home: u.Home, Shell: u.Shell, Sudo: m.hasSudo(u.Username)}, nil
}
func (m *Manager) Add(ctx context.Context, name, shell string, sudo bool) (model.ChrootUserCreateResult, error) {
	if e := m.installed(ctx); e != nil {
		return model.ChrootUserCreateResult{}, e
	}
	name, e := validation.Username(name)
	if e != nil {
		return model.ChrootUserCreateResult{}, e
	}
	shell, e = validShell(shell)
	if e != nil {
		return model.ChrootUserCreateResult{}, e
	}
	if u, x := m.find(name); x == nil {
		return model.ChrootUserCreateResult{Username: name, Shell: u.Shell, Sudo: m.hasSudo(name), Created: false}, nil
	}
	if _, e = m.sh(ctx, "getent group "+q(name)+" >/dev/null || groupadd "+q(name)); e != nil {
		return model.ChrootUserCreateResult{}, e
	}
	if _, e = m.sh(ctx, "useradd -m -s "+q(shell)+" -g "+q(name)+" "+q(name)); e != nil {
		return model.ChrootUserCreateResult{}, e
	}
	if sudo {
		if _, e = m.SetSudo(ctx, name, true); e != nil {
			return model.ChrootUserCreateResult{}, e
		}
	}
	return model.ChrootUserCreateResult{Username: name, Shell: shell, Sudo: sudo, Created: true}, nil
}
func (m *Manager) Remove(ctx context.Context, name string, deleteHome bool) (model.ChrootUserRemoveResult, error) {
	if e := m.installed(ctx); e != nil {
		return model.ChrootUserRemoveResult{}, e
	}
	name, e := validation.Username(name)
	if e != nil {
		return model.ChrootUserRemoveResult{}, e
	}
	if _, e = m.find(name); e != nil {
		return model.ChrootUserRemoveResult{Username: name}, nil
	}
	flag := ""
	if deleteHome {
		flag = "-r "
	}
	if _, e = m.sh(ctx, "userdel "+flag+q(name)); e != nil {
		return model.ChrootUserRemoveResult{}, e
	}
	_ = m.removeSudoers(name)
	return model.ChrootUserRemoveResult{Username: name, HomeDeleted: deleteHome, Removed: true}, nil
}
func (m *Manager) SetPasswordValue(ctx context.Context, name, password string) (model.ChrootUserPasswordResult, error) {
	if e := m.installed(ctx); e != nil {
		return model.ChrootUserPasswordResult{}, e
	}
	name, e := validation.Username(name)
	if e != nil {
		return model.ChrootUserPasswordResult{}, e
	}
	password, e = ValidatePassword(password)
	if e != nil {
		return model.ChrootUserPasswordResult{}, e
	}
	_, e = m.Runner.Run(ctx, []string{"busybox", "chroot", m.Config.ChrootBase(), "/bin/bash", "-lc", "chpasswd"}, sys.RunOptions{ChrootEnv: true, Input: name + ":" + password + "\n"})
	return model.ChrootUserPasswordResult{Username: name, Updated: e == nil}, e
}
func (m *Manager) SetShell(ctx context.Context, name, shell string) (model.ChrootUserShellResult, error) {
	if e := m.installed(ctx); e != nil {
		return model.ChrootUserShellResult{}, e
	}
	name, e := validation.Username(name)
	if e != nil {
		return model.ChrootUserShellResult{}, e
	}
	shell, e = validShell(shell)
	if e != nil {
		return model.ChrootUserShellResult{}, e
	}
	_, e = m.sh(ctx, "usermod -s "+q(shell)+" "+q(name))
	return model.ChrootUserShellResult{Username: name, Shell: shell, Updated: e == nil}, e
}
func (m *Manager) sudoers(name string) string {
	return filepath.Join(m.Config.ChrootBase(), "etc/sudoers.d", "90-chrootctl-"+name)
}
func (m *Manager) writeSudoers(ctx context.Context, name string) error {
	if m.Runner.DryRun {
		return nil
	}
	p := m.sudoers(name)
	if i, e := os.Lstat(p); e == nil && i.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("refusing sudoers symlink: %s", p)
	}
	if e := os.MkdirAll(filepath.Dir(p), 0o755); e != nil {
		return e
	}
	if info, e := os.Lstat(filepath.Dir(p)); e != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return fmt.Errorf("unsafe sudoers directory: %s", filepath.Dir(p))
	}
	tmp, e := os.CreateTemp(filepath.Dir(p), "."+filepath.Base(p)+".")
	if e != nil {
		return e
	}
	tn := tmp.Name()
	defer os.Remove(tn)
	_ = tmp.Chmod(0o440)
	if _, e = tmp.WriteString(name + " ALL=(ALL:ALL) ALL\n"); e != nil {
		return e
	}
	if e = tmp.Sync(); e != nil {
		return e
	}
	if e = tmp.Close(); e != nil {
		return e
	}
	relative := "/etc/sudoers.d/" + filepath.Base(tn)
	checked, runErr := m.Runner.Run(ctx, []string{"busybox", "chroot", m.Config.ChrootBase(), "visudo", "-cf", relative}, sys.RunOptions{ChrootEnv: true, AllowFailure: true})
	if runErr != nil {
		return runErr
	}
	if checked.ReturnCode != 0 {
		return fmt.Errorf("visudo rejected sudoers rule for %s: %s", name, strings.TrimSpace(checked.Stderr))
	}
	if e = os.Rename(tn, p); e != nil {
		return e
	}
	return os.Chmod(p, 0o440)
}
func (m *Manager) removeSudoers(name string) error {
	if m.Runner.DryRun {
		return nil
	}
	e := os.Remove(m.sudoers(name))
	if os.IsNotExist(e) {
		return nil
	}
	return e
}
func (m *Manager) hasSudo(name string) bool {
	p := m.sudoers(name)
	i, e := os.Lstat(p)
	if e != nil || i.Mode()&os.ModeSymlink != 0 || !i.Mode().IsRegular() {
		return false
	}
	d, e := os.ReadFile(p)
	return e == nil && strings.Contains(string(d), name+" ALL=(ALL:ALL) ALL")
}
func (m *Manager) SetSudo(ctx context.Context, name string, enabled bool) (model.ChrootUserSudoResult, error) {
	if e := m.installed(ctx); e != nil {
		return model.ChrootUserSudoResult{}, e
	}
	name, e := validation.Username(name)
	if e != nil {
		return model.ChrootUserSudoResult{}, e
	}
	if enabled {
		if _, e = m.sh(ctx, "getent group sudo >/dev/null || groupadd sudo"); e != nil {
			return model.ChrootUserSudoResult{}, e
		}
		if _, e = m.sh(ctx, "usermod -aG sudo "+q(name)); e != nil {
			return model.ChrootUserSudoResult{}, e
		}
		e = m.writeSudoers(ctx, name)
	} else {
		_, e = m.sh(ctx, "gpasswd -d "+q(name)+" sudo >/dev/null 2>&1 || true")
		if e == nil {
			e = m.removeSudoers(name)
		}
	}
	return model.ChrootUserSudoResult{Username: name, Enabled: enabled}, e
}
func identityRows(path string) map[int]string {
	d, _ := os.ReadFile(path)
	out := map[int]string{}
	for _, l := range strings.Split(string(d), "\n") {
		p := strings.Split(l, ":")
		if len(p) >= 4 {
			if n, e := strconv.Atoi(p[2]); e == nil {
				out[n] = p[0]
			}
		}
	}
	return out
}
func (m *Manager) ShowID(username string) (model.UserIdStatus, error) {
	if username == "" {
		username = m.Config.Username
	}
	u, e := validation.Username(username)
	if e != nil {
		return model.UserIdStatus{}, e
	}
	uid, gid, e := sys.HostTermuxUIDGID(m.Config.TermuxHome)
	if e != nil {
		return model.UserIdStatus{}, e
	}
	status := model.UserIdStatus{Username: u, HostUid: uid, HostGid: gid}
	p := filepath.Join(m.Config.ChrootBase(), "etc/passwd")
	g := filepath.Join(m.Config.ChrootBase(), "etc/group")
	if _, e = os.Stat(p); e == nil {
		status.PasswdExists = true
	}
	if _, e = os.Stat(g); e == nil {
		status.GroupExists = true
	}
	if users, e := m.List(); e == nil {
		for _, x := range users {
			if x.Username == u {
				status.ChrootUid = x.UID
				status.ChrootGid = x.GID
			}
		}
	}
	return status, nil
}
func (m *Manager) SyncID(ctx context.Context, username string, fixOwnership, allowPending bool) (model.UserIdSyncResult, error) {
	if e := m.Runner.RequireRoot(); e != nil {
		return model.UserIdSyncResult{}, e
	}
	if username == "" {
		username = m.Config.Username
	}
	u, e := validation.Username(username)
	if e != nil {
		return model.UserIdSyncResult{}, e
	}
	if m.Registry != nil {
		r, _ := m.Registry.Get(ctx, m.Config.DistroName)
		ready := r != nil && r.Installed
		if !ready && allowPending && r != nil && r.Phase == "desktop" {
			_, x := os.Stat(filepath.Join(m.Config.ChrootBase(), "etc/passwd"))
			ready = x == nil
		}
		if !ready {
			return model.UserIdSyncResult{}, errors.New("chroot must be installed before UID/GID synchronization")
		}
	}
	uid, gid, e := sys.HostTermuxUIDGID(m.Config.TermuxHome)
	if e != nil {
		return model.UserIdSyncResult{}, e
	}
	if owner := identityRows(filepath.Join(m.Config.ChrootBase(), "etc/passwd"))[uid]; owner != "" && owner != u {
		return model.UserIdSyncResult{}, fmt.Errorf("cannot sync UID %d: already owned by chroot user %s", uid, owner)
	}
	if owner := identityRows(filepath.Join(m.Config.ChrootBase(), "etc/group"))[gid]; owner != "" && owner != u {
		return model.UserIdSyncResult{}, fmt.Errorf("cannot sync GID %d: already owned by chroot group %s", gid, owner)
	}
	for _, cmd := range []string{"getent group " + q(u) + " >/dev/null || groupadd " + q(u), "id -u " + q(u) + " >/dev/null 2>&1 || useradd -m -s /bin/bash -g " + q(u) + " " + q(u), fmt.Sprintf("groupmod -g %d %s", gid, q(u)), fmt.Sprintf("usermod -u %d -g %d %s", uid, gid, q(u))} {
		if _, e = m.sh(ctx, cmd); e != nil {
			return model.UserIdSyncResult{}, e
		}
	}
	if fixOwnership {
		home := "/home/" + u
		_, e = m.sh(ctx, fmt.Sprintf("[ -d %s ] && chown -R %d:%d %s || true", q(home), uid, gid, q(home)))
		if e != nil {
			return model.UserIdSyncResult{}, e
		}
		_, e = m.sh(ctx, `for d in /tmp /var/tmp; do [ ! -d "$d" ] || { chown 0:0 "$d" && chmod 1777 "$d"; }; done; [ ! -d /var/cache ] || { chown 0:0 /var/cache && chmod 0755 /var/cache; }`)
		if e != nil {
			return model.UserIdSyncResult{}, e
		}
	}
	return model.UserIdSyncResult{Username: u, Uid: uid, Gid: gid, OwnershipFixed: fixOwnership}, nil
}
