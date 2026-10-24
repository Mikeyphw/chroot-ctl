#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
mk_fixture() {
  d=$(mktemp -d "${TMPDIR:-/tmp}/chrootctl-cc11.XXXXXX")
  for n in chrootctl-standard-arm64.zip chrootctl-standard-arm64.zip.sha256 \
           chrootctl-rclone-arm64.zip chrootctl-rclone-arm64.zip.sha256 \
           release-evidence.json release-qualification.json build-context.json \
           devtool-plan.json devtool-run.json; do
    printf 'fixture contents for %s\n' "$n" > "$d/$n"
  done
  # Real-shaped, successful 19-node Devtool plan and machine fixtures.
  printf '{"ok":true,"command":"plan","exit_code":0,"data":{"action":"ci-release","targets":["chrootctl_hosted_release"],"summary":{"node_count":19,"target_local_job_count":19,"repository_job_count":0}}}' > "$d/devtool-plan.json"
  {
    printf '{"schema_version":1,"machine_schema_version":2,"ok":true,"command":"invoke","repo":"%s","exit_code":0,"totals":{"failed":0,"errors":0,"skipped":0},"workflow":{"targets":["chrootctl_hosted_release"],"workflows":["ci-release"],"summary":{"target_local_job_count":19,"repository_job_count":0},"nodes":[' "$ROOT"
    comma=''
    for node in preflight restore-go restore-tmux build-tmux verify-tmux build-rclone build-repoctl test-webui test-go test-tmux lint-native lint-go test-verifier test-skybind-consumer test-edition-upgrade test-source build-editions verify-editions receipt; do
      printf '%s{"key":"chrootctl_hosted_release.ci-release.%s","target":"chrootctl_hosted_release","workflow":"ci-release","state":"passed","result_count":1}' "$comma" "$node"
      comma=,
    done
    printf ']},"results":['
    comma=''
    for node in preflight restore-go restore-tmux build-tmux verify-tmux build-rclone build-repoctl test-webui test-go test-tmux lint-native lint-go test-verifier test-skybind-consumer test-edition-upgrade test-source build-editions verify-editions receipt; do
      printf '%s{"status":"ok","exit_code":0}' "$comma"; comma=,
    done
    printf ']}'
  } > "$d/devtool-run.json"
  (cd "$d" && sha256sum *.zip > SHA256SUMS)
}
mk_fixture
trap 'rm -rf -- "${d:-}"' EXIT
"$ROOT/scripts/ci/finalize-hosted-evidence.sh" "$d" >/dev/null
(cd "$d" && sha256sum --check --status SHA256SUMS)
[[ $(wc -l < "$d/SHA256SUMS") -eq 9 ]] || { echo 'incomplete evidence index' >&2; exit 1; }
printf 'corrupt\n' > "$d/build-context.json"
if (cd "$d" && sha256sum --check --status SHA256SUMS); then echo 'unsealed context change accepted' >&2; exit 1; fi
rm -rf -- "$d"
mk_fixture
rm -f -- "$d/devtool-run.json"
if "$ROOT/scripts/ci/finalize-hosted-evidence.sh" "$d" >/dev/null 2>&1; then echo 'missing machine receipt accepted' >&2; exit 1; fi
rm -rf -- "$d"
mk_fixture
ln -sf release-evidence.json "$d/extra-link"
if "$ROOT/scripts/ci/finalize-hosted-evidence.sh" "$d" >/dev/null 2>&1; then echo 'unexpected linked output accepted' >&2; exit 1; fi
printf '%s\n' PASS_CC11_COMPLETE_EVIDENCE_FINALIZER_AND_NEGATIVES

rm -rf -- "$d"
mk_fixture
sed -i 's/"state":"passed"/"state":"waiting"/' "$d/devtool-run.json"
if "$ROOT/scripts/ci/finalize-hosted-evidence.sh" "$d" >/dev/null 2>&1; then
  echo 'nonterminal Devtool receipt accepted' >&2; exit 1
fi
printf '%s\n' PASS_CC12_SEMANTIC_RECEIPT_REJECTS_INCOMPLETE_DAG
