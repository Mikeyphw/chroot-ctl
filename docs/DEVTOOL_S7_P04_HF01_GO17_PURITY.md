# S7 P04 HF01 — Correct Go consumer / GO17 purity conflict

`chroot-ctl` PR #1 source SHA `afe0c388ed219e26d6d1de7324098f52f1f5197b`
passed the S7 P04 adoption and Go source-contract workflows, but its
pre-existing dual-release job **failed** at `TestGO17RepositoryPurity` and
`TestGO17LegacyTestMapIsRetained`. The newly added
`tests/test_devtool_go_adoption.py` is incompatible with the longstanding
GO17 rule: *any committed Python source is forbidden* in this Go-native tree.

The correction uses Devtool's **native v2 overlay delete action**, not the
add/modify-only S7 P02 convenience scaffold. It transactionally deletes that
Python test, modifies P04's hosted adoption workflow to call Devtool directly,
and adds native Go adoption/purity tests. `GO17` and production code are
unchanged. The source-bound audit still verifies clean state and exact SHA.

This repair does not rerun, reroute, cancel or soften existing release workflows.
It adds one new commit to the existing PR #1 and requires all hosted jobs to
pass again on the new exact commit before P04 is considered qualified.
No Android device, local Gradle, release signing or module installation.
