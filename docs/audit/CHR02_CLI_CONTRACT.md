# CHR02 — CLI contract as single source of truth

Baseline: CHR01 commit `4ea3e6a`, applied from `chrootctl_chr01_build_devtool_foundation_v1.tar.gz`.

## Closure scope

CHR02 owns 12 canonical findings representing 37 source manifestations:

- D09 — parser/help/docs/completion/capability drift (14 manifestations)
- D10 — fragmented JSON/error/output protocol (12 manifestations)
- D43 — child exit / partial-result loss (2 manifestations)
- U100–U103 — version, install error wording, Android `su` escalation parity, numeric bounds
- U212–U216 — early JSON guard bypass, doctor exit truth, signal exit truth, explicit output modes, per-command JSON capability

The roadmap ledger marks only this CHR02-owned set implemented. D02/D07/D11 and the completion/wrapper trust-boundary findings remain assigned to later overlays even where CHR02 establishes metadata those overlays will consume.

## Contract authority

`migration/contracts/v1/cli.json` now declares 74 normal CLI nodes (including first-class `version`) and 8 globals. Each command carries handler identity, output modes, stream mode, privilege, mutability, health exit policy, mutual-exclusion/require-one groups, JSON incompatibilities, privilege override rules, completion exposure, and completion hints. Integer arguments can declare minimum/maximum bounds.

`cmd/cli-contract-gen` deterministically generates `internal/clicontract/specs_generated.go` and `docs/cli/COMMAND_REFERENCE.md`. `repoctl validate` executes the generator in check mode through `contractgen.Check`; source-contract edits that are not regenerated fail validation.

Parser, help, dispatch-handler routing, privilege resolution, JSON support, and shell completion all consume the generated contract. The old `machineReadable`, `requiresRoot`, static `CommandNodes`, and embedded stale zsh completion authorities are removed.

## Parser and help

Global options are accepted before or after a command and support `--option=value`. Command-local options win spelling collisions after the command, preserving `magisk render --name` as a startup-target selector rather than accidentally setting the global target. Remainder commands stop chrootctl option parsing once child argv begins.

Help is resolved before required-argument/group validation. Required/repeatable syntax is rendered accurately, mutual-exclusion constraints are shown, integer bounds are enforced, and action groups reject ambiguous combinations instead of silently selecting a branch.

README examples and claims were reconciled with native behavior. The generated command reference is the exhaustive command/options reference.

## Result protocol

Normal `--json` uses one schema-v1 envelope for success and failure. The same structured application-error shape is used inside the envelope. Strings are JSON data rather than raw fragments. Commands with raw stdout explicitly declare `raw` and reject `--json`; the app bridge remains a separate `bridge` output surface.

Human output now uses display maps or deterministic key/value/list rendering instead of unconditional title-plus-indented-JSON. Output write failures from the normal renderer are propagated.

Partial-result errors retain completed batch work for services, catalog application, installer catalog stages, and boot startup. Foreground service failures retain the service result and exact child exit code.

`doctor` and `chroots validate-import` set non-zero health exit status on failed checks. The top-level executable installs SIGINT/SIGTERM cancellation with stable 130/143 exit mapping.

## Privilege and version convergence

`version` and global `--version` are both contract actions. Root requirement is resolved from command/action metadata rather than a parallel CLI switch. Auto-escalation now prefers `sudo` when present and falls back to Android/Magisk/KernelSU `su -c`; CHR04 still owns hardening of the privileged wrapper/completion trust boundary and mutable-PATH concerns.

## Executable seals

`ValidateCLIContractFoundation` checks command/global counts, metadata completeness, parser invariants, action-specific privilege, unsupported early JSON paths, and generated completion coverage. The completion test sweeps every completion-exposed contract command and option rather than asserting a handful of legacy tokens.

The CHR01 audit-ledger validator was extended so CHR02 must account for exactly 12 canonical findings and 37 source manifestations while preserving the global 272 canonical / 609 source invariants.

## Validation strategy

This overlay contains no Android source changes. Its artifact validator runs the Go contract generator check and `go run ./cmd/repoctl validate`. In the ChatGPT build environment, the repository compiles across all Go packages using an offline compile-only sqlite3 stub because the real `github.com/mattn/go-sqlite3` source is not cached and outbound module download is unavailable. Focused CHR02 packages/tests run against that compile environment; the real sqlite-backed full suite is delegated to Devtool on the Termux repository.
