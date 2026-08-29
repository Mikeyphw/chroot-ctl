# Python → Go compatibility contracts

`migration/contracts/v1/` is the frozen GO00 baseline for the Python backend.
It is intentionally checked into source control so the Go rewrite has an exact,
machine-readable definition of behavior that must be retained.

The baseline contains:

- `cli.json`: the 66-node human CLI tree plus the separate `chrootctl app` CLI,
  argument metadata, defaults, choices, and help text.
- `bridge.json`: protocol-v1 limits, redaction rules, all 86 allowlisted bridge
  operations, their mode/destructive/lock metadata, and accepted payload fields.
- `persistence.json`: SQLite schema/PRAGMAs, operation journal schema and JSON
  fields, terminal/active states, and stable Android/legacy config locations.
- `foundations.json`: GO03 model field names, validation outcomes/error text,
  deterministic config defaults/overrides, structured error payloads, and
  logging behavior frozen from the Python implementation.
- `release.json`: module, Android app, bridge, compatibility-manifest, and
  current Nuitka runtime identity that the Go cutover must intentionally replace.

Regenerate after an intentional Python contract change:

```sh
PYTHONPATH=src python3 scripts/export-go-migration-contracts.py
```

Check without modifying files:

```sh
PYTHONPATH=src python3 scripts/export-go-migration-contracts.py --check
```

During the migration, any intentional contract change must update the Python
implementation, these fixtures, the relevant Go implementation/tests, and the
migration ledger in the same change. Incidental drift is a test failure.
