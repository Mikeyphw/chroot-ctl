# SWUI-04 — migration, device tests, and release seal

Standalone browser mode is the primary WebUI path. It binds only to IPv4 loopback on an ephemeral port, uses a one-use bootstrap token, HttpOnly SameSite session authentication, CSRF plus exact same-origin checks for mutations, bounded HTTP requests, and typed bridge-backed APIs. There is no generic shell, exec, argv, or root-RPC HTTP endpoint.

KernelSU WebUI remains a compatibility fallback. The standalone server now exposes completion to the CLI so idle HTTP shutdown also terminates the owning `chrootctl webui` process instead of leaving an orphan process.

Run `su -c /data/adb/modules/chrootctl/scripts/webui/device-standalone-smoke.sh` if the scripts directory is packaged by your build, or run the repository copy as root. The automated device phase verifies loopback URL generation, authentication, bootstrap replay rejection, typed capabilities, and mutation rejection without CSRF/Origin. Manual release evidence still covers Action-button browser launch, browser reopen, tmux UTF-8/input/capture/resize/reconnect, multiple targets/users, root-manager restart, and Android reboot/relaunch.
