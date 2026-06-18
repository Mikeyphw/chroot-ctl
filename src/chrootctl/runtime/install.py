from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..base_install import ReleaseRef
from ..catalog import ManifestCatalog
from ..chroot_users import ChrootUserManager
from ..controller import ChrootController
from ..installer_factory import build_installer
from ..interactive import Choice, prompt_text, select_one
from ..models import InstallAlreadyCompleteResult, InstallFinalizeResult
from ..user_sync import UserSyncManager, validate_username
from .catalog import apply_catalog_entries, install_selection_names
from ..services.chroots import validate_chroot_name
from .common import emit_panel, emit_table, progress_call
from .resolution import resolve_catalog_names, resolve_user_reference

PROFILE_DESCRIPTIONS: dict[str, str] = {
    "minimal": "Base shell environment with the smallest package set.",
    "dev": "Developer-oriented packages without a desktop.",
    "xfce4": "XFCE desktop profile with graphical defaults.",
    "plasma": "KDE Plasma desktop profile with graphical defaults.",
    "custom": "Minimal base for a heavily customized install.",
}

DESKTOP_DESCRIPTIONS: dict[str, str] = {
    "auto": "Let the installer pick the default desktop for the selected profile.",
    "none": "Skip desktop setup.",
    "xfce4": "Install the XFCE desktop environment.",
    "plasma": "Install the KDE Plasma desktop environment.",
}

WIZARD_BACK = ":back"
WIZARD_SKIP = ":skip"
WIZARD_KEEP = "__keep__"
WIZARD_SELECT = "__select__"
WIZARD_INSTALL = "__install__"
WIZARD_CANCEL = "__cancel__"
WIZARD_STEPS = ("distro", "name", "release", "profile", "desktop", "username", "tools", "addons")


@dataclass(slots=True)
class InstallWizardState:
    distro: str | None = None
    name: str | None = None
    username: str | None = None
    profile: str | None = None
    desktop: str | None = None
    release: str | None = None
    version: str | None = None
    tools: list[str] = field(default_factory=list)
    addons: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class InstallWizardSelection:
    distro: str
    name: str
    username: str
    profile: str | None
    desktop: str | None
    release: str | None
    version: str | None
    tools: list[str]
    addons: list[str]


def handle_install(context) -> None:
    args = context.args
    non_interactive = bool(getattr(args, "non_interactive", False))
    if getattr(args, "wizard", False):
        _apply_install_wizard(context)

    target_name = getattr(args, "name", None) or args.distro
    if target_name is None:
        raise RuntimeError("install requires a target distro or --name")
    list_username = args.username or context.config.username
    list_config = context.config.with_overrides(distro_name=target_name, username=list_username)
    if args.list_versions:
        installer = _build_installer(context, distro=args.distro, config=list_config)
        emit_table(context, "Available Versions", progress_call("Fetching versions", installer.list_versions))
        return

    selected_tools = install_selection_names(
        catalog=ManifestCatalog("tool", config=context.config),
        distro=args.distro,
        explicit_names=args.tools,
        select_flag=args.select_tools,
        non_interactive=non_interactive,
    )
    selected_addons = install_selection_names(
        catalog=ManifestCatalog("addon", config=context.config),
        distro=args.distro,
        explicit_names=args.addons,
        select_flag=args.select_addons,
        non_interactive=non_interactive,
    )
    username = resolve_user_reference(
        args.username,
        context.chroot_users,
        prompt="Choose user",
        non_interactive=non_interactive,
    )
    install_config = context.config.with_overrides(distro_name=target_name, username=username)
    installer = _build_installer(context, distro=args.distro, config=install_config)
    results = progress_call(
        f"Installing {args.distro}",
        lambda: installer.install(
            phase=args.phase,
            username=username,
            desktop=args.desktop,
            version=args.version,
            release=args.release,
            force_phase=args.force_phase,
            auto=False,
            resume=args.resume,
            repair=args.repair,
            profile=args.profile,
        ),
    )
    if selected_tools or selected_addons:
        record = context.registry.get(install_config.distro_name)
        if record is None or not bool(record.get("installed")):
            raise RuntimeError("tools and addons can only be applied after finalize completes")
        if selected_tools:
            tool_results = progress_call(
                "Applying tools",
                lambda: apply_catalog_entries(
                    catalog=ManifestCatalog("tool", config=context.config),
                    names=selected_tools,
                    config=install_config,
                    runner=context.runner,
                    registry=context.registry,
                    logger=context.logger,
                ),
            )
            results.extend(tool_results)
        if selected_addons:
            addon_results = progress_call(
                "Applying addons",
                lambda: apply_catalog_entries(
                    catalog=ManifestCatalog("addon", config=context.config),
                    names=selected_addons,
                    config=install_config,
                    runner=context.runner,
                    registry=context.registry,
                    logger=context.logger,
                ),
            )
            results.extend(addon_results)
    emit_table(context, "Install Results", results)
    emit_panel(context, "Next Steps", _install_next_steps(context, install_config.distro_name, username, results))
    _maybe_run_post_install_actions(context, install_config, username, results)


