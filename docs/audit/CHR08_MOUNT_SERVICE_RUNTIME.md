# CHR08 — Mount, session & service runtime

CHR08 closes the mount/session/service-runtime and truthful-health tranche of the master audit on top of CHR07.

## Audit closure

Owner set:

- D13 — Status/doctor/health can report false success or hide failures (14 source manifestations)
- D25 — Service-unit lifecycle/state/journal semantics are not reliable (10)
- D26 — Mount/session lifecycle is non-transactional or misvalidated (7)
- U116–U132 (17 standalone manifestations)
- U225 — `/proc/mounts` parser does not decode mount escapes (1)

Total: **21 canonical findings / 49 source manifestations**.

D12 remains owned by CHR16. CHR08 repairs service-journal correctness needed by D25, but does not claim the later log retention/filter/follow root-cause closure.

## Mount-table authority and transactional mounts

`internal/system` now exposes a detailed mount model rather than reducing `/proc/mounts` to source/target pairs. Fields use proc-mount escape decoding (`\\040`, `\\011`, `\\012`, `\\134`), and options/filesystem type remain available to callers.

`internal/controller` consumes this evidence fail-closed:

- duplicate configured targets are rejected before mounting;
- an already occupied target is accepted only when its source/type/options match the expected mount;
- a read-only bind is not considered satisfied when the observed mount is writable;
- mount-table read failure is an error, not an empty/unmounted world view;
- each mount created by the current call is tracked and rolled back in reverse order if a later mount fails;
- a failed read-only remount rolls back its preceding bind;
- TTY/device setup does not stack child device mounts underneath an already authoritative `/dev` bind.

The historical `/data` `dev,suid` workaround is now a scoped transaction. CHR08 records the relevant original `/data` mount flags, applies the temporary remount only when configured, and restores the previous flags before `Mount()` returns. Failure to inspect, alter, or restore that global mount is surfaced rather than discarded.

## Session construction

Interactive `start` and explicit `exec` now share controller session construction. Shell resolution uses the same fallback path for both surfaces. `exec` validates that a command exists before privileged mount/session preparation, eliminating a side-effecting error path for an empty command.

X11 host preparation is no longer optimistic. Required launch/tool failures are returned explicitly instead of silently treating missing/failed `am`, PulseAudio, or `termux-x11` components as successful preparation.

Existing-chroot callers that require an unmounted target now use checked mount evidence. CRUD, snapshot, transfer/import/export, and storage/safety paths cannot interpret an unreadable or mismatched mount table as safely unmounted.

## Service runtime contract

`internal/services/units.go` now applies one strict service-unit contract:

- unit names have a non-colliding validated grammar;
- malformed boolean and restart-policy values are errors;
- `Environment=` uses quoted-field parsing, preserving values containing spaces;
- privileged unit execution checks the service directory and file trust boundary instead of executing writable/untrusted unit definitions;
- services execute with the sanitized chroot environment (`ChrootEnv: true`);
- `ExecStop` receives the service environment and a bounded execution deadline;
- the journal includes lifecycle/preflight information and read failures propagate;
- `[Install] Enabled=true` is parsed and has deliberate default enablement semantics;
- boot-target membership is distinct from current enabled state;
- unknown required managed `.service` dependencies fail closed instead of being silently treated as external requirements.

### Process-state durability

Background start no longer returns optimistic `running` immediately after spawn. It confirms process identity/liveness and cleans up the process if durable identity-state persistence fails.

Stop/restart use verified process identity and process-tree termination. Identity state is deleted only after termination is proven; a survivor cannot be reported as stopped. Status exposes explicit stale/failed conditions instead of flattening uncertain state to stopped/running. List surfaces per-unit status failures rather than discarding them.

The CLI's documented `SERVICE` and `CHROOT SERVICE` addressing is normalized before dispatch and checked against unit `Chroot=` metadata.

## Truthful status and doctor

CHR08 removes health paths that could turn missing evidence into PASS:

- `SystemService.Status` uses checked mount evidence;
- target doctor requires all required mounts to match, rather than treating any mounted count as healthy;
- normal doctor includes host-readiness checks as advertised;
- host readiness probes do not create directories merely to determine writability;
- registry failures are represented as failed diagnostic evidence;
- log-file checks validate type/access rather than accepting a successful `stat` alone;
- hard status/doctor failures set the CLI exit code non-zero.

Foreign-architecture install/catalog/package paths now require an executable foreign-architecture runtime before privileged chroot execution. Clipboard readiness requires the generated wrapper provenance marker. Android operation records can be explicitly marked stale, foreground operation recovery preserves nonterminal work instead of converting stream interruption into terminal success/failure, and Home health includes release-readiness evidence.

Localization/RTL readiness remains an explicit pending release proof; CHR20 retains ownership of the final adaptive/accessibility/i18n release seal.

## Executable closure seal

`repoctl validate` and final-seal execute `ValidateMountServiceRuntime`. The source seal requires the detailed mount parser, transactional controller primitives, checked diagnostics, strict unit/runtime semantics, Android reconciliation markers, and the exact audit ledger ownership above. `ValidateAuditCoverage` enforces **21 canonical / 49 source** closure and also asserts that D12 is still not claimed by CHR08.

## Validation performed during overlay construction

The construction environment cannot download `github.com/mattn/go-sqlite3@v1.14.50`. A compile-only local shim was therefore used only while compiling packages that import the SQLite layer; it is not part of the overlay and `go.mod` was restored afterward.

Passed locally:

- `go test ./internal/system ./internal/controller ./internal/clipboard ./internal/repoctl -count=1`
- `go run ./cmd/cli-contract-gen --check`
- compile of every Go package with `go test -run '^$' ./...`
- `go vet ./...`
- CHR08 repoctl source seal and exact audit-coverage seal

The real repository validator remains wired to the normal SQLite driver and will run on the user's Termux repository at the planned validation gates.
