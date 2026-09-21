#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK="$ROOT/out/tmux-glob-compat-test.$$"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/fixtures"

: > "$WORK/fixtures/b.cfg"
: > "$WORK/fixtures/a.cfg"
: > "$WORK/fixtures/.hidden.cfg"
: > "$WORK/fixtures/space name.conf"

cat > "$WORK/test.c" <<'C'
#include <glob.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "android-glob-compat.h"

static void
expect(int condition, const char *message)
{
    if (!condition) {
        fprintf(stderr, "android glob compat: %s\n", message);
        exit(1);
    }
}

int
main(int argc, char **argv)
{
    glob_t g = {0};
    char pattern[4096];
    int rc;

    if (argc != 2)
        return 2;

    snprintf(pattern, sizeof pattern, "%s/*.cfg", argv[1]);
    rc = glob(pattern, 0, NULL, &g);
    expect(rc == 0, "wildcard lookup failed");
    expect(g.gl_pathc == 2, "hidden files must not match '*' and two cfg files are expected");
    expect(strstr(g.gl_pathv[0], "a.cfg") != NULL, "results must be sorted");
    expect(strstr(g.gl_pathv[1], "b.cfg") != NULL, "results must be sorted");
    globfree(&g);

    snprintf(pattern, sizeof pattern, "%s/space\\ name.conf", argv[1]);
    rc = glob(pattern, 0, NULL, &g);
    expect(rc == 0 && g.gl_pathc == 1, "escaped literal lookup failed");
    globfree(&g);

    snprintf(pattern, sizeof pattern, "%s/*.missing", argv[1]);
    rc = glob(pattern, 0, NULL, &g);
    expect(rc == GLOB_NOMATCH, "missing wildcard must return GLOB_NOMATCH");
    globfree(&g);
    return 0;
}
C

CLANG=${CHROOTCTL_TMUX_HOST_CLANG:-$(command -v clang || true)}
[ -n "$CLANG" ] || { echo "native clang is required for Android glob compatibility test" >&2; exit 127; }
"$CLANG" -Wall -Wextra -Werror \
  -DCHROOTCTL_ANDROID_GLOB_COMPAT=1 \
  -I"$ROOT/scripts/tmux" \
  "$ROOT/scripts/tmux/android-glob-compat.c" "$WORK/test.c" \
  -o "$WORK/test"
"$WORK/test" "$WORK/fixtures"
echo "Android API<28 glob compatibility test passed"