def handle_upgrade(context) -> None:
    non_interactive = bool(getattr(context.args, "non_interactive", False))
    record = context.registry.get(context.config.distro_name)
    if record is None:
        raise RuntimeError(f"no registry record for chroot: {context.config.distro_name}")
    username = resolve_user_reference(context.args.username, context.chroot_users, prompt="Choose user", non_interactive=non_interactive)
    upgrade_config = context.config.with_overrides(username=username)
    installer = _build_installer(context, distro=str(record["distro"]), config=upgrade_config)
    result = progress_call("Upgrading chroot", installer.upgrade)
    emit_panel(context, "Upgrade", result)
    emit_panel(
        context,
        "Next Steps",
        {
            "restart": "chrootctl restart",
            "logs": "chrootctl logs --all",
        },
    )


def _apply_install_wizard(context) -> None:
    args = context.args
    selection = _run_install_wizard(context)
    args.distro = selection.distro
    args.name = selection.name
    args.username = selection.username
    args.profile = selection.profile
    args.desktop = selection.desktop
    args.release = selection.release
    args.version = selection.version
    args.tools = list(selection.tools)
    args.addons = list(selection.addons)
    args.select_tools = False
    args.select_addons = False


def _run_install_wizard(context) -> InstallWizardSelection:
    state = _initial_wizard_state(context)
    step_index = 0

    while True:
        while step_index < len(WIZARD_STEPS):
            _refresh_wizard_state(context, state)
            step = WIZARD_STEPS[step_index]
            outcome = _run_wizard_step(context, state, step=step, can_go_back=step_index > 0)
            if outcome == WIZARD_BACK:
                step_index = max(0, step_index - 1)
                continue
            step_index += 1

        _refresh_wizard_state(context, state)
        emit_panel(context, "Install Wizard", _wizard_summary(context, state))
        action = _choose_wizard_review_action()
        if action == WIZARD_INSTALL:
            return InstallWizardSelection(
                distro=state.distro or "ubuntu",
                name=state.name or state.distro or "ubuntu",
                username=state.username or _default_username_hint(context, chroot_name=state.name) or "user",
                profile=state.profile,
                desktop=state.desktop,
                release=state.release,
                version=state.version,
                tools=list(state.tools),
                addons=list(state.addons),
            )
        if action == WIZARD_CANCEL:
            raise RuntimeError("install cancelled")
        step_index = WIZARD_STEPS.index(action)


def _run_wizard_step(context, state: InstallWizardState, *, step: str, can_go_back: bool) -> str | None:
    if step == "distro":
        return _wizard_step_distro(state, can_go_back=can_go_back)
    if step == "name":
        return _wizard_step_name(state, can_go_back=can_go_back)
    if step == "release":
        return _wizard_step_release(context, state, can_go_back=can_go_back)
    if step == "profile":
        return _wizard_step_profile(state, can_go_back=can_go_back)
    if step == "desktop":
        return _wizard_step_desktop(state, can_go_back=can_go_back)
    if step == "username":
        return _wizard_step_username(context, state, can_go_back=can_go_back)
    if step == "tools":
        return _wizard_step_catalog(context, state, kind="tool", can_go_back=can_go_back)
    if step == "addons":
        return _wizard_step_catalog(context, state, kind="addon", can_go_back=can_go_back)
    raise RuntimeError(f"unsupported wizard step: {step}")


