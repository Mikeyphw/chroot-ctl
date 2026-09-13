# chrootctl

Go-native Android/Termux chroot manager with a Magisk/KernelSU module runtime and Kotlin Android companion.

## Features

- single Go backend (`cmd/chrootctl`) for CLI and Android bridge protocol v1
- native Ubuntu and Arch installers
- multi-chroot registry
- Ubuntu and Arch install flows
- UID/GID sync to match the Termux host user
- ownership repair after UID/GID sync
- runtime mount/start/restart/exec/unmount/fix-tty/status
- systemd-inspired chroot service units with `chrootctl run` and boot-time `boot.target` support
- lifecycle commands for showing, renaming, and removing chroots
- recovery helpers for install resume/repair and post-install upgrades
- config-driven bind mounts, extra packages, locale, DNS, and per-chroot overrides
- diagnostics via `doctor` and local log viewing via `logs`
- zsh completion generated from the same CLI contract used by parser/help, including dynamic chroot/user/catalog candidates
- `wrapper install` for a local `chc` helper that auto-escalates through `su -c` when needed
- YAML-backed `tools` and `addons` repositories with explicit selection and single-candidate auto-selection
- rich CLI output

## Build and install

```bash
# Validate the Go backend
go run ./cmd/repoctl validate

# Build the sealed Android/ARM64 runtime and Magisk/KernelSU module
./build.sh

# Build and install the module through KernelSU
./build.sh --install

# Final deterministic release seal
./scripts/final-seal

# local wrapper and shell completion
chrootctl wrapper install
mkdir -p ~/.local/share/zsh/site-functions
chrootctl completion zsh > ~/.local/share/zsh/site-functions/_chrootctl
```

## Examples

```bash
chrootctl install ubuntu --name ubuntu --username mike
chrootctl install arch --name arch --username mike
chrootctl install ubuntu --name work --resume --profile dev --username mike
chrootctl install ubuntu --name ubuntu --tool remove-snapd --addon nala --username mike

chrootctl users show-id mike --name ubuntu
chrootctl users sync-id --name ubuntu --username mike
chrootctl users list --name ubuntu
chrootctl users show mike --name ubuntu
chrootctl users add dev --shell /bin/bash --sudo --name ubuntu
chrootctl users password dev --name ubuntu
chrootctl users shell dev --shell /usr/bin/zsh --name ubuntu
chrootctl users sudo dev --disable --name ubuntu
chrootctl users remove dev --delete-home --name ubuntu

chrootctl chroots list
chrootctl chroots show --name work
chrootctl start --name ubuntu
chrootctl exec --name work -- ls /home/mike
chrootctl restart --name work --login
chrootctl upgrade --name work
chrootctl doctor --name work
chrootctl logs --tail 50
chrootctl run code serve-web
chrootctl --name code run serve-web --status
chrootctl run --list
chrootctl tools list --distro ubuntu
chrootctl tools apply remove-snapd --name ubuntu
chrootctl addons list --distro ubuntu
chrootctl addons apply nala --name ubuntu
source <(chrootctl completion zsh)
chrootctl wrapper install
chc --help
```


## Service units

`chrootctl run` loads systemd-inspired `*.service` files from `service_dirs`. On Android the default directory is `/data/adb/chrootctl/services`, so you can add or change services without editing the module or backend source. The Magisk/KSU `service.sh` also calls `chrootctl run --boot`, which starts enabled units wanted by `boot.target`.

Each service is intentionally bound to one chroot with `[Service] Chroot=<name>`. Passing a different chroot on the CLI is treated as a safety error instead of silently starting the service elsewhere.

Example `/data/adb/chrootctl/services/serve-web.service`:

```ini
[Unit]
Description=VS Code web server
After=network-online.service
Requires=network-online.service

[Service]
Chroot=code
User=mike
WorkingDirectory=/home/mike/project
Environment=PORT=8080
ExecStart=code serve-web --host 0.0.0.0 --port 8080
ExecStop=pkill -f "code serve-web"

[Install]
WantedBy=boot.target
Enabled=true
```

For your `androidos` VS Code Web service, use:

```ini
[Unit]
Description=VS Code Web Server
After=network-online.service
Requires=network-online.service

[Service]
Chroot=androidos
User=mike
WorkingDirectory=/home/mike
Environment=HOME=/home/mike
Environment=USER=mike
Environment=HOST=0.0.0.0
Environment=PORT=8080
ExecStart=code serve-web --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=boot.target
```

