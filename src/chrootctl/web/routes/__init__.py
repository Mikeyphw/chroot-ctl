from .quickstart import router as quickstart_router
from .api import router as api_router
from .catalog import router as catalog_router
from .chroots import router as chroots_router
from .dashboard import router as dashboard_router
from .docs import router as docs_router
from .faq import router as faq_router
from .install import router as install_router
from .jobs import router as jobs_router
from .ksu import router as ksu_router
from .system import router as system_router
from .users import router as users_router
from .transfer import router as transfer_router
from .build import router as build_router
from .support import router as support_router
from .services import router as services_router

__all__ = [
    "api_router",
    "catalog_router",
    "chroots_router",
    "dashboard_router",
    "docs_router",
    "faq_router",
    "install_router",
    "jobs_router",
    "quickstart_router",
    "ksu_router",
    "system_router",
    "users_router",
    "transfer_router",
    "build_router",
    "support_router",
    "services_router",
]
