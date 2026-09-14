package catalog

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"

	"chrootctl/internal/config"
	"chrootctl/internal/model"
	"chrootctl/internal/registry"
	sys "chrootctl/internal/system"
	resourceassets "chrootctl/resources"
)

var SupportedDistros = map[string]bool{"ubuntu": true, "arch": true}
var supportedSuffix = map[string]bool{".sh": true}

type Entry struct {
	Kind, Name, Description, Script, ScriptText, Version, Rollback string
	Source, ScriptSHA256, RiskLevel, State, StateReason            string
	Distros, Categories, Risks, Requires                           []string
	Destructive, RequiresConfirmation, Installed, Failed           bool
}

type Catalog struct {
	Kind         string
	Config       *config.ChrootConfig
	ResourceRoot string // test/development override; empty means embedded resources.FS
}

func (e Entry) MatchesDistro(d string) bool {
	for _, x := range e.Distros {
		if x == d {
			return true
		}
	}
	return false
}
func (e Entry) MatchesCategory(c string) bool {
	for _, x := range e.Categories {
		if x == c {
			return true
		}
	}
	return false
}

func normalizeCategory(s string) (string, error) {
	raw := s
	s = strings.ToLower(strings.TrimSpace(s))
	s = strings.NewReplacer("_", "-", " ", "-").Replace(s)
	if s == "" {
		return "", fmt.Errorf("invalid category: %q", raw)
	}
	for _, r := range s {
		if !(r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-') {
			return "", fmt.Errorf("invalid category: %q", raw)
		}
	}
	return s, nil
}
func validName(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if !(r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-' || r == '_') {
			return false
		}
	}
	return true
}

// parseManifest implements the deliberately small YAML subset used by the
// repository manifests: scalar keys and top-level string lists. This avoids
// introducing a YAML runtime dependency into the final native binary.
func parseManifest(text, filename, kind, scriptText string) (Entry, map[string]string, error) {
	vals := map[string]string{}
	lists := map[string][]string{}
	current := ""
	scanner := bufio.NewScanner(strings.NewReader(text))
	for scanner.Scan() {
		line := scanner.Text()
		trim := strings.TrimSpace(line)
		if trim == "" || strings.HasPrefix(trim, "#") {
			continue
		}
		if strings.HasPrefix(trim, "-") {
			if current != "" {
				lists[current] = append(lists[current], strings.Trim(strings.TrimSpace(strings.TrimPrefix(trim, "-")), "'\""))
			}
			continue
		}
		parts := strings.SplitN(trim, ":", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		value := strings.Trim(strings.TrimSpace(parts[1]), "'\"")
		current = key
		if value != "" {
			vals[key] = value
			current = ""
		}
	}
	if err := scanner.Err(); err != nil {
		return Entry{}, nil, err
	}
	name := vals["name"]
	if !validName(name) {
		return Entry{}, nil, fmt.Errorf("manifest %s has invalid name: %s", filename, name)
	}
	desc := vals["description"]
	if desc == "" {
		return Entry{}, nil, fmt.Errorf("manifest %s missing description", filename)
	}
	script := vals["script"]
	if strings.ContainsAny(script, "/\\") || strings.Contains(script, "..") || !supportedSuffix[filepath.Ext(script)] {
		return Entry{}, nil, fmt.Errorf("manifest %s has invalid script path: %s", filename, script)
	}
	distros := []string{}
	rawD := vals["distro"]
	if rawD == "all" {
		distros = []string{"arch", "ubuntu"}
	} else if rawD != "" {
		distros = []string{rawD}
	} else {
		distros = lists["distro"]
	}
	if len(distros) == 0 {
		return Entry{}, nil, fmt.Errorf("manifest %s distro must be a string, a non-empty list of strings, or 'all'", filename)
	}
	for _, d := range distros {
		if !SupportedDistros[d] {
			return Entry{}, nil, fmt.Errorf("manifest %s has unsupported distro values: %s", filename, d)
		}
	}
	cats := []string{}
	for _, c := range lists["categories"] {
		n, err := normalizeCategory(c)
		if err != nil {
			return Entry{}, nil, err
		}
		cats = append(cats, n)
	}
	sort.Strings(cats)
	rollback := vals["rollback"]
	if rollback == "" {
		rollback = "manual"
	}
	if rollback != "manual" && rollback != "idempotent" && rollback != "none" {
		return Entry{}, nil, fmt.Errorf("manifest %s has invalid rollback policy: %s", filename, rollback)
	}
	v := vals["version"]
	if v == "" {
		v = "1"
	}
	return Entry{
		Kind: kind, Name: name, Description: desc, Script: script, ScriptText: scriptText,
		Version: v, Rollback: rollback, Distros: distros, Categories: cats,
		Risks: normalizeStringList(lists["risks"]), Requires: normalizeStringList(lists["requires"]),
	}, vals, nil
}

func normalizeStringList(in []string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, v := range in {
		v = strings.ToLower(strings.ReplaceAll(strings.TrimSpace(v), "_", "-"))
		if v != "" && !seen[v] {
			seen[v] = true
			out = append(out, v)
		}
	}
	sort.Strings(out)
	return out
}

func scriptSHA256(text string) string {
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:])
}

