#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x android/gradlew ]; then
  echo "Android Gradle wrapper is missing or not executable: android/gradlew" >&2
  exit 1
fi

(cd android && ./gradlew --no-daemon --continue :chrootctlAndroidAppSeal :app:testDebugUnitTest :app:assembleDebug :chrootctlAndroidLintConfigurationSeal)
