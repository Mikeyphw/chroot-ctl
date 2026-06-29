
import { test, expect } from "@playwright/test";

const pages: Array<[string, RegExp]> = [
  ["/chroots/devbox", /devbox|Use this chroot/i],
  ["/chroots/rescue", /rescue|Use this chroot/i],
  ["/chroots/fedora-dev", /fedora-dev|Use this chroot/i],
  ["/jobs/e2e-upgrade-running", /Installing package updates|Fixture devbox upgrade/i],
  ["/jobs/e2e-repair-queued", /Waiting for maintenance slot|Fixture registry repair/i],
];

for (const [path, matcher] of pages) {
  test(`seeded multi-target page ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByText(matcher).first()).toBeVisible();
  });
}
