# Real-device smoke checklist

## Automated smoke plan

- Root module is discovered from the supported Magisk/KernelSU locations.
- Root bridge binds successfully and capabilities load.
- Dashboard query succeeds.
- Chroots list query succeeds.
- Operation history query succeeds.
- With a registered chroot available, Services query succeeds.
- With a registered chroot available, Users query succeeds.
- With a registered chroot available, Snapshots query succeeds.
- With a registered chroot available, Storage query succeeds.
- With a registered chroot available, bounded Logs query succeeds.
- Advanced runtime diagnostics query succeeds.
- Debug probes complete.
- Support preview completes.
- Module build preview completes.
- Transfer artifact listing completes.

## Manual Android UI seal

Run these checks in portrait and landscape on a phone, and at tablet width when available. Repeat the workspace pass at 200% font scale and with TalkBack or switch/keyboard navigation.

- Open one selected chroot and traverse Overview, Services, Users, Snapshots, Storage, Logs, and Advanced without clipped actions or unreachable controls.
- Confirm workspace/review pane titles are announced and every actionable target is at least 48dp.
- Rotate or recreate the Activity: selected workspace/tab and safe filters restore; the restored workspace re-binds backend detail/users/services state; snapshot/user/service mutation reviews and typed destructive confirmations do not restore.
- Enable Logs live tail, background the app, and verify polling stops; return to foreground and verify it resumes. Leave Logs and verify polling stops.
- Exercise loading, empty, ready, and retryable failure states for Services, Users, Snapshots, Storage, Logs, and Advanced diagnostics.
- Cold-start or recreate with capabilities still loading: capability-gated rooms stay disabled and no gated query is sent. Then connect or simulate a capability set that lacks `storage.status` and `logs.list`; Storage/Logs remain disabled while Overview/Advanced stay usable and no unsupported request is sent.
- Force a RootService disconnect/rebind path and verify the native client reconnects without replaying a mutating request.
- Confirm root-module-first runtime discovery still resolves the installed module before fallback paths.

## Evidence handoff

- Last smoke result is visible.
- Smoke evidence can be persisted and exported.
- A failure support bundle can be created when smoke fails.
- Record manual degraded-protocol and RootService reconnect results beside the automated smoke evidence before release sealing.
