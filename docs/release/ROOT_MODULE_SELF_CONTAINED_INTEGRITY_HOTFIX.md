# Root module self-contained integrity hotfix — 1.3.5 / 20

This hotfix removes the runtime dependency on a host `gpg` executable from rootfs signature verification.

- Ubuntu `SHA256SUMS.gpg` is verified in-process with OpenPGP against Canonical's Ubuntu archive keyring, filtered to the pinned Ubuntu CD Image signing fingerprint.
- Arch Linux ARM rootfs signatures use the same in-process verifier with the pinned Arch Linux ARM build-system fingerprint.
- Remote key material is size-limited, parsed as binary or ASCII-armored OpenPGP, and only the exact pinned primary-key fingerprint is admitted to the verification keyring.
- Ubuntu Base release pages are scanned deterministically and the newest matching point-release tarball is selected instead of the first matching link. This prevents a 24.04.4 page that also lists 24.04.3 from silently installing the older tarball.
- The default Ubuntu resolver uses the stable `24.04` series alias instead of pinning the stale `24.04.4` point-release directory.
- Signature verification remains mandatory; this is not a checksum-only or insecure fallback.
- Signing-key material is fetched through the existing installer downloader, so the same logged `curl --retry 3` transport and failure diagnostics are preserved; only cryptographic verification moves in-process.
- Ubuntu install state records the exact selected tarball version (for example `24.04.5`) and retains the requested version/release plus the resolved release alias as metadata.
- Devtool root-module and release targets now claim the complete compiled `internal/**` dependency tree; the root-module test and lint jobs explicitly include installer and integrity packages while retaining the WR12 explicit module/bridge authority tokens.