Useful commands:

```bash
chrootctl run code serve-web              # start CHROOT SERVICE
chrootctl --name code run serve-web       # same, with --name validated against Chroot=
chrootctl run code serve-web --status
chrootctl journal code serve-web --tail 100
chrootctl run code serve-web --logs --follow
chrootctl run code serve-web --restart
chrootctl run code serve-web --stop
chrootctl enable code serve-web           # enable for boot.target
chrootctl disable code serve-web
chrootctl run --boot                      # dependency-aware boot.target startup
chrootctl run --boot --no-parallel        # sequential boot startup for debugging
chrootctl run --list
```

Boot startup builds a small dependency graph from `[Unit] Requires=` and `[Unit] After=`. Required units are included automatically, ordering dependencies are honored, and independent units in the same layer are started in parallel unless `--no-parallel` is passed.

Service output is captured as journal-style files under `service_log_dir`, with lifecycle entries plus stdout/stderr from the spawned process. Services run through a generated in-chroot login-session script so `User=` sees the same shell startup, `HOME`, `PATH`, and groups as an interactive login. The journal includes a preflight block with `id`, `groups`, `HOME`, `pwd`, and the first entries under the selected home directory; this is useful when a service can see different files than an interactive shell. PID files and enable/disable markers are stored under `service_state_dir`. These paths can be overridden in `config.json` with `service_dirs`, `service_state_dir`, and `service_log_dir`.

The Web UI also exposes a Services module at `/services` for listing units, starting/stopping/restarting, enabling/disabling, and reading each service journal.

By default, new chroots are created under `/data/local/tmp/<name>`. Set `chroot_root` in the config file to change the **creation default**. Once a chroot is registered, its canonical `chroots.path` registry value is the authoritative filesystem identity; changing `chroot_root` does not silently relocate existing chroots.

Configuration is fail-closed for privileged paths: host paths must resolve to non-empty absolute paths (with supported `~` expansion), unknown keys are rejected, and per-chroot overrides cannot replace target identity or process-global database/snapshot/log/state roots. Default media bind targets follow the configured username unless the media mounts were explicitly supplied. Registry writes also enforce one canonical path owner per chroot identity. See [`docs/audit/CHR03_CONFIG_REGISTRY_IDENTITY.md`](docs/audit/CHR03_CONFIG_REGISTRY_IDENTITY.md) for the exact invariants and migration behavior.

Plain `chrootctl install ubuntu` uses the `minimal` profile and keeps Ubuntu Base as the rootfs source. Desktop environments are explicit via `--profile xfce4`, `--profile plasma`, or desktop add-ons.

Tool and add-on manifests live in YAML. `distro` may be a single distro, a list such as `[ubuntu, arch]`, or `all`; scripts are loaded from the matching script repository and run inside an installed chroot with a sanitized chroot environment.

Finite selectors are deterministic: chroot/user/tool/add-on values are auto-selected only when exactly one eligible candidate exists; otherwise pass the value explicitly. `--non-interactive` continues to disable the install wizard and confirmations. The CLI no longer documents an `fzf`/numbered-prompt fallback that the native backend does not implement.

Zsh completion is rendered directly from the compiled CLI contract, so command families, options, choices, and completion hints cannot drift from parser/help metadata. See [`docs/cli/COMMAND_REFERENCE.md`](docs/cli/COMMAND_REFERENCE.md) for the generated exhaustive command reference.


## Native Android replacement foundation

The repository now contains the Phase 0-4 foundation for replacing the WebUI under `android/`.
The Android app uses a fixed libsu root service and the versioned `chrootctl app` bridge; it does not start a localhost server or expose arbitrary shell execution.

Bridge examples:

```bash
chrootctl app capabilities
printf '%s' '{"protocolVersion":1,"requestId":"list-1","operation":"chroots.list","payload":{}}' \
  | chrootctl app query --request-file -
printf '%s' '{"protocolVersion":1,"requestId":"refresh-1","operation":"system.refresh","payload":{}}' \
  | chrootctl app run --request-file - --events ndjson
```

See `docs/android/WEBUI_PARITY_MATRIX.md` for the native replacement gate and `docs/android/ANDROID_APP_ARCHITECTURE.md` for the process and security boundaries.
