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
chrootctl tools list --distro ubuntu
chrootctl tools apply remove-snapd --name ubuntu
chrootctl addons list --distro ubuntu
chrootctl addons apply nala --name ubuntu
source <(chrootctl completion zsh)
```

By default, chroots are created under `/data/local/tmp/<name>`. Set `chroot_root` in the config file if you need a different base directory.

Plain `chrootctl install ubuntu` uses the `minimal` profile and keeps Ubuntu Base as the rootfs source. Desktop environments are explicit via `--profile xfce4`, `--profile plasma`, or desktop add-ons.

Tool and add-on manifests live in YAML. `distro` may be a single distro, a list such as `[ubuntu, arch]`, or `all`; scripts are loaded from the matching script repository and run inside an installed chroot with a sanitized chroot environment.

When a command is missing a finite selectable argument, such as a chroot name, chroot username, tool, or add-on, `chrootctl` uses `fzf` when available. Without `fzf`, it falls back to a numbered prompt in an interactive TTY and returns a clear error in non-interactive scripts.

If `fzf` is installed, the generated zsh completion uses it for interactive chroot selection. If `bat` or `lsd` are available, they are used automatically for previews. The script falls back to normal zsh completion and standard preview tools when those commands are missing, so regeneration is not required after installing them later.
