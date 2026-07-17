from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..services import create_service_container
from .jobs import WebJobManager
from .error_handling import install_exception_handlers
from .e2e_fixtures import install_e2e_fixtures
from .routes import api_router, build_router, catalog_router, chroots_router, dashboard_router, docs_router, faq_router, install_router, jobs_router, quickstart_router, system_router, users_router, ksu_router, transfer_router, support_router
from .security import WebSecurityConfig, csrf_token_input, install_security, is_local_host

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8420


def create_app(
    *,
    config_path: Path | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    bind_host: str = DEFAULT_HOST,
    bind_port: int = DEFAULT_PORT,
    access_token: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="chrootctl Web UI",
        description="Local management UI and API for chrootctl installs, jobs, transfer, and diagnostics.",
        docs_url="/api/openapi",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        openapi_tags=[
            {"name": "api", "description": "Machine-readable state, validation, transfer, and job APIs."},
            {"name": "install", "description": "Guided installer pages and install submission flow."},
            {"name": "transfer", "description": "Archive export, inspect, import, and download flows."},
            {"name": "docs", "description": "Human-friendly API help pages."},
            {"name": "support", "description": "Support bundle, FAQ, and audit pages."},
            {"name": "build", "description": "Magisk module build page and download flows."},
        ],
    )
    template_dir = Path(files("chrootctl").joinpath("web/templates"))
    static_dir = Path(files("chrootctl").joinpath("web/static"))
    app.state.services = create_service_container(config_path, dry_run=dry_run, verbose=verbose)
    app.state.jobs = WebJobManager()
    app.state.web_security = WebSecurityConfig(bind_host=bind_host, bind_port=bind_port, access_token=access_token)
    app.state.templates = Jinja2Templates(directory=str(template_dir))
    app.state.templates.env.globals["csrf_token_input"] = csrf_token_input
    install_security(app)
    install_exception_handlers(app)
    install_e2e_fixtures(app)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(dashboard_router)
    app.include_router(quickstart_router)
    app.include_router(docs_router)
    app.include_router(faq_router)
    app.include_router(support_router)
    app.include_router(api_router)
    app.include_router(chroots_router)
    app.include_router(transfer_router)
    app.include_router(build_router)
    app.include_router(users_router)
    app.include_router(catalog_router)
    app.include_router(system_router)
    app.include_router(install_router)
    app.include_router(jobs_router)
    app.include_router(ksu_router)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="chrootctl-web", description="Run the local chrootctl Web UI.")
    parser.add_argument("--config", type=Path, default=None, help="Optional config file path.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port. Defaults to 8420.")
    parser.add_argument("--access-token", default=None, help="Require this token for all requests when exposing the Web UI beyond localhost.")
    parser.add_argument("--dry-run", action="store_true", help="Run the UI with dry-run service operations.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging for the Web UI service layer.")
    args = parser.parse_args()
    if not is_local_host(args.host) and not args.access_token:
        parser.error("non-localhost binding requires --access-token")
    app = create_app(
        config_path=args.config,
        dry_run=args.dry_run,
        verbose=args.verbose,
        bind_host=args.host,
        bind_port=args.port,
        access_token=args.access_token,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
