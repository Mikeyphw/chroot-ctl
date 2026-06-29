from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..catalog import ManifestCatalog
from ..config import ChrootConfig
from ..chroot_users import ChrootUserManager
from ..interactive import Choice, select_many, select_one
from ..registry import ChrootRegistry
from ..user_sync import validate_username


def resolve_chroot_name(
    value: str | None,
    registry: ChrootRegistry,
    *,
    prompt: str,
    installed_only: bool = False,
    auto_select_single: bool = False,
    non_interactive: bool = False,
) -> str:
    return _resolve_value(
        value,
        chroot_choices(registry, installed_only=installed_only),
        prompt=prompt,
        item_label="chroot",
        auto_select_single=auto_select_single,
        non_interactive=non_interactive,
    )


def resolve_username(
    value: str | None,
    manager: ChrootUserManager,
    *,
    prompt: str,
    non_interactive: bool = False,
) -> str:
    return _resolve_value(
        value,
        user_choices(manager),
        prompt=prompt,
        item_label="user",
        auto_select_single=True,
        non_interactive=non_interactive,
    )


def resolve_user_reference(
    value: str | None,
    manager: ChrootUserManager,
    *,
    prompt: str,
    non_interactive: bool = False,
) -> str:
    if value:
        return validate_username(value)
    choices = user_choices(manager, non_root_only=True)
    if not choices:
        raise RuntimeError(f"{prompt}: no non-root users available; pass --username")
    return _resolve_value(
        None,
        choices,
        prompt=prompt,
        item_label="user",
        auto_select_single=True,
        non_interactive=non_interactive,
    )


def resolve_catalog_name(
    value: str | None,
    *,
    catalog: ManifestCatalog,
    distro: str | None,
    category: str | None,
    prompt: str,
    non_interactive: bool = False,
) -> str:
    return _resolve_value(
        value,
        catalog_choices(catalog, distro=distro, category=category),
        prompt=prompt,
        item_label=catalog.kind,
        non_interactive=non_interactive,
    )


def resolve_catalog_names(
    *,
    catalog: ManifestCatalog,
    distro: str,
    category: str | None,
    prompt: str,
    explicit_names: Iterable[str] = (),
    select_flag: bool = False,
    non_interactive: bool = False,
) -> list[str]:
    choices = catalog_choices(catalog, distro=distro, category=category)
    names = _resolve_explicit_names(explicit_names, choices, item_label=catalog.kind)
    if not select_flag:
        return names
    if not choices:
        if names:
            return names
        raise RuntimeError(f"{prompt}: no {catalog.kind}s available for selection")
    if non_interactive:
        raise RuntimeError(f"{prompt}: selection required in non-interactive mode")
    chosen = _select_many(choices, prompt=prompt)
    for name in chosen:
        if name not in names:
            names.append(name)
    return names


def chroot_choices(registry: ChrootRegistry, *, installed_only: bool = False) -> list[Choice]:
    records = [
        record
        for record in registry.list()
        if not installed_only or bool(record.get("installed"))
    ]
    return [
        Choice(
            value=str(record["name"]),
            label=str(record["name"]),
            description=f"{record.get('distro', '')} {record.get('phase', '')}",
        )
        for record in records
    ]


def user_choices(manager: ChrootUserManager, *, non_root_only: bool = False) -> list[Choice]:
    rows = [
        user
        for user in manager.user_rows()
        if not non_root_only or (user.username != "root" and str(user.uid) != "0")
    ]
    return [
        Choice(
            value=user.username,
            label=user.username,
            description=f"{user.uid}:{user.gid} {user.shell}",
        )
        for user in rows
    ]


