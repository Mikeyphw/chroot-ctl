# CHR03 — configuration, registry identity, and privileged paths

CHR03 makes configuration and the registry fail closed before the later mutation-engine overlays add cross-process locking and crash recovery. Existing chroots now have one authoritative filesystem identity: the registry row selected for the target. Configuration remains the source of creation defaults and per-target behavioral settings, but it cannot silently relocate an existing target.

## Audit closure

Owned canonical findings implemented by this overlay:

- `D01` — target path/identity authority split between registry and config;
- `D42` — registry/SQLite model integrity checks are incomplete;
- `U104` — Android migration can overwrite the stable DB when registry inspection fails;
- `U105` — per-chroot overrides can redirect target identity/root;
- `U106` — privileged core paths accept empty/relative paths;
- `U107` — unknown config keys are silently ignored;
- `U108` — default media destinations are coupled to a literal username;
- `U109` — `~` expansion is inconsistent across path fields; and
- `U222` — snapshot-FK migration accepts an incompletely matching foreign key.

The executable roadmap ledger requires exactly **9 canonical findings / 17 source manifestations** for CHR03 while preserving the global **272 canonical / 609 source** accounting invariant.

## 1. Strict configuration contract

Configuration loading now rejects unknown top-level keys, unknown repository keys, and unknown mount-definition fields. Per-chroot overrides have a narrower allowlist: they may change behavioral settings such as username, mounts, locale, package selections, and service/catalog search paths, but they may not redefine target identity or process-global storage such as `distro_name`, `chroot_root`, database, snapshot, log, Termux, or service-state roots.

All host filesystem paths accepted by the privileged configuration boundary are normalized through one helper. They must be non-empty absolute paths after supported `~` expansion. Chroot-internal paths use the separate chroot-path validator. Mount sources and repository/service path lists use the same host-path normalization rather than retaining literal or relative `~` values.

Default media mounts are derived from the resolved username. Explicitly configured media targets remain unchanged.

## 2. Fail-closed Android state migration

Android runtime-layout migration no longer converts registry inspection errors into a zero-row count. Legacy-to-stable database promotion is allowed only after both databases were successfully inspected and the stable database was positively proven empty.

Publication uses a same-directory temporary file, file `fsync`, rename, and parent-directory `fsync`. The migration never truncates the stable database in place. An unreadable, busy, corrupt, or otherwise uninspectable stable database therefore blocks migration instead of being replaced.

## 3. Registry-backed resolved target identity

`services.Container.ResolveTarget` resolves one typed target containing:

- the selected registry record;
- the authoritative canonical `RootPath`;
- behavior configuration hydrated for that target; and
- architecture/lifecycle data from the registry record.

For an existing target, `chroots.path` owns filesystem identity. `chroot_root` is a creation default, not a relocation mechanism. After a global root default changes, existing targets continue to operate on their registered path. Runtime/controller/user construction hydrates `ChrootRoot` from the registered path's parent and pins `DistroName` to the selected registry identity.

A registered target path must be absolute, must identify exactly one chroot rather than `/`, the active management root, or a filesystem-root child, and its basename must match the selected chroot name. Existing symlink aliases are canonicalized at the registry boundary.

Snapshot source/restore staging and overwrite-import of an existing target also use the resolved registry path, preventing later workflows from reintroducing config-derived target drift.

## 4. Registry path ownership and SQLite integrity

Registry opening now requires an absolute database path. Chroot writes validate safe names and canonical identity paths. Existing data is checked during registry migration before a unique path index is installed. Ambiguous or invalid legacy rows fail migration rather than being silently rewritten to an arbitrary owner.

`Upsert` and batched upserts refuse a canonical path already owned by another target. `FindByPath` canonicalizes its lookup. `Rename` and `Delete` require exactly one affected row and return `ErrNotFound` for stale/zero-row mutations instead of reporting success.

The `chroots_updated_at` trigger now updates `NEW.name`, and rename explicitly refreshes `updated_at` using fractional-second SQLite time. Primary-key rename therefore no longer leaves stale provenance.

Snapshot foreign-key migration accepts an existing FK only when all of these match the intended relation:

- table `chroots`;
- source column `chroot_name`;
- destination column `name`;
- `ON UPDATE CASCADE`; and
- `ON DELETE CASCADE`.

Matching only the cascade actions is no longer sufficient.

## 5. Android Room schema v4

The Android cache database advances from Room schema 3 to 4. The redundant secondary `index_chroots_name` is removed because `name` is already the primary key. `MIGRATION_3_4` drops only that redundant index and preserves all data.

The exported Room v4 schema is checked into the repository. CHR03's repoctl validator recomputes its Room identity hash and verifies that the redundant index is absent and the 3→4 migration is wired into `AppContainer`.

## 6. Executable regression and release gates

CHR03 adds behavioral/configuration tests for:

- unknown-key rejection;
- identity-changing per-chroot override rejection;
- absolute/normalized privileged paths;
- username-derived media defaults with explicit-target preservation;
- fail-closed Android DB migration;
- authoritative registered-path behavior after creation-root drift;
- unsafe registered-path rejection;
- canonical registry path ownership;
- zero-row rename/delete rejection;
- rename timestamp refresh; and
- exact snapshot foreign-key repair.

`repoctl validate` and final-seal internal checks now run `ValidateConfigRegistryFoundation`, which also guards the config/registry/resolved-target/Room declarations against later drift.

## Deliberate boundaries

CHR03 does **not** claim to solve the later transaction/lifecycle findings. They remain owned by their roadmap overlays:

- global dry-run and mutation enforcement — CHR06;
- shared CLI/bridge locks and crash-recovery transaction engine — CHR06/CHR07;
- mounted/live-service checks, snapshot namespace migration, and external service-state migration during rename/remove — CHR07/CHR08/CHR09;
- sudo/wrapper/completion trust boundary and elevated-config identity — CHR04; and
- Android operation/Room behavioral reconciliation beyond this schema-integrity migration — CHR18.

The purpose of CHR03 is to make those future mutations operate on one validated identity instead of attempting transactional safety on top of ambiguous paths.
