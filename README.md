# chrootctl v9

Proper installable `src/` pip package for managing Termux chroots.

## Features

- `pip install .` / `pip install -e .`
- separate installers:
  - `src/chrootctl/ubuntu.py`
  - `src/chrootctl/arch.py`
- multi-chroot registry
- Ubuntu and Arch/Manjaro install flows
- UID/GID sync to match the Termux host user
- ownership repair after UID/GID sync
- runtime mount/start/fix-tty/status
- rich CLI output

## Install

```bash
pip install .
# or
pip install -e .
```

## Examples

```bash
chrootctl install ubuntu --name ubuntu --auto --username mike
chrootctl install arch --name arch --auto --username mike
chrootctl install manjaro --name manjaro --auto --username mike

chrootctl users show-id --name ubuntu --username mike
chrootctl users sync-id --name ubuntu --username mike

chrootctl chroots list
```