def catalog_choices(
    catalog: ManifestCatalog,
    *,
    distro: str | None,
    category: str | None,
) -> list[Choice]:
    entries = catalog.list_entries(distro=distro, category=category)
    return [
        Choice(
            value=entry.name,
            label=entry.name,
            description=f"{','.join(getattr(entry, 'categories', ())) or 'uncategorized'} - {entry.description}",
            preview="\n".join(
                [
                    f"name: {entry.name}",
                    f"kind: {getattr(entry, 'kind', getattr(catalog, 'kind', 'entry'))}",
                    f"distros: {','.join(getattr(entry, 'distros', ())) or 'all'}",
                    f"categories: {','.join(getattr(entry, 'categories', ())) or 'uncategorized'}",
                    f"script: {getattr(entry, 'script', '')}",
                    "",
                    getattr(entry, "description", ""),
                    "",
                    getattr(entry, "script_text", ""),
                ]
            ).strip(),
        )
        for entry in entries
    ]


def _resolve_value(
    value: str | None,
    choices: Sequence[Choice],
    *,
    prompt: str,
    item_label: str,
    auto_select_single: bool = False,
    non_interactive: bool = False,
) -> str:
    if value:
        available = {choice.value for choice in choices}
        if value not in available:
            raise RuntimeError(f"unknown {item_label}: {value}")
        return value
    if not choices:
        raise RuntimeError(f"{prompt}: no {item_label}s available for selection")
    if auto_select_single and len(choices) == 1:
        return choices[0].value
    if non_interactive:
        raise RuntimeError(f"{prompt}: selection required in non-interactive mode")
    try:
        return select_one(choices, prompt=prompt)
    except RuntimeError as exc:
        raise RuntimeError(f"{prompt}: {exc}") from exc


def _resolve_explicit_names(values: Iterable[str], choices: Sequence[Choice], *, item_label: str) -> list[str]:
    names = _dedupe_names(values)
    if not names:
        return []
    available = {choice.value for choice in choices}
    missing = [name for name in names if name not in available]
    if missing:
        missing_names = ", ".join(missing)
        raise RuntimeError(f"unknown {item_label}{'' if len(missing) == 1 else 's'}: {missing_names}")
    return names


def _select_many(choices: Sequence[Choice], *, prompt: str) -> list[str]:
    try:
        return select_many(choices, prompt=prompt, multi=True)
    except RuntimeError as exc:
        raise RuntimeError(f"{prompt}: {exc}") from exc


def _dedupe_names(values: Iterable[str]) -> list[str]:
    names: list[str] = []
    for value in values:
        if value not in names:
            names.append(value)
    return names


def resolve_runtime_chroot_name(args, base_config: ChrootConfig, registry: ChrootRegistry) -> str | None:
    prompt = _runtime_chroot_prompt(args)
    if args.command == "install":
        if getattr(args, "wizard", False) and not (args.name or args.distro):
            return None
        return args.name or args.distro
    if args.command in {"completion", "__complete"}:
        return args.name
    if prompt is None:
        return args.name or None
    installed_only = _runtime_chroot_installed_only(args)
    return resolve_target_chroot_name(
        args.name,
        registry,
        prompt=prompt,
        installed_only=installed_only,
        non_interactive=bool(getattr(args, "non_interactive", False)),
    )


def resolve_target_chroot_name(
    value: str | None,
    registry: ChrootRegistry,
    *,
    prompt: str,
    installed_only: bool,
    non_interactive: bool = False,
) -> str:
    return _resolve_value(
        value,
        chroot_choices(registry, installed_only=installed_only),
        prompt=prompt,
        item_label="chroot",
        auto_select_single=True,
        non_interactive=non_interactive,
    )


def _runtime_chroot_prompt(args) -> str | None:
    if args.command in {"status", "mount", "unmount", "fix-tty", "doctor", "start", "restart", "exec", "upgrade", "users"}:
        return "Choose chroot"
    if args.command in {"tools", "addons"} and getattr(args, f"{args.command}_command", None) == "apply":
        return "Choose chroot"
    if args.command == "chroots":
        subcommand = getattr(args, "chroots_command", None)
        if subcommand == "show":
            return "Choose chroot"
        if subcommand == "remove":
            return "Choose chroot to remove"
        if subcommand == "rename":
            return "Choose chroot to rename"
    return None


def _runtime_chroot_installed_only(args) -> bool:
    if args.command == "chroots":
        return False
    return True
