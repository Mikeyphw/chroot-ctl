# Normal CLI JSON protocol

The human-facing `chrootctl` CLI uses a versioned JSON envelope when a command declares `json` in its generated `outputModes` contract and the caller passes `--json`.

```json
{
  "schema_version": 1,
  "ok": true,
  "command": "status",
  "data": {},
  "warnings": [],
  "next_steps": [],
  "partial": false
}
```

Failures use the same envelope and stdout remains the machine-readable channel:

```json
{
  "schema_version": 1,
  "ok": false,
  "command": "events list",
  "error": {
    "code": "command_failed",
    "title": "Command failed",
    "message": "...",
    "details": {},
    "hints": [],
    "actions": [],
    "retryable": false,
    "status_code": 400
  },
  "warnings": [],
  "next_steps": [],
  "partial": false
}
```

If a batch operation completes some work before a later element fails, `partial` is true and `data` contains the completed/observed result instead of being discarded. Exit status remains non-zero.

Commands whose contract output is `raw` deliberately do not support `--json` because their stdout belongs to a child process, clipboard text, shell completion, or another raw stream. The `chrootctl app` protocol is a separate bridge protocol and is not wrapped in the normal CLI envelope.

Health commands with `healthExitPolicy = fail-on-fail`, currently `doctor` and `chroots validate-import`, return exit 1 when their checks report failure. Signal cancellation returns 130 for SIGINT and 143 for SIGTERM. Foreground child/service actions preserve the child exit status when available.
