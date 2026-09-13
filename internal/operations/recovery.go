package operations

import (
	sys "chrootctl/internal/system"
	"context"
	"time"
)

func (m *Manager) Reconcile(ctx context.Context, id string) (Record, error) {
	r, e := m.Journal.Load(id)
	if e != nil {
		return Record{}, e
	}
	if !IsActive(r.State) || r.Corrupt {
		return m.Get(id, 200)
	}
	host := identity(r)
	if host != nil && sys.ProcessIdentityMatches(*host) {
		return m.Get(id, 200)
	}
	for i := len(r.ChildProcesses) - 1; i >= 0; i-- {
		if p := sys.ProcessIdentityFromMap(r.ChildProcesses[i]); p != nil {
			sys.TerminateProcessIdentity(*p, sys.TerminateGrace)
		}
	}
	now := float64(time.Now().UnixNano()) / 1e9
	r.FinishedAt = &now
	if m.Journal.CancellationRequested(id) {
		r.State = "cancelled"
		r.ProgressText = "Cancelled"
		c := "CANCELLED"
		msg := "Cancellation was requested before the operation process exited"
		r.ErrorCode = &c
		r.Error = &msg
		r.NextSteps = []string{}
	} else {
		r.State = "interrupted"
		r.ProgressText = "Interrupted"
		c := "PROCESS_DISAPPEARED"
		msg := "The recorded operation process identity is no longer running"
		r.ErrorCode = &c
		r.Error = &msg
		r.NextSteps = []string{"Retry the operation after reviewing its last completed phase."}
	}
	if e := m.Journal.Save(&r); e != nil {
		return r, e
	}
	if e := m.Journal.ClearCancel(id); e != nil {
		return r, e
	}
	return m.Get(id, 200)
}
func (m *Manager) Recover(ctx context.Context) ([]string, error) {
	rows, e := m.Journal.ListActive(nil)
	if e != nil {
		return nil, e
	}
	out := []string{}
	for _, r := range rows {
		if !IsActive(r.State) || r.Corrupt {
			continue
		}
		before := r.State
		after, e := m.Reconcile(ctx, r.OperationID)
		if e != nil {
			return out, e
		}
		if after.State != before {
			out = append(out, r.OperationID)
		}
	}
	return out, nil
}
