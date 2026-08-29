package operations

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"chrootctl/internal/redaction"
)

const MaxEventBytes = 64 * 1024
const MaxEventCount = 2000
const MaxEventFileBytes = 4 * 1024 * 1024

type Journal struct{ Root, RecordsDir, EventsDir, CancelDir, LocksDir string }

func NewJournal(root string) (*Journal, error) {
	j := &Journal{Root: root, RecordsDir: filepath.Join(root, "records"), EventsDir: filepath.Join(root, "events"), CancelDir: filepath.Join(root, "cancel"), LocksDir: filepath.Join(root, "locks")}
	for _, d := range []string{j.RecordsDir, j.EventsDir, j.CancelDir, j.LocksDir} {
		if err := os.MkdirAll(d, 0755); err != nil {
			return nil, err
		}
	}
	return j, nil
}
func ValidateID(v string) (string, error) {
	if v == "" || len(v) > 128 || v == "." || v == ".." {
		return "", errors.New("invalid operation identifier")
	}
	for _, c := range v {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '-') {
			return "", errors.New("invalid operation identifier")
		}
	}
	return v, nil
}
func normalize(v any) any {
	b, e := json.Marshal(v)
	if e != nil {
		return fmt.Sprint(v)
	}
	var out any
	if json.Unmarshal(b, &out) != nil {
		return fmt.Sprint(v)
	}
	return out
}
func (j *Journal) Save(r *Record) error {
	id, e := ValidateID(r.OperationID)
	if e != nil {
		return e
	}
	r.SchemaVersion = SchemaVersion
	r.RefreshComplete()
	v := normalize(*r)
	v = redaction.Value(v)
	return atomicJSON(filepath.Join(j.RecordsDir, id+".json"), v)
}
func (j *Journal) Load(id string) (Record, error) {
	safe, e := ValidateID(id)
	if e != nil {
		return Record{}, e
	}
	p := filepath.Join(j.RecordsDir, safe+".json")
	b, e := os.ReadFile(p)
	if e != nil {
		return Record{}, e
	}
	r, e := DecodeRecord(b)
	if e != nil {
		return CorruptPlaceholder(safe, fmt.Sprintf("%T: %v", e, e)), nil
	}
	if r.OperationID != safe {
		return CorruptPlaceholder(safe, "ValueError: record operationId does not match its filename"), nil
	}
	return r, nil
}
func (j *Journal) ListRecent(limit int, target *string) ([]Record, error) {
	if limit < 1 {
		limit = 1
	}
	entries, e := os.ReadDir(j.RecordsDir)
	if e != nil {
		return nil, e
	}
	out := []Record{}
	for _, x := range entries {
		if x.IsDir() || filepath.Ext(x.Name()) != ".json" {
			continue
		}
		r, e := j.Load(strings.TrimSuffix(x.Name(), ".json"))
		if e != nil {
			continue
		}
		if target == nil || (r.TargetName != nil && *r.TargetName == *target) {
			out = append(out, r)
		}
	}
	sort.SliceStable(out, func(a, b int) bool { return out[a].CreatedAt > out[b].CreatedAt })
	if len(out) > limit {
		out = out[:limit]
	}
	return out, nil
}
func eventSequence(v map[string]any) int {
	if n, ok := number(v["sequence"]); ok && n > 0 {
		return int(n)
	}
	return 0
}
func boundedEvent(event map[string]any, id string) []byte {
	clean := redaction.Value(normalize(event))
	m, _ := clean.(map[string]any)
	b, _ := json.Marshal(m)
	if len(b) <= MaxEventBytes {
		return b
	}
	replacement := map[string]any{"type": fmt.Sprint(event["type"]), "operationId": id, "sequence": eventSequence(event), "timestamp": event["timestamp"], "payload": map[string]any{"message": "Event payload exceeded the journal size limit and was truncated.", "truncated": true, "originalBytes": len(b), "maxBytes": MaxEventBytes}}
	b, _ = json.Marshal(replacement)
	return b
}
func (j *Journal) AppendEvent(id string, event map[string]any) error {
	safe, e := ValidateID(id)
	if e != nil {
		return e
	}
	p := filepath.Join(j.EventsDir, safe+".jsonl")
	f, e := os.OpenFile(p, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if e != nil {
		return e
	}
	if _, e = f.Write(append(boundedEvent(event, safe), '\n')); e == nil {
		e = f.Sync()
	}
	ce := f.Close()
	if e == nil {
		e = ce
	}
	if e != nil {
		return e
	}
	if st, er := os.Stat(p); er == nil && (st.Size() > MaxEventFileBytes || eventSequence(event) > MaxEventCount) {
		return j.compact(p)
	}
	return nil
}
func (j *Journal) ReadEvents(id string, limit int) ([]map[string]any, error) {
	safe, e := ValidateID(id)
	if e != nil {
		return nil, e
	}
	if limit < 1 {
		limit = 1
	}
	if limit > MaxEventCount {
		limit = MaxEventCount
	}
	p := filepath.Join(j.EventsDir, safe+".jsonl")
	b, e := os.ReadFile(p)
	if os.IsNotExist(e) {
		return []map[string]any{}, nil
	}
	if e != nil {
		return nil, e
	}
	if len(b) > MaxEventFileBytes {
		b = b[len(b)-MaxEventFileBytes:]
	}
	lines := bytes.Split(b, []byte("\n"))
	if len(lines) > limit+1 {
		lines = lines[len(lines)-limit-1:]
	}
	out := []map[string]any{}
	for _, line := range lines {
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		var m map[string]any
		if json.Unmarshal(line, &m) == nil {
			out = append(out, m)
		}
	}
	if len(out) > limit {
		out = out[len(out)-limit:]
	}
	return out, nil
}
func (j *Journal) compact(p string) error {
	f, e := os.Open(p)
	if e != nil {
		return e
	}
	s := bufio.NewScanner(f)
	buf := make([]byte, 64*1024)
	s.Buffer(buf, MaxEventBytes*2)
	lines := [][]byte{}
	for s.Scan() {
		line := append([]byte(nil), s.Bytes()...)
		lines = append(lines, line)
		if len(lines) > MaxEventCount {
			lines = lines[1:]
		}
	}
	f.Close()
	if e = s.Err(); e != nil {
		return e
	}
	return atomicBytes(p, append(bytes.Join(lines, []byte("\n")), '\n'))
}
func (j *Journal) RequestCancel(id string) error {
	safe, e := ValidateID(id)
	if e != nil {
		return e
	}
	return os.WriteFile(filepath.Join(j.CancelDir, safe), []byte("cancel\n"), 0644)
}
func (j *Journal) CancellationRequested(id string) bool {
	safe, e := ValidateID(id)
	if e != nil {
		return false
	}
	_, e = os.Stat(filepath.Join(j.CancelDir, safe))
	return e == nil
}
func (j *Journal) ClearCancel(id string) error {
	safe, e := ValidateID(id)
	if e != nil {
		return e
	}
	e = os.Remove(filepath.Join(j.CancelDir, safe))
	if os.IsNotExist(e) {
		return nil
	}
	return e
}
func atomicJSON(path string, v any) error {
	b, e := json.Marshal(v)
	if e != nil {
		return e
	}
	return atomicBytes(path, append(b, '\n'))
}
func atomicBytes(path string, b []byte) error {
	if e := os.MkdirAll(filepath.Dir(path), 0755); e != nil {
		return e
	}
	f, e := os.CreateTemp(filepath.Dir(path), "."+filepath.Base(path)+".*")
	if e != nil {
		return e
	}
	name := f.Name()
	defer os.Remove(name)
	if e = f.Chmod(0644); e == nil {
		_, e = f.Write(b)
	}
	if e == nil {
		e = f.Sync()
	}
	ce := f.Close()
	if e == nil {
		e = ce
	}
	if e != nil {
		return e
	}
	return os.Rename(name, path)
}
