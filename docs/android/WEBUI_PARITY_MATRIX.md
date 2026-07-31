# WebUI to Android parity matrix

This matrix is the migration gate for replacing the FastAPI/Jinja WebUI with the native Android application. WebUI code remains available only while a row is not yet marked **Native complete**.

| Existing surface | Current implementation | Native destination | Operation class | Migration state |
|---|---|---|---|---|
| Dashboard | `web/routes/dashboard.py` | Home | Read-only | Bridge ready |
| Quick Start | `web/routes/quickstart.py` | Home onboarding | Read-only | Contract mapped |
| Chroot list | `web/routes/chroots.py` | Chroots | Read-only | Bridge ready |
| Chroot detail | `web/routes/chroots.py` | Chroot detail | Read-only | Bridge ready |
| Chroot status | `web/routes/system.py` | Overview / Diagnostics | Read-only | Bridge ready |
| Chroot doctor | `web/routes/system.py` | Overview / Diagnostics | Read-only | Bridge ready |
| Install wizard | `web/routes/install.py` | Native install flow | Mutating, streaming | Planned |
| Install preview | `web/routes/install.py` | Native install review | Preview | Planned |
| Install retry | `web/routes/install.py` | Activity operation recovery | Mutating, streaming | Planned |
| Jobs list | `web/routes/jobs.py` | Activity | Read-only | Persistent engine ready |
| Job detail | `web/routes/jobs.py` | Operation detail | Read-only | Persistent engine ready |
| Job event stream | `web/routes/jobs.py` | Foreground operation stream | Streaming | NDJSON foundation ready |
| Chroot start | `web/routes/chroots.py` | Chroot detail | Mutating | Planned |
| Chroot restart | `web/routes/chroots.py` | Chroot detail | Mutating | Planned |
| Chroot rename | `web/routes/chroots.py` | Guarded overflow action | Destructive | Planned |
| Chroot removal | `web/routes/chroots.py` | Guarded overflow action | Destructive | Preview bridge ready |
| Package difference | `web/routes/chroots.py` | Packages | Read-only | Planned |
| Snapshot list | `web/routes/chroots.py` | Snapshots | Read-only | Planned |
| Snapshot create | `web/routes/chroots.py` | Snapshots | Mutating | Planned |
| Snapshot restore | `web/routes/chroots.py` | Recovery | Destructive | Planned |
| Snapshot export | `web/routes/chroots.py` | Android document picker | Streaming | Planned |
| Transfer inspect | `web/routes/transfer.py` | Import review | Read-only | Planned |
| Transfer import | `web/routes/transfer.py` | Android document picker | Mutating, streaming | Planned |
| Transfer export | `web/routes/transfer.py` | Android document picker | Streaming | Preview bridge ready |
| Chunked HTTP upload | `web/routes/transfer.py` | File descriptor streaming | Browser-only replacement | Remove after parity |
| Users list/detail | `web/routes/users.py` | Users | Read-only | Planned |
| User add/update/remove | `web/routes/users.py` | Users | Mutating / destructive | Planned |
| User password | `web/routes/users.py` | Ephemeral pipe input | Sensitive mutation | Planned |
| Services list/detail | `web/routes/services.py` | Services | Read-only | Planned |
| Service start/stop/restart | `web/routes/services.py` | Services | Mutating | Planned |
| Service enable/disable | `web/routes/services.py` | Services | Mutating | Planned |
| Service journal | `web/routes/services.py` | Service detail | Read-only | Planned |
| Tools catalog | `web/routes/catalog.py` | Tools / Catalog | Read-only | Planned |
| Add-ons catalog | `web/routes/catalog.py` | Tools / Catalog | Read-only | Planned |
| Catalog apply | `web/routes/catalog.py` | Catalog operation | Mutating, streaming | Planned |
| Registry repair | `web/routes/system.py` | Recovery | Destructive | Planned |
| Logs | `web/routes/system.py` | Activity / Diagnostics | Read-only | Planned |
| Checks | `web/routes/system.py` | Diagnostics | Read-only | Planned |
| Audit events | `web/routes/support.py` | Activity / Diagnostics | Read-only | Planned |
| Support bundle | `web/routes/support.py` | Support | Streaming artifact | Planned |
| KernelSU controls | `web/routes/ksu.py` | Tools / System | Mutating | Planned |
| Module build | `web/routes/build.py` | Tools / Module | Streaming artifact | Planned |
| API reference | `web/routes/docs.py` | Protocol documentation | Documentation | Contract started |
| FAQ | `web/routes/faq.py` | Native Help | Documentation | Planned |
| CSRF/access token | `web/security.py` | Not needed for Binder bridge | Browser-only removal | Retire with WebUI |
| FastAPI HTTP server | `web/app.py` | libsu RootService | Browser-only removal | Root bridge scaffold ready |

## Retirement rule

The WebUI may be deleted only when every feature row is **Native complete**, Android destructive-action policies pass, and the repository contains no remaining operational dependency on FastAPI, Jinja, Uvicorn, browser tokens, upload endpoints, or localhost port 8420.

## Route inventory

Mapped route modules: api.py, build.py, catalog.py, chroots.py, dashboard.py, docs.py, faq.py, install.py, jobs.py, ksu.py, quickstart.py, services.py, support.py, system.py, transfer.py, users.py.