def _wizard_step_distro(state: InstallWizardState, *, can_go_back: bool) -> str | None:
    current = state.distro
    previous = state.distro
    choices = _wizard_control_choices(current=current, can_go_back=can_go_back, skip_label=None)
    choices.extend(
        [
            Choice(
                "ubuntu",
                "ubuntu",
                "Stable Ubuntu rootfs with selectable releases.",
                preview="distro: ubuntu\nkind: ubuntu-base\nnotes: stable LTS-friendly rootfs with desktop support",
            ),
            Choice(
                "arch",
                "arch",
                "Rolling Arch Linux ARM rootfs.",
                preview="distro: arch\nkind: Arch Linux ARM\nnotes: rolling rootfs with a single latest release",
            ),
        ]
    )
    selected = select_one(choices, prompt="Choose distro")
    if selected == WIZARD_BACK:
        return WIZARD_BACK
    if selected == WIZARD_KEEP:
        return None
    state.distro = selected
    if state.name in {None, previous}:
        state.name = selected
    if selected != previous:
        state.release = None
        state.version = None
    return None


def _wizard_step_name(state: InstallWizardState, *, can_go_back: bool) -> str | None:
    raw = prompt_text(
        "Chroot name",
        default=state.name or state.distro,
        validator=validate_chroot_name,
        allow_back=can_go_back,
    )
    if raw == WIZARD_BACK:
        return WIZARD_BACK
    state.name = validate_chroot_name(raw)
    return None


def _wizard_step_release(context, state: InstallWizardState, *, can_go_back: bool) -> str | None:
    if state.distro is None:
        raise RuntimeError("wizard requires a distro before choosing a release")
    installer = _build_installer(context, distro=state.distro, config=_wizard_preview_config(context, state))
    refs = progress_call("Fetching versions", installer.list_versions)
    if not refs:
        state.release = None
        state.version = None
        return None
    if len(refs) == 1 and state.release is None and state.version is None:
        state.release = refs[0].label
        return None
    current = state.release or state.version
    choices = _wizard_control_choices(
        current=current,
        can_go_back=can_go_back,
        skip_label="Use installer default release",
    )
    choices.extend(
        [
            Choice(
                value=ref.label,
                label=ref.label,
                description=_release_description(ref),
                preview=_release_preview(state.distro, ref),
            )
            for ref in refs
        ]
    )
    selected = select_one(choices, prompt="Choose release")
    if selected == WIZARD_BACK:
        return WIZARD_BACK
    if selected == WIZARD_KEEP:
        return None
    if selected == WIZARD_SKIP:
        state.release = None
        state.version = None
        return None
    state.release = selected
    state.version = None
    return None


def _wizard_step_profile(state: InstallWizardState, *, can_go_back: bool) -> str | None:
    choices = _wizard_control_choices(
        current=state.profile,
        can_go_back=can_go_back,
        skip_label="Use installer default profile",
    )
    choices.extend(
        [
            Choice(
                value=profile,
                label=profile,
                description=PROFILE_DESCRIPTIONS.get(profile, ""),
                preview=f"profile: {profile}\n\n{PROFILE_DESCRIPTIONS.get(profile, '')}",
            )
            for profile in PROFILE_DESCRIPTIONS
        ]
    )
    selected = select_one(choices, prompt="Choose profile")
    if selected == WIZARD_BACK:
        return WIZARD_BACK
    if selected == WIZARD_KEEP:
        return None
    if selected == WIZARD_SKIP:
        state.profile = None
        return None
    state.profile = selected
    return None


def _wizard_step_desktop(state: InstallWizardState, *, can_go_back: bool) -> str | None:
    current = state.desktop or "auto"
    choices = _wizard_control_choices(
        current=current,
        can_go_back=can_go_back,
        skip_label="Use profile default desktop",
    )
    choices.extend(
        [
            Choice(
                value=name,
                label=name,
                description=DESKTOP_DESCRIPTIONS[name],
                preview=f"desktop: {name}\nprofile: {state.profile or 'default'}\n\n{DESKTOP_DESCRIPTIONS[name]}",
            )
            for name in ("auto", "none", "xfce4", "plasma")
        ]
    )
    selected = select_one(choices, prompt="Choose desktop")
    if selected == WIZARD_BACK:
        return WIZARD_BACK
    if selected == WIZARD_KEEP:
        return None
    if selected == WIZARD_SKIP:
        state.desktop = None
        return None
    state.desktop = None if selected == "auto" else selected
    return None


