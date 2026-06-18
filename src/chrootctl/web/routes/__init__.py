from .catalog import router as catalog_router
from .chroots import router as chroots_router
from .dashboard import router as dashboard_router
from .install import router as install_router
from .jobs import router as jobs_router
from .system import router as system_router
from .users import router as users_router

__all__ = [
    "catalog_router",
    "chroots_router",
    "dashboard_router",
    "install_router",
    "jobs_router",
    "system_router",
    "users_router",
]
