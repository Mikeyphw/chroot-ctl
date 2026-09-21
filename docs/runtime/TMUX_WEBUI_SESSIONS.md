# TMUX-06 of 7 — WebUI terminal/session client

The WebUI exposes a Sessions workspace backed exclusively by the structured `chrootctl app` session API. It lists runtime/session state, creates or reconnects deterministic sessions, polls bounded capture history, requests backend PTY resize as part of capture, detaches clients, kills sessions with confirmation, and surfaces recovery/runtime failures.

No UI code executes tmux or accepts tmux argv. KernelSU transports only the chrootctl executable and allow-listed protocol requests. Terminal output is bounded and rendered as text. Sessions survive WebUI closure because tmux and persistent job state remain backend-owned.
