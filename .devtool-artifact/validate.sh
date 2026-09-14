#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# CHR24 optimized convergence gate: keep the full Go roadmap/source validation,
# then ask Gradle for the single Android aggregate.  The aggregate already
# depends on stable-toolchain verification, debug unit tests, debug packaging,
# and the deterministic lint-configuration seal, so listing those leaf tasks as
# additional command-line roots only creates avoidable graph/phase churn.
go run ./cmd/repoctl validate

if [ ! -x android/gradlew ]; then
  echo "Android Gradle wrapper is missing or not executable: android/gradlew" >&2
  exit 1
fi

(cd android && ./gradlew --no-daemon --continue :chrootctlAndroidAppSeal)

# CHR22/CHR23/CHR24 regression: prove the focused lint seal is reusable from
# Gradle's configuration cache after the complete Android gate has populated it.
(cd android && ./gradlew --no-daemon :chrootctlAndroidLintConfigurationSeal)