func classifyRisk(entryName, scriptText, rollback string, risks []string) (level string, destructive, confirm bool) {
	level = "low"
	riskSet := map[string]bool{}
	for _, risk := range risks {
		riskSet[risk] = true
	}
	scriptLower := strings.ToLower(scriptText)
	if riskSet["identity-mutation"] || riskSet["filesystem-ownership"] || strings.Contains(scriptLower, "usermod") || strings.Contains(scriptLower, "groupmod") || strings.Contains(scriptLower, "chown -r") {
		level = "high"
		destructive = true
	}
	if riskSet["package-mutation"] || strings.Contains(scriptLower, "apt-get install") || strings.Contains(scriptLower, "pacman -s") {
		if level == "low" {
			level = "medium"
		}
		confirm = true
	}
	for _, token := range []string{"rm -rf", "mkfs", "dd if=", "dpkg --add-architecture", "pacman -syu", "pacman -Syu"} {
		if strings.Contains(scriptLower, strings.ToLower(token)) {
			level = "high"
			destructive = true
			confirm = true
		}
	}
	if rollback == "manual" && level == "low" && len(risks) > 0 {
		level = "medium"
	}
	if destructive || level == "high" {
		confirm = true
	}
	if entryName == "sync-uid" {
		level = "blocked"
		destructive = true
		confirm = false
	}
	return level, destructive, confirm
}

func finalizeEntry(e Entry, source string) Entry {
	e.Source = source
	e.ScriptSHA256 = scriptSHA256(e.ScriptText)
	e.State = "available"
	e.StateReason = "ready"
	e.RiskLevel, e.Destructive, e.RequiresConfirmation = classifyRisk(e.Name, e.ScriptText, e.Rollback, e.Risks)
	if e.Name == "sync-uid" {
		e.State = "blocked"
		e.StateReason = "host-managed; use users sync-id so UID/GID collision checks and ownership bounds run"
	}
	return e
}

func (e Entry) IsBlocked() bool { return e.State == "blocked" }

func (e Entry) WithMetadataState(meta map[string]any) Entry {
	state := catalogState(meta, e.Kind, e.Name)
	if e.IsBlocked() {
		return e
	}
	if len(state) == 0 {
		return e
	}
	if raw, ok := state["state"].(string); ok && raw != "" {
		e.State = raw
		e.Installed = raw == "completed"
		e.Failed = raw == "failed"
	}
	if raw, ok := state["error"].(string); ok && raw != "" {
		e.StateReason = raw
	} else if e.Installed {
		e.StateReason = "already applied to target"
	} else if e.Failed {
		e.StateReason = "last apply attempt failed"
	}
	return e
}

func catalogState(meta map[string]any, kind, name string) map[string]any {
	cs, _ := meta["catalog_state"].(map[string]any)
	ks, _ := cs[kind].(map[string]any)
	row, _ := ks[name].(map[string]any)
	return row
}

