# Phase 16-17: Catalog, packages, transfer and artifacts

Phase 16 adds native catalog and package-intelligence surfaces for the Android app while keeping Python as the only implementation of catalog rules and package inventory parsing.

Delivered bridge contracts:

- `catalog.tools`
- `catalog.addons`
- `catalog.search`
- `catalog.preview`
- `catalog.apply`
- `packages.inventory`
- `packages.compare`

Delivered Android surfaces:

- catalog cards in Tools
- tool/add-on mode chips
- target chroot entry
- search and category filters
- entry selection
- preview/apply foreground operation wiring
- package inventory and package comparison panels

Phase 17 adds native transfer and managed artifact flows. Browser uploads/downloads remain available only as WebUI compatibility while Android gains document-picker staging and fixed AIDL descriptor copying.

Delivered bridge contracts:

- `transfer.inspect_import`
- `transfer.import`
- `transfer.preview_export`
- `transfer.export`
- `artifacts.list`
- `artifacts.cleanup`

Delivered Android transfer pieces:

- Android `OpenDocument` import picker
- fixed root-service `transferFromDescriptor` staging method
- Android `CreateDocument` export picker
- fixed root-service `transferToDescriptor` copy method
- import inspection and import operation controls
- export preview and export operation controls
- managed artifact list and cleanup operation wiring

Guardrails retained:

- SDK remains pinned to 36
- no WebView
- no arbitrary-shell AIDL
- no broad storage permission
- no `QUERY_ALL_PACKAGES`
- no direct Kotlin `Manifest.permission.POST_NOTIFICATIONS`
- no fragile `combine(arrayOf(...))`
- no Kotlin hardcoded `/data/` path literal
