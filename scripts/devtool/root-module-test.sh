#!/usr/bin/env sh
set -eu
echo "== chrootctl root module: test =="
node --check internal/module/webroot/kernelsu.js
node --check internal/module/webroot/chrootctl.js
node --check internal/module/webroot/index.js
if [ -f internal/module/webui_transport_test.mjs ]; then node internal/module/webui_transport_test.mjs; fi
if [ -f internal/module/webui_bridge_ui_test.mjs ]; then node internal/module/webui_bridge_ui_test.mjs; fi
if [ -f internal/module/webui_post_cux_transport_test.mjs ]; then node internal/module/webui_post_cux_transport_test.mjs; fi
if [ -f internal/module/webui_install_failure_transport_test.mjs ]; then node internal/module/webui_install_failure_transport_test.mjs; fi
go test ./internal/module ./internal/bridge ./internal/operations ./internal/users ./internal/services ./internal/rcloneops ./internal/catalog ./internal/repoctl ./internal/config ./internal/logging ./internal/clipboard

# TMUX-01 static runtime contract tests do not require network/build execution.
go test ./internal/repoctl -run 'TestTMUX01'
bash scripts/tmux/test-android-glob-compat.sh
bash scripts/tmux/test-android-langinfo-compat.sh
scripts/devtool/root-module-evidence.sh record root_test 'scripts/devtool/root-module-test.sh'
