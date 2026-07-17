import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  use: {
    baseURL: process.env.CHROOTCTL_E2E_BASE_URL || "http://127.0.0.1:8420",
    trace: "retain-on-failure",
  },
  webServer: process.env.CHROOTCTL_E2E_SKIP_SERVER ? undefined : {
    command: "CHROOTCTL_E2E_FIXTURES=1 CHROOTCTL_E2E_DASHBOARD_MODE=dense python3 -m chrootctl.web --dry-run",
    url: "http://127.0.0.1:8420",
    reuseExistingServer: true,
    timeout: 120000,
  },
});
