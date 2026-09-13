# CHR04 — Privilege, wrapper & completion trust boundary

Status: implemented

CHR04 closes the audit-owned privilege/trust set: D07, D08 and U202–U211 (12 canonical findings / 22 source manifestations). It also repairs the `wrapper install --dry-run` manifestation of D02, recorded as CHR04 supporting work without closing the broader D02 mutation-boundary finding.

## Generated privilege authority

Root requirement remains generated from `migration/contracts/v1/cli.json`. `chroots rename` is `mutate-root`, `chroots diff` is `read-root`, `__complete` is non-root/read-only, and `wrapper install` is explicitly a mutation. The CLI no longer uses a parallel privilege table.

Root re-exec now consumes the exact `cli.Run` argv and I/O streams. Before elevation, an implicit config path is frozen into argv so conventional sudo cannot switch the command from the invoking user's config to root's HOME-derived config. Dry-run never enters the root re-exec path; it continues through normal validation/dispatch with the dry-run service context.

Root providers are fixed trusted paths rather than caller-PATH lookups. Android `su -c` construction uses the in-process Go quoting routine and installs a curated root PATH. Conventional sudo uses a fixed sudo and env path. Process-start failures are returned as errors instead of being hidden as an exit-code-only success path.

## Thin `chc` launcher

The generated wrapper is now intentionally dumb. It never calls `sed`, never evaluates `command -v`, never copies caller PATH into root, never runs `su`, and never executes `modules_update`. It checks only active/root-managed runtime locations and execs the selected Go CLI unchanged. Privilege decisions therefore remain in one generated Go contract.

Wrapper installation is provenance-aware and failure-preserving:

- generated wrapper/completion files carry versioned markers;
- unrelated existing files are refused unless `--force` is explicit;
- the currently executing chrootctl path cannot be replaced;
- wrapper names use `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`;
- custom wrapper aliases are registered in generated zsh completion;
- all outputs are staged before publication and existing outputs are backed up for rollback;
- dry-run performs validation/planning but creates no directory or file.

## Read-only completion

`__complete` is handled before the normal services container exists. It uses `config.LoadReadOnly` and `registry.OpenReadOnly` (`mode=ro`, query-only), performs no Android layout migration, no schema migration, no logging setup and no operation-state creation. When root-owned Android state cannot be read, it degrades to conservative read-only filesystem/catalog discovery rather than escalating.

Generated zsh completion carries `--config` and `--name` into dynamic queries, so user completion retains the selected chroot context. Because `chc` no longer escalates, pressing TAB through the wrapper is also non-root.

## Android root-runtime trust

RootService runtime resolution no longer honors `CHROOTCTL_EXECUTABLE` and no longer probes Termux-writable executable candidates as UID 0. Non-module fallbacks are limited to root-managed locations and are rechecked for root ownership, canonical non-symlink identity, executable mode and absence of group/world write permissions.

`BridgeProcess` clears the inherited environment and installs a curated root environment. Its PATH contains only `/data/adb/chrootctl/bin` plus Android system/vendor/product binary directories; Termux home/local/prefix paths are excluded.

Pending `modules_update` directories remain diagnostic-only and are never executable candidates.

## Regression coverage

CHR04 adds executable tests/seals for:

- dry-run wrapper zero-write behavior;
- wrapper provenance/force collision handling;
- strict wrapper-name validation;
- custom completion aliases;
- thin-launcher source trust invariants;
- read-only dynamic completion with no registry/state creation;
- selected-target user completion;
- generated completion propagation of `--config`/`--name`;
- exact argv preservation and dry-run privilege re-exec fail-closed behavior;
- Android root environment and trusted-runtime metadata policy;
- repoctl source-level trust-boundary seal;
- exact CHR04 roadmap ownership/source count.

The next overlay, CHR05, owns process-tree cancellation/timeout and the remaining RootService/Binder transport mechanics; CHR06 owns the universal mutation boundary, including the remaining D02 manifestations.
