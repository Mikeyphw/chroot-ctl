import { test, expect } from "@playwright/test";

test("chroot destructive actions use the shared confirmation modal", async ({ page }) => {
  await page.route("**/chroots/androidos/upgrade", async (route) => {
    await route.fulfill({
      status: 303,
      headers: { location: "/jobs/e2e-upgrade?toast=Upgrade+queued" },
      body: "",
    });
  });
  await page.route("**/chroots/androidos/remove", async (route) => {
    await route.fulfill({
      status: 303,
      headers: { location: "/jobs/e2e-remove?toast=Remove+queued" },
      body: "",
    });
  });

  await page.goto("/chroots/androidos");
  await page.getByRole("button", { name: "Run upgrade" }).click();
  await expect(page.getByText("Confirm chroot upgrade")).toBeVisible();
  await page.getByRole("button", { name: "Run upgrade" }).last().click();
  await expect(page).toHaveURL(/toast=Upgrade\+queued/);

  await page.goto("/chroots/androidos");
  await page.getByLabel(/Type androidos to confirm/).fill("androidos");
  await page.getByRole("button", { name: "Remove chroot" }).click();
  await expect(page.getByText("Confirm chroot removal")).toBeVisible();
  await page.getByRole("button", { name: "Remove chroot" }).last().click();
  await expect(page).toHaveURL(/toast=Remove\+queued/);
});

test("support bundle and build downloads stay reachable in fixture mode", async ({ page }) => {
  await page.route("**/support/download**", async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/zip",
        "content-disposition": 'attachment; filename="chrootctl-support.zip"',
      },
      body: "fixture-bundle",
    });
  });
  await page.route("**/build/artifacts/e2e-build-success", async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/zip",
        "content-disposition": 'attachment; filename="chrootctl-magisk.zip"',
      },
      body: "fixture-module",
    });
  });

  await page.goto("/build");
  const buildDownload = page.waitForEvent("download");
  await page.getByRole("link", { name: /Download ZIP/i }).click();
  await expect((await buildDownload).suggestedFilename()).toBe("chrootctl-magisk.zip");

  const supportDownload = page.waitForEvent("download");
  await page.goto("/support/download?path=/tmp/chrootctl-support.zip");
  await expect((await supportDownload).suggestedFilename()).toBe("chrootctl-support.zip");
});
