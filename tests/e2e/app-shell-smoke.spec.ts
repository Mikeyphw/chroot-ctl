import { test, expect } from "@playwright/test";

const pages: Array<[string, RegExp]> = [
  ["/", /Local chroot control|Fastest working path|Ready to install/i],
  ["/quickstart", /Quick start/i],
  ["/install", /Queue a guided install job/i],
  ["/chroots/androidos", /Use this chroot/i],
  ["/chroots/androidos/users", /Users/i],
  ["/chroots/androidos/users/mike", /User/i],
  ["/transfer", /Export, inspect, and import tar\.zst chroots/i],
  ["/build", /Magisk module/i],
  ["/jobs", /Recent activity|Live status/i],
  ["/jobs/e2e-failed-install", /Failure summary/i],
  ["/tools", /Search, preview, and apply tools/i],
  ["/addons", /Search, preview, and apply addons/i],
  ["/doctor", /Doctor/i],
  ["/doctor/host", /Doctor/i],
  ["/logs", /Live tail/i],
  ["/docs", /API docs and examples/i],
  ["/faq", /FAQ and troubleshooting/i],
  ["/support", /Support bundle and audit history/i],
  ["/ksu/status", /Module control panel/i],
];

for (const [path, matcher] of pages) {
  test(`page smoke ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByText(matcher).first()).toBeVisible();
  });
}
