#!/usr/bin/env bash
# Shared identity checks for the pinned Android rclone runtime.
# This file is sourced by the installer and by focused regression tests.

chrootctl_rclone_validate_build_info() {
    local build_info=${1:-}
    local failed=0
    if ! grep -Fq 'github.com/rclone/rclone' <<<"$build_info"; then
        printf 'missing rclone main-module identity in Go build metadata\n' >&2
        failed=1
    fi
    if ! grep -Fq 'GOOS=android' <<<"$build_info"; then
        printf 'missing GOOS=android in Go build metadata\n' >&2
        failed=1
    fi
    if ! grep -Fq 'GOARCH=arm64' <<<"$build_info"; then
        printf 'missing GOARCH=arm64 in Go build metadata\n' >&2
        failed=1
    fi
    if ! grep -Fq 'CGO_ENABLED=1' <<<"$build_info"; then
        printf 'missing CGO_ENABLED=1 in Go build metadata\n' >&2
        failed=1
    fi
    [[ $failed -eq 0 ]]
}

chrootctl_rclone_validate_version_output() {
    local version_output=${1:-}
    local expected_version=${2:-}
    local failed=0
    if ! grep -Fqx "rclone v${expected_version}" <<<"$version_output"; then
        printf 'rclone version output does not contain the exact expected version line: rclone v%s\n' "$expected_version" >&2
        failed=1
    fi
    if ! grep -Eq '(^|[[:space:]])os/type:[[:space:]]*android([[:space:]]|$)' <<<"$version_output"; then
        printf 'rclone version output does not report os/type: android\n' >&2
        failed=1
    fi
    if ! grep -Eq '(^|[[:space:]])os/arch:[[:space:]]*arm64([[:space:]]|$)' <<<"$version_output"; then
        printf 'rclone version output does not report os/arch: arm64\n' >&2
        failed=1
    fi
    [[ $failed -eq 0 ]]
}
