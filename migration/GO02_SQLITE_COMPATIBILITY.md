# GO02 SQLite compatibility gate

GO02 proves that the Go migration can use the existing chrootctl SQLite registry without a format fork or destructive conversion.

## Invariants

- Python remains the production registry owner during this phase.
- The compatibility database is created by the real `ChrootRegistry` implementation.
- Go opens the same file with standard SQLite locking and WAL semantics.
- Go must preserve `busy_timeout=5000`, `foreign_keys=ON`, `journal_mode=WAL`, and `synchronous=FULL`.
- The `snapshots.chroot_name -> chroots.name` foreign key must retain `ON UPDATE CASCADE ON DELETE CASCADE`.
- Python-written rows must survive Go writes and Go-written rows must be readable by Python.
- `PRAGMA integrity_check` and `PRAGMA foreign_key_check` must stay clean after the round trip.
- No production `cmd/chrootctl` registry path is switched to Go in GO02.

## Driver decision

The compatibility spike uses `github.com/mattn/go-sqlite3` and cgo. This intentionally prioritizes standard SQLite file locking and WAL interoperability with Python's `sqlite3` over a cgo-free build. The driver is isolated under `internal/sqlitecompat` until the registry port lands in GO04.

The shipping Go scaffold remains independently buildable with `CGO_ENABLED=0` because it does not import the compatibility package yet.

## Gate

Run:

```sh
bash scripts/validate-go02-sqlite-compat.sh
```

The gate performs:

1. Python creates a real registry database.
2. Go tests/vet run.
3. Go probes and mutates the Python database transactionally.
4. Python reopens and verifies the Go mutation and both FK cascade directions.
5. The original `cmd/chrootctl` Android/arm64 CGO-free compile still passes.
6. The SQLite helper is cross-compiled for Android/arm64 with cgo when an Android compiler is available. Set `CHROOTCTL_GO02_REQUIRE_ANDROID=1` to make absence of that compiler fatal.

CI installs NDK `29.0.14206865` and requires the Android cgo build.