func sameFileIdentity(a, b fs.FileInfo) bool {
	if a == nil || b == nil {
		return false
	}
	if a.Mode() != b.Mode() || a.Size() != b.Size() || !a.ModTime().Equal(b.ModTime()) {
		return false
	}
	as, aok := a.Sys().(*syscall.Stat_t)
	bs, bok := b.Sys().(*syscall.Stat_t)
	if aok && bok {
		return as.Dev == bs.Dev && as.Ino == bs.Ino && as.Uid == bs.Uid && as.Gid == bs.Gid && as.Mode == bs.Mode
	}
	return true
}

func readStable(path, label string) ([]byte, error) {
	before, err := safeExternal(path, label)
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	after, err := safeExternal(path, label)
	if err != nil {
		return nil, err
	}
	if !sameFileIdentity(before, after) {
		return nil, fmt.Errorf("%s changed while being read: %s", label, path)
	}
	return data, nil
}

func safeExternalDir(path, label string) error {
	return safeExternalDirWithRole(path, label, false)
}

func safeExternalDirWithRole(path, label string, parent bool) error {
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return err
	}
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return fmt.Errorf("%s must be a real directory: %s", label, path)
	}
	// Android exposes app-private Termux trees below /data and /data/data. Those
	// system-owned ancestors are not controlled by the Termux UID, but they are
	// unavoidable trusted ancestors for app-private children. Only parent-chain
	// validation may skip owner/mode checks for them; configured manifest/script
	// directories themselves still have to be private and owned by root/current UID.
	if parent && trustedAndroidSystemAncestor(path) {
		return nil
	}
	trustedOwner := false
	if st, ok := info.Sys().(*syscall.Stat_t); ok {
		uid := uint32(os.Geteuid())
		if st.Uid != 0 && st.Uid != uid {
			return fmt.Errorf("%s has untrusted owner uid %d: %s", label, st.Uid, path)
		}
		trustedOwner = st.Uid == uid
	}
	if info.Mode().Perm()&0o022 != 0 && info.Mode()&os.ModeSticky == 0 && !trustedAndroidAppPrivateDir(path, trustedOwner) {
		return fmt.Errorf("%s must not be group/world writable unless sticky: %s", label, path)
	}
	return nil
}

func trustedAndroidSystemAncestor(path string) bool {
	clean := filepath.ToSlash(filepath.Clean(path))
	if clean == "/data" || clean == "/data/data" || clean == "/data/user" {
		return true
	}
	parts := strings.Split(strings.Trim(clean, "/"), "/")
	return len(parts) == 3 && parts[0] == "data" && parts[1] == "user" && parts[2] != ""
}

func trustedAndroidAppPrivateDir(path string, trustedOwner bool) bool {
	if !trustedOwner {
		return false
	}
	clean := filepath.ToSlash(filepath.Clean(path))
	parts := strings.Split(strings.Trim(clean, "/"), "/")
	if len(parts) >= 4 && parts[0] == "data" && parts[1] == "data" && parts[2] != "" && parts[3] == "files" {
		return true
	}
	if len(parts) >= 5 && parts[0] == "data" && parts[1] == "user" && parts[2] != "" && parts[3] != "" && parts[4] == "files" {
		return true
	}
	return false
}

func safeExternalParentChain(path, label string) error {
	abs, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	cur := filepath.Dir(abs)
	for {
		if err := safeExternalDirWithRole(cur, label+" parent", true); err != nil {
			return err
		}
		next := filepath.Dir(cur)
		if next == cur {
			return nil
		}
		cur = next
	}
}

func safeExternal(path, label string) (fs.FileInfo, error) {
	if err := safeExternalParentChain(path, label); err != nil {
		return nil, err
	}
	i, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if i.Mode()&os.ModeSymlink != 0 {
		return nil, fmt.Errorf("%s must not be a symlink: %s", label, path)
	}
	if !i.Mode().IsRegular() {
		return nil, fmt.Errorf("%s is not a regular file: %s", label, path)
	}
	if i.Mode().Perm()&0o022 != 0 {
		return nil, fmt.Errorf("%s must not be group/world writable: %s", label, path)
	}
	if st, ok := i.Sys().(*syscall.Stat_t); ok {
		uid := uint32(os.Geteuid())
		if st.Uid != 0 && st.Uid != uid {
			return nil, fmt.Errorf("%s has untrusted owner uid %d: %s", label, st.Uid, path)
		}
	}
	return i, nil
}

