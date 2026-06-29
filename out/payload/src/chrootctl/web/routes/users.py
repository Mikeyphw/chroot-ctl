from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..deps import get_jobs, get_services, get_templates, resolve_log_path

router = APIRouter(prefix="/chroots/{name}/users", tags=["users"])


def _job_redirect(job_id: str, *, toast: str = "Job queued") -> RedirectResponse:
    return RedirectResponse(url=f"/jobs/{job_id}?toast={toast.replace(' ', '+')}&toast_kind=ok", status_code=303)


def _bool_from_form(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"0", "false", "off", "no", ""}


@router.get("")
def list_users(name: str, request: Request, services=Depends(get_services), templates=Depends(get_templates)):
    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "page_title": f"Users · {name}",
            "chroot_name": name,
            "users": services.users(name=name).list(),
            "default_shell": "/bin/bash",
        },
    )


@router.post("")
def add_user(
    name: str,
    username: str = Form(...),
    shell: str = Form("/bin/bash"),
    sudo: str | None = Form(None),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    normalized_username = username.strip()
    if not normalized_username:
        raise HTTPException(status_code=400, detail="username is required")
    job = jobs.submit(
        kind="user-add",
        title=f"Add user {normalized_username} to {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name, username=normalized_username),
        runner=lambda progress: _run_add_user(
            services,
            name=name,
            username=normalized_username,
            shell=shell.strip() or "/bin/bash",
            sudo=_bool_from_form(sudo),
            progress=progress,
        ),
    )
    return _job_redirect(job.job_id)


@router.get("/{username}")
def show_user(name: str, username: str, request: Request, services=Depends(get_services), templates=Depends(get_templates)):
    return templates.TemplateResponse(
        request,
        "user_detail.html",
        {
            "page_title": f"User · {username}",
            "chroot_name": name,
            "user": services.users(name=name).show(username),
            "ids": services.users(name=name).show_id(username),
        },
    )


@router.post("/{username}/sync-id")
def sync_user_id(
    name: str,
    username: str,
    fix_ownership: str | None = Form(None),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    enabled = True if fix_ownership is None else _bool_from_form(fix_ownership)
    job = jobs.submit(
        kind="user-sync-id",
        title=f"Sync id for {username} in {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name, username=username),
        runner=lambda progress: _run_sync_id(services, name=name, username=username, fix_ownership=enabled, progress=progress),
    )
    return _job_redirect(job.job_id)


@router.post("/{username}/shell")
def set_shell(
    name: str,
    username: str,
    shell: str = Form(...),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    normalized_shell = shell.strip()
    if not normalized_shell:
        raise HTTPException(status_code=400, detail="shell is required")
    job = jobs.submit(
        kind="user-shell",
        title=f"Set shell for {username} in {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name, username=username),
        runner=lambda progress: _run_set_shell(services, name=name, username=username, shell=normalized_shell, progress=progress),
    )
    return _job_redirect(job.job_id)


@router.post("/{username}/sudo")
def set_sudo(
    name: str,
    username: str,
    enabled: str = Form(...),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    sudo_enabled = _bool_from_form(enabled)
    label = "Enable sudo" if sudo_enabled else "Disable sudo"
    job = jobs.submit(
        kind="user-sudo",
        title=f"{label} for {username} in {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name, username=username),
        runner=lambda progress: _run_set_sudo(
            services,
            name=name,
            username=username,
            enabled=sudo_enabled,
            progress=progress,
        ),
    )
    return _job_redirect(job.job_id)


@router.post("/{username}/password")
def set_password(
    name: str,
    username: str,
    password: str = Form(...),
    confirm_password: str = Form(...),
    confirm_username: str = Form(...),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    if not password.strip():
        raise HTTPException(status_code=400, detail="password is required")
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="password confirmation does not match")
    if confirm_username.strip() != username:
        raise HTTPException(status_code=400, detail=f"type the username to confirm the password change: {username}")
    job = jobs.submit(
        kind="user-password",
        title=f"Set password for {username} in {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name, username=username),
        runner=lambda progress: _run_set_password(
            services,
            name=name,
            username=username,
            password=password,
            progress=progress,
        ),
    )
    return _job_redirect(job.job_id)


@router.post("/{username}/remove")
def remove_user(
    name: str,
    username: str,
    confirm_username: str = Form(...),
    delete_home: str | None = Form(None),
    services=Depends(get_services),
    jobs=Depends(get_jobs),
):
    if confirm_username.strip() != username:
        raise HTTPException(status_code=400, detail=f"type the username to confirm removal: {username}")
    remove_home = _bool_from_form(delete_home)
    job = jobs.submit(
        kind="user-remove",
        title=f"Remove user {username} from {name}",
        target_name=name,
        log_path=resolve_log_path(services, name=name, username=username),
        runner=lambda progress: _run_remove_user(
            services,
            name=name,
            username=username,
            delete_home=remove_home,
            progress=progress,
        ),
    )
    return _job_redirect(job.job_id)


def _run_add_user(services, *, name: str, username: str, shell: str, sudo: bool, progress) -> object:
    progress(f"Adding user {username}")
    return services.users(name=name).add(username, shell=shell, sudo=sudo)


def _run_sync_id(services, *, name: str, username: str, fix_ownership: bool, progress) -> object:
    progress(f"Syncing uid/gid for {username}")
    return services.users(name=name).sync_id(username, fix_ownership=fix_ownership)


def _run_set_shell(services, *, name: str, username: str, shell: str, progress) -> object:
    progress(f"Updating shell for {username}")
    return services.users(name=name).set_shell(username, shell=shell)


def _run_set_sudo(services, *, name: str, username: str, enabled: bool, progress) -> object:
    progress(("Enabling" if enabled else "Disabling") + f" sudo for {username}")
    return services.users(name=name).set_sudo(username, enabled=enabled)


def _run_set_password(services, *, name: str, username: str, password: str, progress) -> object:
    progress(f"Updating password for {username}")
    return services.users(name=name).set_password(username, password=password)


def _run_remove_user(services, *, name: str, username: str, delete_home: bool, progress) -> object:
    progress(f"Removing user {username}")
    return services.users(name=name).remove(username, delete_home=delete_home)
