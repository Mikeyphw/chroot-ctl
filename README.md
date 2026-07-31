# chrootctl v9

Proper installable `src/` pip package for managing Termux chroots.

## Features

- `pip install .` / `pip install -e .`
- separate installers:
  - `src/chrootctl/ubuntu.py`
  - `src/chrootctl/arch.py`
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
- `completion zsh` output with auto-detected `fzf`, `bat`, and `lsd` enhancements
- YAML-backed `tools` and `addons` repositories with optional `fzf` multi-select
- rich CLI output

## Install

```bash
pip install .
# or
pip install -e .

# one-shot for current shell
source <(chrootctl completion zsh)

# persistent install
mkdir -p ~/.local/share/zsh/site-functions
chrootctl completion zsh > ~/.local/share/zsh/site-functions/_chrootctl
```

## Examples

```bash
chrootctl install ubuntu --name ubuntu --username mike
chrootctl install arch --name arch --username mike
chrootctl install ubuntu --name work --resume --profile dev --username mike
chrootctl install ubuntu --name ubuntu --tool remove-snapd --addon nala --username mike
chrootctl install ubuntu --name ubuntu --select-tools --select-addons --username mike

chrootctl users show-id --name ubuntu --username mike
chrootctl users sync-id --name ubuntu --username mike
chrootctl users list --name ubuntu
chrootctl users show mike --name ubuntu
chrootctl users add dev --shell /bin/bash --sudo --name ubuntu
chrootctl users password dev --name ubuntu
chrootctl users shell dev --shell /usr/bin/zsh --name ubuntu
chrootctl users sudo dev --disable --name ubuntu
chrootctl users remove dev --delete-home --name ubuntu

chrootctl chroots list
chrootctl chroots show work
chrootctl start ubuntu
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
```


## Service units

`chrootctl run` loads systemd-inspired `*.service` files from `service_dirs`. On Android the default directory is `/data/adb/chrootctl/services`, so you can add or change services without editing the module or Python source. The Magisk/KSU `service.sh` also calls `chrootctl run --boot`, which starts enabled units wanted by `boot.target`.

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

By default, chroots are created under `/data/local/tmp/<name>`. Set `chroot_root` in the config file if you need a different base directory.

Plain `chrootctl install ubuntu` uses the `minimal` profile and keeps Ubuntu Base as the rootfs source. Desktop environments are explicit via `--profile xfce4`, `--profile plasma`, or desktop add-ons.

Tool and add-on manifests live in YAML. `distro` may be a single distro, a list such as `[ubuntu, arch]`, or `all`; scripts are loaded from the matching script repository and run inside an installed chroot with a sanitized chroot environment.

When a command is missing a finite selectable argument, such as a chroot name, chroot username, tool, or add-on, `chrootctl` uses `fzf` when available. Without `fzf`, it falls back to a numbered prompt in an interactive TTY and returns a clear error in non-interactive scripts.

If `fzf` is installed, the generated zsh completion uses it for interactive chroot selection. If `bat` or `lsd` are available, they are used automatically for previews. The script falls back to normal zsh completion and standard preview tools when those commands are missing, so regeneration is not required after installing them later.
