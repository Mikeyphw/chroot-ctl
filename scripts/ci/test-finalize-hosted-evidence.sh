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
