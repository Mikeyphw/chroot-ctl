#!/usr/bin/env sh
set -eu
echo "== chrootctl root module: test =="
node --check internal/module/webroot/kernelsu.js
node --check internal/module/webroot/chrootctl.js
node --check internal/module/webroot/index.js
if [ -f internal/module/webui_transport_test.mjs ]; then node internal/module/webui_transport_test.mjs; fi
if [ -f internal/module/webui_bridge_ui_test.mjs ]; then node internal/module/webui_bridge_ui_test.mjs; fi
go test ./internal/module ./internal/bridge ./internal/operations ./internal/users ./internal/services ./internal/rcloneops ./internal/catalog ./internal/repoctl ./internal/config ./internal/logging ./internal/clipboard
