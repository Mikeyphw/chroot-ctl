from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from markupsafe import Markup, escape


_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True, slots=True)
class WebSecurityConfig:
    bind_host: str
    bind_port: int
    access_token: str | None = None
    csrf_cookie_name: str = "chrootctl_csrf"
    auth_cookie_name: str = "chrootctl_token"

    @property
    def token_enabled(self) -> bool:
        return bool(self.access_token)

    @property
    def localhost_only(self) -> bool:
        return self.bind_host in _LOCAL_HOSTS


@dataclass(frozen=True, slots=True)
class RequestSecurityState:
    bind_host: str
    bind_port: int
    localhost_only: bool
    access_token_enabled: bool
    running_as_root: bool
    effective_uid: int
    username: str


def is_local_host(host: str) -> bool:
    return host in _LOCAL_HOSTS


def build_request_security_state(config: WebSecurityConfig) -> RequestSecurityState:
    uid_getter = getattr(os, "geteuid", None)
    uid = int(uid_getter()) if callable(uid_getter) else -1
    try:
        username = os.getlogin()
    except OSError:
        username = os.environ.get("USER", "unknown")
    return RequestSecurityState(
        bind_host=config.bind_host,
        bind_port=config.bind_port,
        localhost_only=config.localhost_only,
        access_token_enabled=config.token_enabled,
        running_as_root=uid == 0,
        effective_uid=uid,
        username=username,
    )


def csrf_token_input(request: Request) -> Markup:
    token = getattr(request.state, "csrf_token", "")
    if not token:
        return Markup("")
    return Markup(f'<input type="hidden" name="csrf_token" value="{escape(token)}">')


def install_security(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        config: WebSecurityConfig = request.app.state.web_security
        request.state.web_security = build_request_security_state(config)
        request.state.csrf_token = request.cookies.get(config.csrf_cookie_name) or secrets.token_urlsafe(32)
        request.state._set_csrf_cookie = request.cookies.get(config.csrf_cookie_name) != request.state.csrf_token

        path = request.url.path
        if not path.startswith("/static"):
            access_token = config.access_token
            if access_token:
                supplied_token = (
                    request.headers.get("x-chrootctl-token")
                    or request.query_params.get("access_token")
                    or request.cookies.get(config.auth_cookie_name)
                )
                if supplied_token != access_token:
                    return PlainTextResponse("access token required", status_code=401)
                request.state._set_auth_cookie = request.cookies.get(config.auth_cookie_name) != access_token
            else:
                request.state._set_auth_cookie = False

            if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                submitted_token = request.headers.get("x-csrf-token")
                if submitted_token is None:
                    content_type = (request.headers.get("content-type") or "").lower()
                    if "application/x-www-form-urlencoded" in content_type:
                        body = await request.body()
                        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True)
                        submitted_token = "".join(fields.get("csrf_token", [""]))
                    elif "multipart/form-data" in content_type:
                        body = await request.body()
                        marker = b'name="csrf_token"'
                        if marker in body:
                            tail = body.split(marker, 1)[1]
                            parts = tail.split(b"\r\n\r\n", 1)
                            if len(parts) == 2:
                                submitted_token = parts[1].split(b"\r\n", 1)[0].decode("utf-8")
                if not submitted_token or submitted_token != request.state.csrf_token:
                    return PlainTextResponse("csrf validation failed", status_code=403)

        response = await call_next(request)

        if getattr(request.state, "_set_csrf_cookie", False):
            response.set_cookie(
                config.csrf_cookie_name,
                request.state.csrf_token,
                httponly=True,
                samesite="strict",
                secure=False,
                path="/",
            )
        if config.access_token and getattr(request.state, "_set_auth_cookie", False):
            response.set_cookie(
                config.auth_cookie_name,
                config.access_token,
                httponly=True,
                samesite="strict",
                secure=False,
                path="/",
            )
        return response
