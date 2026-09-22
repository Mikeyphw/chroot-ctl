# CUX-05 Terminal, Jobs and Activity

CUX-05 turns the existing tmux/session and persistent-operation foundations into first-class operational UX. Terminal retains backend-owned create/reconnect/capture/input/detach/kill flows. Jobs shows active and recovery-needed persistent work. Activity is now a distinct unified operation-history surface instead of an alias for Logs, with filters for failures and completed work. Operation cards preserve backend IDs and open the existing detail/retry/cancel/reconcile flow, so state survives navigation and WebUI reconnects.

This overlay is intentionally applied with `--no-validate`; CUX-04 is the authoritative midpoint gate and CUX-07 is the final detailed roadmap gate.
