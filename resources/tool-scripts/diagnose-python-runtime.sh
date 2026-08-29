#!/bin/bash
set -eu
if command -v python3 >/dev/null 2>&1; then
  python_version=$(python3 --version 2>&1 | awk '{print $2}')
elif command -v python >/dev/null 2>&1; then
  python_version=$(python --version 2>&1 | awk '{print $2}')
else
  python_version=missing
fi
printf 'python=%s\n' "$python_version"
printf 'platform=%s\n' "$(uname -a 2>/dev/null || uname -srm)"
for key in CHROOTCTL_NAME CHROOTCTL_DISTRO CHROOTCTL_USERNAME; do
  eval "value=\${$key-}"
  printf '%s=%s\n' "$key" "$value"
done
