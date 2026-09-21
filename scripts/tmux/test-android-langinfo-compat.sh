#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
TMP=${TMPDIR:-$ROOT/out}/tmux-langinfo-compat-test.$$
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT
cat >"$TMP/test.c" <<'EOF'
#include <langinfo.h>
#include <stdio.h>
#include <string.h>
#include "android-langinfo-compat.h"
int main(void) {
    const char *s = nl_langinfo(CODESET);
    if (strcmp(s, "ASCII") != 0 && strcmp(s, "UTF-8") != 0) return 1;
    return nl_langinfo((nl_item)9999)[0] != '\0';
}
EOF
cc -DCHROOTCTL_ANDROID_LANGINFO_COMPAT=1 -I"$ROOT/scripts/tmux" \
  "$ROOT/scripts/tmux/android-langinfo-compat.c" "$TMP/test.c" -o "$TMP/test"
"$TMP/test"
echo 'android langinfo compatibility test passed'
