#!/usr/bin/env bash
set -euo pipefail
# Finalize after Devtool has emitted its machine run receipt, *not* in a DAG node.
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
cd "$ROOT"
dir=${1:-out/hosted-evidence}
[[ -d "$dir" && ! -L "$dir" ]] || { echo 'FAIL_HOSTED_FINALIZE: unsafe evidence directory' >&2; exit 1; }
dir=$(cd -- "$dir" && pwd -P)
required=(
  chrootctl-standard-arm64.zip chrootctl-standard-arm64.zip.sha256
  chrootctl-rclone-arm64.zip chrootctl-rclone-arm64.zip.sha256
  release-evidence.json release-qualification.json build-context.json
  devtool-plan.json devtool-run.json
)
for name in "${required[@]}"; do
  path="$dir/$name"
  [[ -f "$path" && ! -L "$path" && -s "$path" ]] || { echo "FAIL_HOSTED_FINALIZE: missing, empty or unsafe $name" >&2; exit 1; }
done
# A checksum over arbitrary JSON is not proof of a completed Devtool DAG.
# Require all 19 source-bound hosted jobs, an exact plan, and successful results.
GOTOOLCHAIN=local go run scripts/ci/verify-devtool-receipt.go \
  --plan "$dir/devtool-plan.json" --run "$dir/devtool-run.json" --repo "$ROOT"
[[ -f "$dir/SHA256SUMS" && ! -L "$dir/SHA256SUMS" ]] || { echo 'FAIL_HOSTED_FINALIZE: missing original checksum index' >&2; exit 1; }
(cd "$dir" && sha256sum --check --status SHA256SUMS) || { echo 'FAIL_HOSTED_FINALIZE: original checksum mismatch' >&2; exit 1; }
# Do not silently index arbitrary extra files (e.g. stale outputs from a prior build).
while IFS= read -r -d '' path; do
  name=${path#"$dir/"}
  [[ "$name" == SHA256SUMS ]] && continue
  found=0
  for allowed in "${required[@]}"; do [[ "$name" == "$allowed" ]] && { found=1; break; }; done
  [[ $found -eq 1 ]] || { echo "FAIL_HOSTED_FINALIZE: unexpected evidence path $name" >&2; exit 1; }
done < <(find "$dir" -mindepth 1 -print0)
tmp=$(mktemp "$dir/.SHA256SUMS.XXXXXX")
trap 'rm -f -- "$tmp"' EXIT
(cd "$dir" && sha256sum "${required[@]}") > "$tmp"
mv -f -- "$tmp" "$dir/SHA256SUMS"
trap - EXIT
(cd "$dir" && sha256sum --check --status SHA256SUMS) || { echo 'FAIL_HOSTED_FINALIZE: new checksum mismatch' >&2; exit 1; }
echo PASS_CC11_ALL_HOSTED_EVIDENCE_CHECKSUMMED
