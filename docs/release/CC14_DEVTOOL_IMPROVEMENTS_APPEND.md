# Additive Devtool cross-consumer ledger — CC14

**External evidence:** Chrootctl GitHub Actions `40120074334` (job `120949501319`), Chrootctl source commit `44e3c594b50bb1d7f4e41f8ae6eb9c984b5d4edf`, Devtool lock `445044ac4941c1542754cc19d74ebd785b5d8595`.

- **DT-CC14-01 (consumer fixed, Devtool candidate):** Hosted jobs can call Bash scripts tracked at Git mode `100644` directly, causing exit 126 after an expensive native build; current DAG planning does not validate shell-call target execute bits. Add an optional portable preflight/source-contract check for selected runner + executable shell paths, and suggest invoking the interpreter explicitly where appropriate. Preserve strict mode validation for genuinely executable runtime artifacts.
- **DT-CC14-02 (open):** Source-only `actions` gates passed despite `verify-tmux` and next `build-rclone` call sites depending on absent executable bits. Add a general Actions-adoption diagnostic for working-tree/index permissions and command invocation semantics; distinguish this failure from compiler/ELF errors in machine receipts.
- **DT-CC14-03 (open):** A failed middle DAG job skipped all downstream evidence and uploaded no failure-only diagnostics. Consider a separate, redacted failure evidence artifact, never confused with a passing release candidate.

This is a proposed append for the permanent cumulative Devtool improvements ledger, not a claim that the Devtool repository has already been changed. Hosted and device qualification remain open.