func simpleScriptName(text string) string {
	for _, l := range strings.Split(text, "\n") {
		p := strings.SplitN(strings.TrimSpace(l), ":", 2)
		if len(p) == 2 && p[0] == "script" {
			return strings.Trim(strings.TrimSpace(p[1]), "'\"")
		}
	}
	return ""
}

func (c Catalog) builtinEntries() ([]Entry, error) {
	if c.ResourceRoot != "" {
		dir := filepath.Join(c.ResourceRoot, c.Kind+"s")
		scripts := filepath.Join(c.ResourceRoot, c.Kind+"-scripts")
		files, err := os.ReadDir(dir)
		if err != nil {
			return nil, err
		}
		entries := []Entry{}
		for _, file := range files {
			if file.IsDir() || filepath.Ext(file.Name()) != ".yaml" {
				continue
			}
			manifest, err := os.ReadFile(filepath.Join(dir, file.Name()))
			if err != nil {
				return nil, err
			}
			scriptName := simpleScriptName(string(manifest))
			script, err := os.ReadFile(filepath.Join(scripts, scriptName))
			if err != nil {
				return nil, fmt.Errorf("manifest %s references missing script: %s", file.Name(), scriptName)
			}
			entry, _, err := parseManifest(string(manifest), file.Name(), c.Kind, string(script))
			if err != nil {
				return nil, err
			}
			entries = append(entries, finalizeEntry(entry, "builtin"))
		}
		return entries, nil
	}

	manifestDir := c.Kind + "s"
	scriptDir := c.Kind + "-scripts"
	files, err := fs.ReadDir(resourceassets.FS, manifestDir)
	if err != nil {
		return nil, err
	}
	entries := []Entry{}
	for _, file := range files {
		if file.IsDir() || filepath.Ext(file.Name()) != ".yaml" {
			continue
		}
		manifest, err := resourceassets.FS.ReadFile(manifestDir + "/" + file.Name())
		if err != nil {
			return nil, err
		}
		scriptName := simpleScriptName(string(manifest))
		script, err := resourceassets.FS.ReadFile(scriptDir + "/" + scriptName)
		if err != nil {
			return nil, fmt.Errorf("manifest %s references missing script: %s", file.Name(), scriptName)
		}
		entry, _, err := parseManifest(string(manifest), file.Name(), c.Kind, string(script))
		if err != nil {
			return nil, err
		}
		entries = append(entries, finalizeEntry(entry, "builtin"))
	}
	return entries, nil
}

func (c Catalog) externalDirs() (manifests, scripts []string) {
	if c.Config == nil {
		return nil, nil
	}
	if c.Kind == "tool" {
		return c.Config.ToolManifestDirs, c.Config.ToolScriptDirs
	}
	return c.Config.AddonManifestDirs, c.Config.AddonScriptDirs
}

func (c Catalog) externalEntries(existing map[string]bool) ([]Entry, error) {
	manifestDirs, scriptDirs := c.externalDirs()
	out := []Entry{}
	for _, dir := range manifestDirs {
		if err := safeExternalDir(dir, c.Kind+" manifest directory"); os.IsNotExist(err) {
			continue
		} else if err != nil {
			return nil, err
		}
		files, err := os.ReadDir(dir)
		if err != nil {
			return nil, err
		}
		for _, file := range files {
			if file.IsDir() || (filepath.Ext(file.Name()) != ".yaml" && filepath.Ext(file.Name()) != ".yml") {
				continue
			}
			manifestPath := filepath.Join(dir, file.Name())
			manifest, err := readStable(manifestPath, c.Kind+" manifest")
			if err != nil {
				return nil, err
			}
			scriptName := simpleScriptName(string(manifest))
			var scriptPath string
			for _, sd := range scriptDirs {
				candidate := filepath.Join(sd, scriptName)
				if _, err := os.Lstat(candidate); err == nil {
					if err := safeExternalDir(sd, c.Kind+" script directory"); err != nil {
						return nil, err
					}
					scriptPath = candidate
					break
				}
			}
			if scriptPath == "" {
				return nil, fmt.Errorf("manifest %s references missing external script: %s", manifestPath, scriptName)
			}
			script, err := readStable(scriptPath, c.Kind+" script")
			if err != nil {
				return nil, err
			}
			entry, vals, err := parseManifest(string(manifest), manifestPath, c.Kind, string(script))
			if err != nil {
				return nil, err
			}
			if existing[entry.Name] {
				return nil, fmt.Errorf("external %s manifest %s attempts to override existing catalog entry '%s'", c.Kind, manifestPath, entry.Name)
			}
			expected := strings.ToLower(strings.TrimSpace(vals["sha256"]))
			if len(expected) != 64 {
				return nil, fmt.Errorf("external manifest %s must declare a lowercase sha256 for its script", manifestPath)
			}
			for _, r := range expected {
				if !(r >= '0' && r <= '9' || r >= 'a' && r <= 'f') {
					return nil, fmt.Errorf("external manifest %s must declare a lowercase sha256 for its script", manifestPath)
				}
			}
			actual := sha256.Sum256(script)
			if hex.EncodeToString(actual[:]) != expected {
				return nil, fmt.Errorf("external manifest %s script sha256 mismatch", manifestPath)
			}
			existing[entry.Name] = true
			out = append(out, finalizeEntry(entry, "external"))
		}
	}
	return out, nil
}

