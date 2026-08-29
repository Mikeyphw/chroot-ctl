#!/bin/sh
set -eu

echo "sync-uid is host-managed by chrootctl and cannot be executed as a raw catalog script." >&2
echo "Use the chrootctl user/UID sync operation so host UID/GID collision checks and ownership bounds are enforced." >&2
exit 64
