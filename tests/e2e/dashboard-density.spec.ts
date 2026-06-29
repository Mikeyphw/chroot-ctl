
import { test, expect } from "@playwright/test";

test("fixture dashboard mode shows multiple chroots and mixed job states", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "androidos" })).toBeVisible();
  await expect(page.getByRole("link", { name: "devbox" })).toBeVisible();
  await expect(page.getByRole("link", { name: "rescue" })).toBeVisible();
  await expect(page.getByRole("link", { name: "fedora-dev" })).toBeVisible();

  await expect(page.getByText("Fixture failed install")).toBeVisible();
  await expect(page.getByText("Fixture devbox upgrade")).toBeVisible();
  await expect(page.getByText("Fixture registry repair")).toBeVisible();

  await expect(page.getByText("Registered chroots")).toBeVisible();
  await expect(page.getByText("Recent jobs")).toBeVisible();
  await expect(page.getByText(/Filesystem and registry drift detected/i)).toBeVisible();
});

test("fixture dashboard mode exercises grid density and mixed card states", async ({ page }) => {
  await page.goto("/");
  const chips = page.locator(".chip");
  await expect(chips.filter({ hasText: /installed|pending/i })).toHaveCount(4);
  await expect(page.getByText("1 fail / 1 warn")).toBeVisible();
  await expect(page.getByText("0 fail / 2 warn")).toBeVisible();
});
