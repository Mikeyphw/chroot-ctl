import { test, expect } from "@playwright/test";

test("chroot detail shows seeded snapshot history and queues restore", async ({ page }) => {
  await page.route("**/chroots/androidos/snapshots/snap-good-001/restore", async (route) => {
    await route.fulfill({
      status: 303,
      headers: { location: "/jobs/e2e-snapshot-restore?toast=Snapshot+restore+queued" },
      body: "",
    });
  });

  await page.goto("/chroots/androidos");
  await expect(page.getByText("Snapshots")).toBeVisible();
  await expect(page.getByText("snap-good-001")).toBeVisible();
  await page.getByRole("button", { name: "Restore" }).first().click();
  await expect(page).toHaveURL(/\/jobs\/e2e-snapshot-restore\?toast=Snapshot\+restore\+queued/);
});


test("chroot detail confirms upgrade before queueing", async ({ page }) => {
  await page.route("**/chroots/androidos/upgrade", async (route) => {
    await route.fulfill({
      status: 303,
      headers: { location: "/jobs/e2e-upgrade?toast=Upgrade+queued" },
      body: "",
    });
  });

  await page.goto("/chroots/androidos");
  await page.getByRole("button", { name: "Upgrade" }).click();
  await expect(page.getByText("Confirm chroot upgrade")).toBeVisible();
  await page.getByRole("button", { name: "Run upgrade" }).click();
  await expect(page).toHaveURL(/\/jobs\/e2e-upgrade\?toast=Upgrade\+queued/);
});
