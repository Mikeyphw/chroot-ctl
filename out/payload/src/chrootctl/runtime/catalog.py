from __future__ import annotations

from typing import Any

from ..catalog import ManifestCatalog
from ..config import ChrootConfig
from ..output import use_compact_catalog_layout
from ..registry import ChrootRegistry
from ..system import SystemRunner
from .common import emit_panel, emit_table, progress_call
from .resolution import resolve_catalog_name, resolve_catalog_names


def handle_tools(context) -> None:
    _handle_catalog_command(context, kind="tool")


def handle_addons(context) -> None:
    _handle_catalog_command(context, kind="addon")


def _handle_catalog_command(context, *, kind: str) -> None:
    args = context.args
    non_interactive = bool(getattr(args, "non_interactive", False))
    service = context.services.catalog(kind, name=context.config.distro_name)
    catalog = ManifestCatalog(kind, config=context.config)
    title = f"{kind.title()}s"
    item_label = kind if kind == "tool" else "addon"

    command_name = getattr(args, f"{title.lower()}_command")
    if command_name == "categories":
        render_category_table(context, f"{title} Categories", service.categories(distro=args.distro))
        return
    if command_name == "list":
        render_catalog_table(context, title, service.list_entries(distro=args.distro, category=args.category))
        return
    if command_name == "show":
        entry_name = resolve_catalog_name(
            getattr(args, item_label + "_name"),
            catalog=catalog,
            distro=None,
            category=None,
            prompt=f"Choose {item_label}",
            non_interactive=non_interactive,
        )
        catalog_result_panel(context, item_label, service.get_entry(entry_name))
        return
    if command_name == "apply":
        entry_names = resolve_catalog_names(
            catalog=catalog,
            distro=registry_distro_for_config(context.registry, context.config),
            category=args.category,
            prompt=f"Choose {item_label}(s) to apply",
            explicit_names=getattr(args, item_label + "_names"),
            select_flag=not bool(getattr(args, item_label + "_names")),
            non_interactive=non_interactive,
        )
        results = progress_call(
            f"Applying {title.lower()}",
            lambda: service.apply(entry_names),
        )
        emit_table(context, title, results)
        return
    raise RuntimeError(f"unsupported {title.lower()} command: {command_name}")


def render_catalog_table(context, title: str, entries: Any) -> None:
    if use_compact_catalog_layout():
        rows = [
            {
                "name": entry.name,
                "categories": ",".join(entry.categories) or "uncategorized",
                "description": entry.description,
            }
            for entry in entries
        ]
    else:
        rows = [
            {
                "name": entry.name,
                "description": entry.description,
                "distros": ",".join(entry.distros),
                "categories": ",".join(entry.categories),
                "script": entry.script,
            }
            for entry in entries
        ]
    emit_table(context, title, rows)


def render_category_table(context, title: str, categories: list[str]) -> None:
    emit_table(context, title, [{"category": category} for category in categories])


def catalog_result_panel(context, kind: str, entry: Any) -> None:
    emit_panel(
        context,
        kind.title(),
        {
            "name": entry.name,
            "description": entry.description,
            "distros": ",".join(entry.distros),
            "categories": ",".join(entry.categories),
            "script": entry.script,
        },
    )


def apply_catalog_entries(
    *,
    catalog: ManifestCatalog,
    names: list[str],
    config: ChrootConfig,
    runner: SystemRunner,
    registry: ChrootRegistry,
    logger,
):
    return [
        catalog.apply(
            name=name,
            config=config,
            runner=runner,
            registry=registry,
            logger=logger,
        )
        for name in names
    ]


def install_selection_names(*, catalog: ManifestCatalog, distro: str, explicit_names: list[str], select_flag: bool, non_interactive: bool = False) -> list[str]:
    return resolve_catalog_names(
        catalog=catalog,
        distro=distro,
        category=None,
        prompt=f"Choose {catalog.kind}(s) to apply",
        explicit_names=explicit_names,
        select_flag=select_flag,
        non_interactive=non_interactive,
    )


def registry_distro_for_config(registry: ChrootRegistry, config: ChrootConfig) -> str:
    record = registry.get(config.distro_name)
    if record is None:
        raise RuntimeError("chroot must be installed first")
    return str(record.get("distro", ""))


def completion_catalog_names(kind: str, distro: str | None = None) -> str:
    catalog = ManifestCatalog("tool" if kind == "tools" else "addon")
    return "\n".join(entry.name for entry in catalog.list_entries(distro=distro))


def completion_catalog_categories(topic: str, distro: str | None = None) -> str:
    catalog = ManifestCatalog("tool" if topic == "tool-categories" else "addon")
    return "\n".join(catalog.categories(distro=distro))


def completion_catalog_details(topic: str, distro: str | None = None, category: str | None = None) -> str:
    catalog = ManifestCatalog("tool" if topic == "tool-details" else "addon")
    entries = catalog.list_entries(distro=distro, category=category)
    return "\n".join(
        "\t".join(
            [
                entry.name,
                ",".join(entry.categories) or "uncategorized",
                ",".join(entry.distros),
                entry.description,
            ]
        )
        for entry in entries
    )


def completion_catalog_preview(topic: str, name: str) -> str:
    catalog = ManifestCatalog("tool" if topic == "tool-preview" else "addon")
    entry = catalog.get_entry(name)
    lines = [
        f"name: {entry.name}",
        f"kind: {entry.kind}",
        f"distros: {','.join(entry.distros)}",
        f"categories: {','.join(entry.categories) or 'uncategorized'}",
        f"script: {entry.script}",
        "",
        entry.description,
    ]
    return "\n".join(lines)
