# TMUX-05 of 7 — persistent backend jobs and recovery

TMUX sessions now have a persistent backend job record under the authoritative tmux state root. A successful session creation is atomically linked to a job; if persistence fails the newly-created session is killed so no untracked backend job is left behind.

`JobStore.Reconcile` is the restart/reboot recovery boundary. It compares persisted jobs with live managed tmux sessions, marks surviving work as recovered, marks disappeared work as lost, and refreshes bounded evidence from the pane. Evidence is capped at 256 KiB and tmux capture is independently bounded.

Records use 0600 files and atomic rename. IDs remain restricted to chrootctl-managed session IDs, preventing path traversal. `Remove` provides explicit cleanup semantics and is idempotent for already-absent records. This layer never accepts raw shell or arbitrary tmux argv.
