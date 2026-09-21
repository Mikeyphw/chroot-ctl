# TMUX-04 CLI and app protocol parity

TMUX-04 exposes the backend session manager through the frozen app bridge and the human/JSON CLI. The app bridge now contains `sessions.list`, `sessions.get`, `sessions.create`, `sessions.capture`, `sessions.detach`, `sessions.kill`, `sessions.reconcile`, and the existing `sessions.runtime` capability.

The generic bridge remains structured and allowlisted: `arbitraryShell` is still `false`; callers provide chroot/user/session identifiers and bounded dimensions or capture limits, never tmux argv or shell text. Create, detach, kill, and reconcile are operation-mode requests so they follow the existing operation journal/progress conventions. List, get, capture, and runtime are queries.

The CLI mirrors the same backend service as `chrootctl sessions list|get|create|capture|detach|kill|reconcile|runtime`. Mutating commands retain the CLI privilege contract. `sessions create` resolves an installed chroot and validated user before the service constructs the login invocation; it does not accept arbitrary command text.
