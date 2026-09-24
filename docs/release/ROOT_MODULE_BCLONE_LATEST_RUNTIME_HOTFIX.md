# Root module latest-bclone runtime hotfix

The optional remote-transfer runtime now comes from the official `BenjiThatFoxGuy/bclone` project rather than upstream rclone release archives.

- The build does **not** pin a bclone version. `scripts/install-rclone-android-runtime.sh` resolves GitHub `releases/latest` every time it needs to build a runtime and then uses that immutable release tag for the source archive.
- The resolved tag is validated before it is used in a URL or cache path.
- The source archive is path-safety checked and cached with a local SHA-256 integrity sidecar.
- Dependencies are vendored from the resolved release using its checked-in `go.sum`, then the Android build is forced through `-mod=vendor`.
- The resulting executable remains `runtime/arm64-v8a/rclone` because bclone intentionally preserves rclone CLI/config and Go-module compatibility.
- Existing AArch64 PIE, Android/arm64, CGO, version-output, and 16 KiB PT_LOAD checks remain mandatory.

The WebUI copy-error action also uses only the standard Clipboard API. The retired `document.execCommand` fallback is intentionally absent so the CUX-07 no-raw-execution seal remains authoritative.
