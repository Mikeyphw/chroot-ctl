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

type User struct {
	Username      string
	UID           string
	GID           string
	Home          string
	Shell         string
	Sudo          bool
	SudoRule      bool
	SudoGroup     bool
	Protected     bool
	System        bool
	Login         bool
	Mutable       bool
	PolicyReasons []string
}

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
	sudoMembers := m.sudoGroupMembers()
	out := []User{}
	for _, line := range strings.Split(string(data), "\n") {
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		p := strings.Split(line, ":")
		if len(p) >= 7 {
			u := User{Username: p[0], UID: p[2], GID: p[3], Home: p[5], Shell: p[6]}
			u.SudoGroup = sudoMembers[u.Username]
			m.applyUserPolicy(&u)
			out = append(out, u)
		}
	}
	return out, nil
}

func (m *Manager) applyUserPolicy(u *User) {
	u.SudoRule = m.hasSudoRule(u.Username)
	u.Sudo = u.SudoRule || u.SudoGroup
	policy := classifyUser(*u)
	u.Protected = policy.Protected
	u.System = policy.System
	u.Login = policy.Login
	u.Mutable = policy.Mutable
	u.PolicyReasons = policy.Reasons
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

func (m *Manager) shAllow(ctx context.Context, cmd string) (sys.RunResult, error) {
	return m.Runner.Run(ctx, []string{"busybox", "chroot", m.Config.ChrootBase(), "/bin/bash", "-lc", cmd}, sys.RunOptions{ChrootEnv: true, AllowFailure: true})
}

func q(s string) string { return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'" }

func (m *Manager) Show(name string) (model.ChrootUserDetails, error) {
	u, e := m.find(name)
	if e != nil {
		return model.ChrootUserDetails{}, e
	}
	return userDetails(u), nil
}

func userDetails(u User) model.ChrootUserDetails {
	return model.ChrootUserDetails{Username: u.Username, Uid: u.UID, Gid: u.GID, Home: u.Home, Shell: u.Shell, Sudo: u.Sudo, SudoRule: u.SudoRule, SudoGroup: u.SudoGroup, Protected: u.Protected, System: u.System, Login: u.Login, Mutable: u.Mutable, PolicyReasons: append([]string(nil), u.PolicyReasons...)}
}

func (m *Manager) ensureMutableUser(name, action string) (User, error) {
	u, e := m.find(name)
	if e != nil {
		return User{}, e
	}
	if !u.Mutable {
		reason := strings.Join(u.PolicyReasons, ", ")
		if reason == "" {
			reason = "protected or system account"
		}
		return User{}, fmt.Errorf("refusing %s for protected chroot user %s: %s", action, u.Username, reason)
	}
	return u, nil
}

func rejectProtectedNewUser(name string) error {
	if isProtectedUsername(name) {
		return fmt.Errorf("refusing to create protected chroot user: %s", name)
	}
	return nil
}

func (m *Manager) validateShellForMutation(ctx context.Context, shell string) (string, error) {
	shell, e := validShell(shell)
	if e != nil {
		return "", e
	}
	if !shellAllowsLogin(shell) {
		return "", fmt.Errorf("refusing non-login shell for managed user: %s", shell)
	}
	if m.Runner != nil && m.Runner.DryRun {
		return shell, nil
	}
	res, e := m.shAllow(ctx, "test -x "+q(shell))
	if e != nil {
		return "", e
	}
	if res.ReturnCode != 0 {
		return "", fmt.Errorf("shell is not executable inside chroot: %s", shell)
	}
	return shell, nil
}

func (m *Manager) Add(ctx context.Context, name, shell string, sudo bool) (model.ChrootUserCreateResult, error) {
	if e := m.installed(ctx); e != nil {
		return model.ChrootUserCreateResult{}, e
	}
	name, e := validation.Username(name)
	if e != nil {
		return model.ChrootUserCreateResult{}, e
	}
	if e = rejectProtectedNewUser(name); e != nil {
		return model.ChrootUserCreateResult{}, e
	}
	shell, e = m.validateShellForMutation(ctx, shell)
	if e != nil {
		return model.ChrootUserCreateResult{}, e
	}
	if u, x := m.find(name); x == nil {
		return model.ChrootUserCreateResult{Username: name, Shell: u.Shell, Sudo: u.Sudo, Created: false, AlreadyExisted: true}, nil
	}
	groupPreexisting := m.groupExists(ctx, name)
	if _, e = m.sh(ctx, "getent group "+q(name)+" >/dev/null || groupadd "+q(name)); e != nil {
		return model.ChrootUserCreateResult{}, e
	}
	created := false
	if _, e = m.sh(ctx, "useradd -m -s "+q(shell)+" -g "+q(name)+" "+q(name)); e != nil {
		if !groupPreexisting {
			_, _ = m.shAllow(ctx, "groupdel "+q(name))
		}
		return model.ChrootUserCreateResult{}, e
	}
	created = true
	if sudo {
		if _, e = m.SetSudo(ctx, name, true); e != nil {
			m.rollbackCreatedUser(ctx, name, !groupPreexisting)
			return model.ChrootUserCreateResult{}, e
		}
	}
	return model.ChrootUserCreateResult{Username: name, Shell: shell, Sudo: sudo, Created: created}, nil
}

func (m *Manager) rollbackCreatedUser(ctx context.Context, name string, removeGroup bool) {
	_ = m.removeSudoers(name)
	_, _ = m.shAllow(ctx, "userdel -r "+q(name)+" >/dev/null 2>&1 || userdel "+q(name)+" >/dev/null 2>&1 || true")
	if removeGroup {
		_, _ = m.shAllow(ctx, "groupdel "+q(name)+" >/dev/null 2>&1 || true")
	}
}

func (m *Manager) groupExists(ctx context.Context, name string) bool {
	res, e := m.shAllow(ctx, "getent group "+q(name)+" >/dev/null")
	return e == nil && res.ReturnCode == 0
}

func (m *Manager) Remove(ctx context.Context, name string, deleteHome bool) (model.ChrootUserRemoveResult, error) {
	if e := m.installed(ctx); e != nil {
		return model.ChrootUserRemoveResult{}, e
	}
	name, e := validation.Username(name)
	if e != nil {
		return model.ChrootUserRemoveResult{}, e
	}
	if _, e = m.ensureMutableUser(name, "remove"); e != nil {
		if strings.Contains(e.Error(), "unknown chroot user") {
			return model.ChrootUserRemoveResult{Username: name}, nil
		}
		return model.ChrootUserRemoveResult{}, e
	}
	flag := ""
	if deleteHome {
		flag = "-r "
	}
	if _, e = m.sh(ctx, "userdel "+flag+q(name)); e != nil {
		return model.ChrootUserRemoveResult{}, e
	}
	if e = m.removeSudoers(name); e != nil {
		return model.ChrootUserRemoveResult{}, e
	}
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
	if _, e = m.ensureMutableUser(name, "password update"); e != nil {
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
	if _, e = m.ensureMutableUser(name, "shell update"); e != nil {
		return model.ChrootUserShellResult{}, e
	}
	shell, e = m.validateShellForMutation(ctx, shell)
	if e != nil {
		return model.ChrootUserShellResult{}, e
	}
	_, e = m.sh(ctx, "usermod -s "+q(shell)+" "+q(name))
	return model.ChrootUserShellResult{Username: name, Shell: shell, Updated: e == nil}, e
}

func (m *Manager) sudoers(name string) string {
	return filepath.Join(m.Config.ChrootBase(), "etc/sudoers.d", sudoersBasename(name))
}

func (m *Manager) sudoersCandidates(name string) []string {
	base := filepath.Join(m.Config.ChrootBase(), "etc/sudoers.d")
	return []string{filepath.Join(base, sudoersBasename(name)), filepath.Join(base, legacySudoersBasename(name))}
}

func (m *Manager) validateSudoersParentChain(path string) error {
	base, e := filepath.Abs(m.Config.ChrootBase())
	if e != nil {
		return e
	}
	target, e := filepath.Abs(path)
	if e != nil {
		return e
	}
	rel, e := filepath.Rel(base, target)
	if e != nil || strings.HasPrefix(rel, "..") || filepath.IsAbs(rel) {
		return fmt.Errorf("sudoers path escapes chroot: %s", path)
	}
	cur := base
	for _, part := range strings.Split(filepath.Dir(rel), string(filepath.Separator)) {
		if part == "" || part == "." {
			continue
		}
		cur = filepath.Join(cur, part)
		info, statErr := os.Lstat(cur)
		if statErr != nil {
			return statErr
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return fmt.Errorf("unsafe sudoers parent: %s", cur)
		}
	}
	return nil
}

func (m *Manager) writeSudoers(ctx context.Context, name string) error {
	if m.Runner.DryRun {
		return nil
	}
	p := m.sudoers(name)
	if i, e := os.Lstat(p); e == nil && i.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("refusing sudoers symlink: %s", p)
	}
	dir := filepath.Dir(p)
	if e := os.MkdirAll(dir, 0o755); e != nil {
		return e
	}
	if e := m.validateSudoersParentChain(p); e != nil {
		return e
	}
	tmp, e := os.CreateTemp(dir, "."+filepath.Base(p)+".")
	if e != nil {
		return e
	}
	tn := tmp.Name()
	defer os.Remove(tn)
	_ = tmp.Chmod(0o440)
	if _, e = tmp.WriteString(sudoersRule(name)); e != nil {
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
	if e = os.Chmod(p, 0o440); e != nil {
		return e
	}
	legacy := filepath.Join(dir, legacySudoersBasename(name))
	if legacy != p {
		if e = os.Remove(legacy); e != nil && !os.IsNotExist(e) {
			return e
		}
	}
	return nil
}

func (m *Manager) removeSudoers(name string) error {
	if m.Runner.DryRun {
		return nil
	}
	var errs []string
	for _, p := range m.sudoersCandidates(name) {
		e := os.Remove(p)
		if e != nil && !os.IsNotExist(e) {
			errs = append(errs, e.Error())
		}
	}
	if len(errs) > 0 {
		return errors.New(strings.Join(errs, "; "))
	}
	return nil
}

func (m *Manager) hasSudoRule(name string) bool {
	for _, p := range m.sudoersCandidates(name) {
		i, e := os.Lstat(p)
		if e != nil || i.Mode()&os.ModeSymlink != 0 || !i.Mode().IsRegular() {
			continue
		}
		d, e := os.ReadFile(p)
		if e == nil && sudoersRuleMentionsUser(string(d), name) {
			return true
		}
	}
	return false
}

func (m *Manager) hasSudo(name string) bool { return m.hasSudoRule(name) || m.sudoGroupMembers()[name] }

func (m *Manager) sudoGroupMembers() map[string]bool {
	out := map[string]bool{}
	paths := []string{filepath.Join(m.Config.ChrootBase(), "etc/group"), filepath.Join(m.Config.ChrootBase(), "etc/gshadow")}
	for _, path := range paths[:1] {
		data, e := os.ReadFile(path)
		if e != nil {
			continue
		}
		for _, line := range strings.Split(string(data), "\n") {
			parts := strings.Split(line, ":")
			if len(parts) < 4 || parts[0] != "sudo" {
				continue
			}
			for _, item := range strings.Split(parts[3], ",") {
				if item = strings.TrimSpace(item); item != "" {
					out[item] = true
				}
			}
		}
	}
	return out
}

func (m *Manager) SetSudo(ctx context.Context, name string, enabled bool) (model.ChrootUserSudoResult, error) {
	if e := m.installed(ctx); e != nil {
		return model.ChrootUserSudoResult{}, e
	}
	name, e := validation.Username(name)
	if e != nil {
		return model.ChrootUserSudoResult{}, e
	}
	if _, e = m.ensureMutableUser(name, "sudo update"); e != nil {
		return model.ChrootUserSudoResult{}, e
	}
	if enabled {
		if e = m.writeSudoers(ctx, name); e != nil {
			return model.ChrootUserSudoResult{}, e
		}
		if _, e = m.sh(ctx, "getent group sudo >/dev/null || groupadd sudo"); e != nil {
			_ = m.removeSudoers(name)
			return model.ChrootUserSudoResult{}, e
		}
		if _, e = m.sh(ctx, "usermod -aG sudo "+q(name)); e != nil {
			_ = m.removeSudoers(name)
			return model.ChrootUserSudoResult{}, e
		}
	} else {
		cmd := "if getent group sudo >/dev/null; then if id -nG " + q(name) + " | tr ' ' '\\n' | grep -qx sudo; then gpasswd -d " + q(name) + " sudo; fi; fi"
		if _, e = m.sh(ctx, cmd); e != nil {
			return model.ChrootUserSudoResult{}, e
		}
		if e = m.removeSudoers(name); e != nil {
			return model.ChrootUserSudoResult{}, e
		}
	}
	return model.ChrootUserSudoResult{Username: name, Enabled: enabled, Passwordless: enabled, SudoRule: enabled, SudoGroup: enabled}, nil
}

func identityRows(path string) map[int]string {
	rows, _ := identityRowsErr(path)
	return rows
}

func identityRowsErr(path string) (map[int]string, error) {
	d, e := os.ReadFile(path)
	if e != nil {
		return nil, e
	}
	out := map[int]string{}
	for _, l := range strings.Split(string(d), "\n") {
		p := strings.Split(l, ":")
		if len(p) >= 4 {
			if n, e := strconv.Atoi(p[2]); e == nil {
				out[n] = p[0]
			}
		}
	}
	return out, nil
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
				status.Protected = x.Protected
				status.System = x.System
				status.Mutable = x.Mutable
				status.PolicyReasons = append([]string(nil), x.PolicyReasons...)
			}
		}
	}
	if status.ChrootUid == "" && isProtectedUsername(u) {
		status.Protected = true
		status.System = true
		status.Mutable = false
		status.PolicyReasons = []string{"protected account"}
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
	if e = rejectProtectedNewUser(u); e != nil {
		return model.UserIdSyncResult{}, e
	}
	if existing, findErr := m.find(u); findErr == nil && !existing.Mutable {
		return model.UserIdSyncResult{}, fmt.Errorf("refusing UID/GID sync for protected chroot user %s", u)
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
	passwdRows, e := identityRowsErr(filepath.Join(m.Config.ChrootBase(), "etc/passwd"))
	if e != nil {
		return model.UserIdSyncResult{}, fmt.Errorf("read passwd for UID collision check: %w", e)
	}
	groupRows, e := identityRowsErr(filepath.Join(m.Config.ChrootBase(), "etc/group"))
	if e != nil {
		return model.UserIdSyncResult{}, fmt.Errorf("read group for GID collision check: %w", e)
	}
	if owner := passwdRows[uid]; owner != "" && owner != u {
		return model.UserIdSyncResult{}, fmt.Errorf("cannot sync UID %d: already owned by chroot user %s", uid, owner)
	}
	if owner := groupRows[gid]; owner != "" && owner != u {
		return model.UserIdSyncResult{}, fmt.Errorf("cannot sync GID %d: already owned by chroot group %s", gid, owner)
	}
	script := m.syncIDScript(u, uid, gid, fixOwnership)
	if _, e = m.sh(ctx, script); e != nil {
		return model.UserIdSyncResult{}, e
	}
	return model.UserIdSyncResult{Username: u, Uid: uid, Gid: gid, OwnershipFixed: fixOwnership, Transactional: true}, nil
}

func (m *Manager) syncIDScript(u string, uid, gid int, fixOwnership bool) string {
	user := q(u)
	uidText := strconv.Itoa(uid)
	gidText := strconv.Itoa(gid)
	parts := []string{
		"set -eu",
		"u=" + user,
		"new_uid=" + q(uidText),
		"new_gid=" + q(gidText),
		"created_user=0",
		"created_group=0",
		"old_uid=$(id -u \"$u\" 2>/dev/null || true)",
		"old_gid=$(id -g \"$u\" 2>/dev/null || true)",
		"rollback(){ status=$?; set +e; if [ \"$old_uid\" != \"\" ]; then usermod -u \"$old_uid\" \"$u\" >/dev/null 2>&1; fi; if [ \"$old_gid\" != \"\" ]; then groupmod -g \"$old_gid\" \"$u\" >/dev/null 2>&1; usermod -g \"$old_gid\" \"$u\" >/dev/null 2>&1; fi; if [ \"$created_user\" = 1 ]; then userdel -r \"$u\" >/dev/null 2>&1 || userdel \"$u\" >/dev/null 2>&1; fi; if [ \"$created_group\" = 1 ]; then groupdel \"$u\" >/dev/null 2>&1; fi; exit $status; }",
		"trap rollback ERR",
		"getent group \"$u\" >/dev/null || { groupadd \"$u\"; created_group=1; }",
		"id -u \"$u\" >/dev/null 2>&1 || { useradd -m -s /bin/bash -g \"$u\" \"$u\"; created_user=1; old_uid=$(id -u \"$u\"); old_gid=$(id -g \"$u\"); }",
		"groupmod -g \"$new_gid\" \"$u\"",
		"usermod -u \"$new_uid\" -g \"$new_gid\" \"$u\"",
	}
	if fixOwnership {
		parts = append(parts,
			"home=$(getent passwd \"$u\" | cut -d: -f6)",
			"if [ -n \"$home\" ] && [ -d \"$home\" ] && [ -n \"$old_uid\" ] && [ -n \"$old_gid\" ]; then find \"$home\" -xdev \\( -uid \"$old_uid\" -o -gid \"$old_gid\" \\) -exec chown -h \"$new_uid:$new_gid\" {} +; fi",
			`for d in /tmp /var/tmp; do [ ! -d "$d" ] || { chown 0:0 "$d" && chmod 1777 "$d"; }; done; [ ! -d /var/cache ] || { chown 0:0 /var/cache && chmod 0755 /var/cache; }`,
		)
	}
	parts = append(parts, "trap - ERR")
	return strings.Join(parts, "; ")
}
