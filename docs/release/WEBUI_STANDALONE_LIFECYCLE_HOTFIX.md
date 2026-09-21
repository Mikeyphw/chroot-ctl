# Standalone WebUI lifecycle hotfix

Real-device evidence showed that the standalone browser could load the authenticated WebUI and then lose the loopback authority before its first backend health request. KernelSU WebUI remained healthy, isolating the defect to the Action-launched standalone authority.

This hotfix makes the Action launcher session-detached (`setsid` when available, BusyBox fallback, then the existing `nohup` fallback), records a root-only PID, replaces an older Action-launched authority, and catches immediate launch death. The native HTTP server now logs request begin/end, panic recovery, idle shutdown, and serve termination to the existing standalone log via the CLI logger. The browser transport retries one idempotent GET once after 250 ms and reports the exact same-origin URL and the on-device log path when the listener is unreachable.

The privileged API boundary is unchanged: the server remains bound to `127.0.0.1`, bootstrap/session/CSRF/Origin rules remain intact, and no generic shell/exec/argv HTTP endpoint is introduced.

Device evidence command after installing the rebuilt module:

```sh
cd "$HOME/Code/chroot-ctl"
su -c "$PWD/scripts/webui/device-standalone-lifecycle-smoke.sh"
```

If the browser still reports a network failure, inspect `/data/local/tmp/chrootctl/standalone-webui.log`; the new request and termination records distinguish listener death from an HTTP/backend error without logging the bootstrap query token.