func (c Catalog) LoadAll() ([]Entry, error) {
	if c.Kind != "tool" && c.Kind != "addon" {
		return nil, errors.New("catalog kind must be tool or addon")
	}
	builtins, err := c.builtinEntries()
	if err != nil {
		return nil, err
	}
	existing := map[string]bool{}
	for _, entry := range builtins {
		existing[entry.Name] = true
	}
	external, err := c.externalEntries(existing)
	if err != nil {
		return nil, err
	}
	all := append(builtins, external...)
	sort.Slice(all, func(i, j int) bool { return all[i].Name < all[j].Name })
	return all, nil
}

func (c Catalog) List(distro, category string) ([]Entry, error) {
	all, err := c.LoadAll()
	if err != nil {
		return nil, err
	}
	if category != "" {
		category, err = normalizeCategory(category)
		if err != nil {
			return nil, err
		}
	}
	out := []Entry{}
	for _, x := range all {
		if distro != "" && !x.MatchesDistro(distro) {
			continue
		}
		if category != "" && !x.MatchesCategory(category) {
			continue
		}
		out = append(out, x)
	}
	return out, nil
}
func (c Catalog) Get(name string) (Entry, error) {
	all, err := c.LoadAll()
	if err != nil {
		return Entry{}, err
	}
	for _, x := range all {
		if x.Name == name {
			return x, nil
		}
	}
	return Entry{}, fmt.Errorf("unknown %s: %s", c.Kind, name)
}
func (c Catalog) Categories(distro string) ([]string, error) {
	all, err := c.List(distro, "")
	if err != nil {
		return nil, err
	}
	m := map[string]bool{}
	for _, x := range all {
		for _, v := range x.Categories {
			m[v] = true
		}
	}
	out := []string{}
	for x := range m {
		out = append(out, x)
	}
	sort.Strings(out)
	return out, nil
}

