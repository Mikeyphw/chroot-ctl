# Phase 29D - Runtime bootstrap and responsive actions hotfix

Phase 29D repairs the real-device bootstrap failure seen after Phase 29C while keeping the Android SDK contract pinned to API 36.

## Runtime bootstrap

- The root runtime resolver now probes each Magisk and Termux candidate and selects only a bridge that returns a valid protocol-1 capabilities envelope.
- The resolver also checks Termux user installs at `~/.local/bin/chrootctl` instead of assuming the executable is installed only under `$PREFIX/bin`.
- A stale executable that prints argparse usage text is skipped rather than being accepted merely because it is executable.
- Bridge stdout and stderr are captured separately so command-line diagnostics cannot masquerade as JSON.
- Empty, timed-out, malformed, or wrong-protocol bridge output is converted into a structured bridge failure with a bounded diagnostic excerpt.
- Protocol parsing no longer silently converts the wrong `data` shape into an empty object or array.
- Capability lists remain compatible with both structured operation objects and legacy operation-name strings.

## Home recovery

The initial Home screen now renders the bootstrap error and a Retry action when the first refresh fails. It cannot remain indefinitely on “Checking root and chrootctl runtime” solely because the cache has never received its first snapshot.

## Narrow-screen actions

Button and filter groups on Home, Install, and Tools use wrapping `FlowRow` layouts. Long actions such as smoke report and evidence export move onto another line instead of collapsing into one-character columns.

## Guardrails

- `compileSdk = 37`
- `targetSdk = 36`
- `warningsAsErrors = true`
- only `OldTargetApi` remains exempted by Phase 29C
- no arbitrary shell bridge capability
- no WebView restoration
