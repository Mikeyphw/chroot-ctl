#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# CHR23 convergence gate: roadmap/source contracts, Go tests/vet, and the
# Android application seal must all pass in the same artifact validation path.
go run ./cmd/repoctl validate

if [ ! -x android/gradlew ]; then
  echo "Android Gradle wrapper is missing or not executable: android/gradlew" >&2
  exit 1
fi

(cd android && ./gradlew --no-daemon --continue \
  :chrootctlAndroidAppSeal \
  :app:testDebugUnitTest \
  :app:assembleDebug \
  :chrootctlAndroidLintConfigurationSeal)

# CHR22/CHR23 regression: prove the focused lint seal is reusable from Gradle's
# configuration cache after the complete Android gate has populated it.
(cd android && ./gradlew --no-daemon :chrootctlAndroidLintConfigurationSeal)