def _wizard_step_username(context, state: InstallWizardState, *, can_go_back: bool) -> str | None:
    raw = prompt_text(
        "Username",
        default=state.username or _default_username_hint(context, chroot_name=state.name),
        validator=validate_username,
        allow_back=can_go_back,
    )
    if raw == WIZARD_BACK:
        return WIZARD_BACK
    state.username = validate_username(raw)
    return None


def _wizard_step_catalog(context, state: InstallWizardState, *, kind: str, can_go_back: bool) -> str | None:
    current = list(state.tools if kind == "tool" else state.addons)
    action = _choose_catalog_step_action(kind=kind, current=current, can_go_back=can_go_back)
    if action == WIZARD_BACK:
        return WIZARD_BACK
    if action == WIZARD_KEEP:
        return None
    if action == WIZARD_SKIP:
        if kind == "tool":
            state.tools = []
        else:
            state.addons = []
        return None
    if state.distro is None:
        raise RuntimeError("wizard requires a distro before choosing catalog entries")
    names = resolve_catalog_names(
        catalog=ManifestCatalog(kind, config=context.config),
        distro=state.distro,
        category=None,
        prompt=f"Choose {kind}(s) to apply",
        explicit_names=(),
        select_flag=True,
        non_interactive=False,
    )
    if kind == "tool":
        state.tools = names
    else:
        state.addons = names
    return None


def _initial_wizard_state(context) -> InstallWizardState:
    args = context.args
    state = InstallWizardState(
        distro=getattr(args, "distro", None),
        name=getattr(args, "name", None),
        username=getattr(args, "username", None),
        profile=getattr(args, "profile", None),
        desktop=getattr(args, "desktop", None),
        release=getattr(args, "release", None),
        version=getattr(args, "version", None),
        tools=list(getattr(args, "tools", []) or []),
        addons=list(getattr(args, "addons", []) or []),
    )
    _refresh_wizard_state(context, state)
    return state


def _refresh_wizard_state(context, state: InstallWizardState) -> None:
    record = _wizard_state_record(context, state)
    if state.distro is None and record and record.get("distro"):
        state.distro = str(record["distro"])
    if state.name is None and record and record.get("name"):
        state.name = str(record["name"])
    if state.name is None and state.distro is not None:
        state.name = state.distro
    if record:
        metadata = record.get("metadata", {})
        if state.release is None and record.get("release_name"):
            state.release = str(record["release_name"])
        if state.version is None and record.get("version"):
            state.version = str(record["version"])
        if state.profile is None:
            state.profile = _metadata_value(metadata, "profile")
        if state.desktop is None:
            desktop = _metadata_value(metadata, "desktop")
            if desktop not in {None, "auto"}:
                state.desktop = desktop
        if state.username is None:
            recorded_user = _validated_username(_metadata_value(metadata, "username"))
            if recorded_user is not None:
                state.username = recorded_user
    if state.username is None:
        state.username = _default_username_hint(context, chroot_name=state.name)


def _wizard_state_record(context, state: InstallWizardState) -> dict[str, object] | None:
    if state.name:
        record = context.registry.get(state.name)
        if record is not None:
            return record
    records = list(context.registry.list())
    incomplete = [record for record in records if not bool(record.get("installed"))]
    if len(incomplete) == 1:
        return context.registry.get(str(incomplete[0]["name"]))
    if state.distro is not None:
        matches = [record for record in records if str(record.get("distro", "")) == state.distro]
        if len(matches) == 1:
            return context.registry.get(str(matches[0]["name"]))
    if len(records) == 1:
        return context.registry.get(str(records[0]["name"]))
    return None


def _wizard_preview_config(context, state: InstallWizardState):
    preview_name = state.name or state.distro or context.config.distro_name
    preview_username = state.username or _default_username_hint(context, chroot_name=preview_name)
    return context.config.with_overrides(distro_name=preview_name, username=preview_username)