func (c Catalog) Apply(ctx context.Context, name string, cfg config.ChrootConfig, runner *sys.Runner, reg *registry.Registry) (model.CatalogApplyResult, error) {
	if reg == nil {
		return model.CatalogApplyResult{}, errors.New("registry is nil")
	}
	rec, err := reg.Get(ctx, cfg.DistroName)
	if err != nil {
		return model.CatalogApplyResult{}, err
	}
	if rec == nil || !rec.Installed {
		return model.CatalogApplyResult{}, errors.New("chroot must be installed first")
	}
	entry, err := c.Get(name)
	if err != nil {
		return model.CatalogApplyResult{}, err
	}
	entry = entry.WithMetadataState(rec.Metadata)
	if !entry.MatchesDistro(rec.Distro) {
		return model.CatalogApplyResult{}, fmt.Errorf("%s '%s' does not support distro '%s'", c.Kind, name, rec.Distro)
	}
	if entry.IsBlocked() {
		return model.CatalogApplyResult{}, fmt.Errorf("%s '%s' is blocked: %s", c.Kind, name, entry.StateReason)
	}
	if filepath.Ext(entry.Script) != ".sh" {
		return model.CatalogApplyResult{}, fmt.Errorf("%s '%s' uses unsupported script type %q", c.Kind, name, entry.Script)
	}
	if runner != nil && runner.DryRun {
		return model.CatalogApplyResult{Kind: c.Kind, Name: name, Distro: rec.Distro, Categories: entry.Categories, Version: entry.Version, ScriptSHA256: entry.ScriptSHA256, RiskLevel: entry.RiskLevel, Rollback: entry.Rollback, Applied: false}, nil
	}
	meta := clone(rec.Metadata)
	state := map[string]any{"state": "running", "version": entry.Version, "script_sha256": entry.ScriptSHA256, "risk_level": entry.RiskLevel, "destructive": entry.Destructive, "requires_confirmation": entry.RequiresConfirmation, "risks": entry.Risks, "rollback": entry.Rollback, "updated_at": float64(time.Now().UnixNano()) / 1e9}
	setState(meta, c.Kind, name, state)
	if err = save(ctx, reg, rec, meta); err != nil {
		return model.CatalogApplyResult{}, err
	}
	env := map[string]string{"CHROOTCTL_NAME": cfg.DistroName, "CHROOTCTL_DISTRO": rec.Distro, "CHROOTCTL_USERNAME": cfg.Username}
	if !strings.HasSuffix(entry.Script, ".sh") {
		err = fmt.Errorf("%s '%s' uses unsupported embedded script type %q", c.Kind, name, entry.Script)
	} else {
		_, err = runner.Run(ctx, []string{"busybox", "chroot", cfg.ChrootBase(), "/bin/bash", "-lc", "set -e\n" + entry.ScriptText}, sys.RunOptions{ChrootEnv: true, Env: env, NoCapture: true})
	}
	latest, _ := reg.Get(ctx, cfg.DistroName)
	if latest == nil {
		latest = rec
	}
	meta = clone(latest.Metadata)
	if err != nil {
		state["state"] = "failed"
		state["error"] = truncate(err.Error(), 1000)
		setState(meta, c.Kind, name, state)
		if saveErr := save(context.WithoutCancel(ctx), reg, latest, meta); saveErr != nil {
			return model.CatalogApplyResult{}, errors.Join(err, fmt.Errorf("persist catalog failure state: %w", saveErr))
		}
		return model.CatalogApplyResult{}, err
	}
	key := c.Kind + "s"
	names := metadataList(meta[key])
	found := false
	for _, x := range names {
		if x == name {
			found = true
		}
	}
	if !found {
		names = append(names, name)
	}
	meta[key] = strings.Join(names, ",")
	state["state"] = "completed"
	setState(meta, c.Kind, name, state)
	if err = save(ctx, reg, latest, meta); err != nil {
		return model.CatalogApplyResult{}, err
	}
	return model.CatalogApplyResult{Kind: c.Kind, Name: name, Distro: rec.Distro, Categories: entry.Categories, Version: entry.Version, ScriptSHA256: entry.ScriptSHA256, RiskLevel: entry.RiskLevel, Rollback: entry.Rollback, Applied: true}, nil
}

func clone(m map[string]any) map[string]any {
	o := map[string]any{}
	for k, v := range m {
		o[k] = v
	}
	return o
}
func truncate(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}
func metadataList(v any) []string {
	if s, ok := v.(string); ok && s != "" {
		return strings.Split(s, ",")
	}
	return []string{}
}
func setState(meta map[string]any, kind, name string, row map[string]any) {
	cs, _ := meta["catalog_state"].(map[string]any)
	if cs == nil {
		cs = map[string]any{}
	}
	ks, _ := cs[kind].(map[string]any)
	if ks == nil {
		ks = map[string]any{}
	}
	ks[name] = row
	cs[kind] = ks
	meta["catalog_state"] = cs
}
func save(ctx context.Context, r *registry.Registry, rec *registry.Chroot, meta map[string]any) error {
	return r.Upsert(ctx, registry.ChrootInput{Name: rec.Name, Distro: rec.Distro, Path: rec.Path, Arch: rec.Arch, ReleaseName: rec.ReleaseName, Version: rec.Version, Phase: rec.Phase, Installed: rec.Installed, Metadata: meta})
}
