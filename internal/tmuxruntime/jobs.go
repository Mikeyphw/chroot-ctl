package tmuxruntime

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const maxJobEvidenceBytes = 256 << 10

type JobState string

const (
	JobRunning   JobState = "running"
	JobRecovered JobState = "recovered"
	JobExited    JobState = "exited"
	JobLost      JobState = "lost"
	JobKilled    JobState = "killed"
)

type Job struct {
	ID        string   `json:"id"`
	SessionID string   `json:"sessionId"`
	Target    string   `json:"target"`
	Username  string   `json:"username"`
	State     JobState `json:"state"`
	CreatedAt int64    `json:"createdAt"`
	UpdatedAt int64    `json:"updatedAt"`
	Evidence  string   `json:"evidence,omitempty"`
}

type JobStore struct {
	Paths Paths
	Now   func() time.Time
}

func NewJobStore() *JobStore { return &JobStore{Paths: Resolve()} }
func (s *JobStore) root() (string, error) {
	if err := s.Paths.ValidateAuthority(); err != nil {
		return "", err
	}
	if err := EnsureState(s.Paths); err != nil {
		return "", err
	}
	return filepath.Join(s.Paths.StateRoot, "jobs"), nil
}
func (s *JobStore) now() int64 {
	if s.Now != nil {
		return s.Now().Unix()
	}
	return time.Now().Unix()
}
func validateJobID(id string) error {
	if !strings.HasPrefix(id, ManagedSessionPrefix) || strings.ContainsAny(id, "/\\\x00\r\n") {
		return errors.New("invalid managed job id")
	}
	return nil
}
func (s *JobStore) path(id string) (string, error) {
	if err := validateJobID(id); err != nil {
		return "", err
	}
	r, e := s.root()
	if e != nil {
		return "", e
	}
	return filepath.Join(r, id+".json"), nil
}
func (s *JobStore) Save(j Job) error {
	p, e := s.path(j.ID)
	if e != nil {
		return e
	}
	if j.SessionID == "" {
		j.SessionID = j.ID
	}
	if err := validateJobID(j.SessionID); err != nil {
		return err
	}
	if len(j.Evidence) > maxJobEvidenceBytes {
		j.Evidence = j.Evidence[len(j.Evidence)-maxJobEvidenceBytes:]
	}
	if j.CreatedAt == 0 {
		j.CreatedAt = s.now()
	}
	j.UpdatedAt = s.now()
	if e = os.MkdirAll(filepath.Dir(p), 0700); e != nil {
		return e
	}
	b, e := json.MarshalIndent(j, "", "  ")
	if e != nil {
		return e
	}
	tmp := p + ".tmp"
	if e = os.WriteFile(tmp, b, 0600); e != nil {
		return e
	}
	if e = os.Rename(tmp, p); e != nil {
		_ = os.Remove(tmp)
		return e
	}
	return nil
}
func (s *JobStore) Get(id string) (*Job, error) {
	p, e := s.path(id)
	if e != nil {
		return nil, e
	}
	b, e := os.ReadFile(p)
	if errors.Is(e, os.ErrNotExist) {
		return nil, nil
	}
	if e != nil {
		return nil, e
	}
	var j Job
	if e = json.Unmarshal(b, &j); e != nil {
		return nil, fmt.Errorf("decode job %s: %w", id, e)
	}
	return &j, nil
}
func (s *JobStore) List() ([]Job, error) {
	r, e := s.root()
	if e != nil {
		return nil, e
	}
	ents, e := os.ReadDir(r)
	if errors.Is(e, os.ErrNotExist) {
		return []Job{}, nil
	}
	if e != nil {
		return nil, e
	}
	out := []Job{}
	for _, ent := range ents {
		if ent.IsDir() || !strings.HasSuffix(ent.Name(), ".json") {
			continue
		}
		j, e := s.Get(strings.TrimSuffix(ent.Name(), ".json"))
		if e != nil {
			return nil, e
		}
		if j != nil {
			out = append(out, *j)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}
func (s *JobStore) Remove(id string) error {
	p, e := s.path(id)
	if e != nil {
		return e
	}
	e = os.Remove(p)
	if errors.Is(e, os.ErrNotExist) {
		return nil
	}
	return e
}
func (s *JobStore) LinkSession(sess Session) error {
	return s.Save(Job{ID: sess.ID, SessionID: sess.ID, Target: sess.Target, Username: sess.Username, State: JobRunning, CreatedAt: sess.CreatedAt})
}
func (s *JobStore) Reconcile(ctx context.Context, m *SessionManager) ([]Job, error) {
	live, e := m.List(ctx)
	if e != nil {
		return nil, e
	}
	lm := map[string]Session{}
	for _, x := range live {
		lm[x.ID] = x
	}
	jobs, e := s.List()
	if e != nil {
		return nil, e
	}
	out := make([]Job, 0, len(jobs))
	for _, j := range jobs {
		if _, ok := lm[j.SessionID]; ok {
			if j.State != JobRunning {
				j.State = JobRecovered
			}
			if ev, ce := m.Capture(ctx, j.SessionID, 200); ce == nil {
				j.Evidence = ev
			}
		} else if j.State == JobRunning || j.State == JobRecovered {
			j.State = JobLost
		}
		if e := s.Save(j); e != nil {
			return nil, e
		}
		out = append(out, j)
	}
	return out, nil
}