def _wizard_control_choices(
    *,
    current: str | None,
    can_go_back: bool,
    skip_label: str | None,
) -> list[Choice]:
    choices: list[Choice] = []
    if current:
        choices.append(
            Choice(
                WIZARD_KEEP,
                f"Keep current: {current}",
                "Reuse the current or recorded value.",
                preview=f"value: {current}\nsource: current wizard state",
            )
        )
    if skip_label is not None:
        choices.append(
            Choice(
                WIZARD_SKIP,
                skip_label,
                "Skip explicit selection and let the installer use its default.",
                preview="value: default",
            )
        )
    if can_go_back:
        choices.append(
            Choice(
                WIZARD_BACK,
                "Back",
                "Return to the previous wizard step.",
                preview="action: back",
            )
        )
    return choices


def _choose_catalog_step_action(*, kind: str, current: list[str], can_go_back: bool) -> str:
    noun = f"{kind}(s)"
    choices: list[Choice] = []
    if current:
        choices.append(
            Choice(
                WIZARD_KEEP,
                f"Keep current {noun}",
                ", ".join(current),
                preview=f"{kind}s: {', '.join(current)}",
            )
        )
    choices.append(
        Choice(
            WIZARD_SELECT,
            f"Choose {noun}",
            f"Open the interactive {kind} picker.",
            preview=f"action: select {kind}s",
        )
    )
    choices.append(
        Choice(
            WIZARD_SKIP,
            f"Skip {noun}",
            f"Do not apply any {kind}s after install.",
            preview=f"{kind}s: none",
        )
    )
    if can_go_back:
        choices.append(
            Choice(
                WIZARD_BACK,
                "Back",
                "Return to the previous wizard step.",
                preview="action: back",
            )
        )
    return select_one(choices, prompt=f"Choose {kind}(s) to apply")


def _choose_wizard_review_action() -> str:
    choices = [
        Choice(WIZARD_INSTALL, "Start install", "Run the install with the current wizard choices.", preview="action: install"),
        Choice("distro", "Edit distro", "Go back to distro selection.", preview="step: distro"),
        Choice("name", "Edit chroot name", "Change the target chroot name.", preview="step: name"),
        Choice("release", "Edit release", "Change the distro release/version choice.", preview="step: release"),
        Choice("profile", "Edit profile", "Change the install profile.", preview="step: profile"),
        Choice("desktop", "Edit desktop", "Change the desktop selection.", preview="step: desktop"),
        Choice("username", "Edit username", "Change the bootstrap username.", preview="step: username"),
        Choice("tools", "Edit tools", "Change the post-finalize tool selection.", preview="step: tools"),
        Choice("addons", "Edit addons", "Change the post-finalize addon selection.", preview="step: addons"),
        Choice(WIZARD_CANCEL, "Cancel", "Exit the install wizard without changing anything.", preview="action: cancel"),
    ]
    return select_one(choices, prompt="Review install plan")


def _maybe_run_post_install_actions(context, install_config, username: str, results) -> None:
    if not bool(getattr(context.args, "wizard", False)):
        return
    if not os.isatty(0):
        return
    record = context.registry.get(install_config.distro_name)
    if record is None or not _install_finished(results, record):
        return
    action = _choose_post_install_action(username)
    if action == WIZARD_SKIP:
        return
    if action in {"sync", "sync-and-start"}:
        user_sync = _build_user_sync(context, install_config)
        result = progress_call("Syncing user IDs", lambda: user_sync.sync_id(username=username, fix_ownership=True))
        emit_panel(context, "User Sync", result)
    if action in {"start", "sync-and-start"}:
        controller = _build_controller(context, install_config)
        login = action == "sync-and-start"
        code = progress_call(
            "Starting chroot session",
            lambda: controller.start(login=login, root_login=not login),
            interactive=True,
        )
        if code != 0:
            raise RuntimeError(f"post-install start exited with status {code}")


def _choose_post_install_action(username: str) -> str:
    return select_one(
        [
            Choice(
                WIZARD_SKIP,
                "Finish",
                "Exit the wizard and run post-install steps later.",
                preview="action: finish",
            ),
            Choice(
                "sync",
                "Run users sync-id now",
                f"Sync UID/GID ownership for {username}.",
                preview=f"command: chrootctl users sync-id {username}",
            ),
            Choice(
                "start",
                "Start chroot now",
                "Open a root shell in the new chroot.",
                preview="command: chrootctl start",
            ),
            Choice(
                "sync-and-start",
                "Sync IDs and start login shell",
                f"Run users sync-id for {username}, then open a login shell as that user.",
                preview=f"commands:\n  chrootctl users sync-id {username}\n  chrootctl start --login",
            ),
        ],
        prompt="Choose post-install action",
    )


def _default_username_hint(context, *, chroot_name: str | None = None) -> str | None:
    manager = _user_manager_for(context, chroot_name)
    existing = [
        row.username
        for row in manager.user_rows()
        if row.username != "root" and str(getattr(row, "uid", "")) != "0"
    ]
    if len(existing) == 1:
        return existing[0]
    env_user = os.environ.get("USER", "").strip()
    if env_user and env_user != "root":
        try:
            return validate_username(env_user)
        except ValueError:
            return None
    configured = context.config.username
    if configured and configured != "root" and configured != "mike":
        try:
            return validate_username(configured)
        except ValueError:
            return None
    return None


def _user_manager_for(context, chroot_name: str | None) -> ChrootUserManager:
    if not chroot_name or chroot_name == context.config.distro_name:
        return context.chroot_users
    target_config = context.config.for_chroot(chroot_name)
    return ChrootUserManager(target_config, context.runner, context.registry, context.logger)


def _metadata_value(metadata: object, key: str) -> str | None:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validated_username(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return validate_username(value)
    except ValueError:
        return None


def _wizard_summary(context, state: InstallWizardState) -> dict[str, str]:
    summary = {
        "distro": state.distro or "unset",
        "name": state.name or "unset",
        "username": state.username or "unset",
        "profile": state.profile or "default",
        "desktop": state.desktop or "auto",
        "release": state.release or state.version or "default",
        "tools": ", ".join(state.tools) if state.tools else "none",
        "addons": ", ".join(state.addons) if state.addons else "none",
    }
    record = _wizard_state_record(context, state)
    if record is not None:
        summary["existing_phase"] = str(record.get("phase", "")) or "unknown"
        summary["installed"] = "yes" if bool(record.get("installed")) else "no"
    return summary


def _release_description(ref: ReleaseRef) -> str:
    return ref.url


def _release_preview(distro: str, ref: ReleaseRef) -> str:
    return "\n".join(
        [
            f"distro: {distro}",
            f"label: {ref.label}",
            f"url: {ref.url}",
        ]
    )


def _build_installer(context, *, distro: str, config):
    return build_installer(
        distro,
        config=config,
        runner=context.runner,
        controller=_build_controller(context, config),
        registry=context.registry,
        user_sync=_build_user_sync(context, config),
        logger=context.logger,
    )


def _build_controller(context, config):
    return ChrootController(config, context.runner, context.logger)


def _build_user_sync(context, config):
    return UserSyncManager(config, context.runner, context.logger)


def _install_next_steps(context, distro_name: str, username: str, results) -> dict[str, str]:
    record = context.registry.get(distro_name)
    if record is None:
        return {
            "resume": f"chrootctl install {context.args.distro} --resume",
            "logs": "chrootctl logs --all",
        }
    if _install_finished(results, record):
        return {
            "start": "chrootctl start",
            "sync_id": f"chrootctl users sync-id {username}",
            "tools_apply": "chrootctl tools apply <tool>",
            "addons_apply": "chrootctl addons apply <addon>",
            "logs": "chrootctl logs --all",
        }
    return {
        "resume": f"chrootctl install {context.args.distro} --resume",
        "logs": "chrootctl logs --all",
    }


def _install_finished(results, record: dict[str, object]) -> bool:
    if bool(record.get("installed")):
        return True
    for result in results:
        if isinstance(result, InstallFinalizeResult):
            return bool(result.installed)
        if isinstance(result, InstallAlreadyCompleteResult):
            return bool(result.installed)
    return False
