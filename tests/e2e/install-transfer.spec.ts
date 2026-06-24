import { test, expect } from "@playwright/test";

test("install wizard renders guided installer sections", async ({ page }) => {
  await page.goto("/install");
  await expect(page.getByText("Target user")).toBeVisible();
  await expect(page.getByText("Install summary")).toBeVisible();
});

test("transfer page supports inspect and upload actions", async ({ page }) => {
  await page.goto("/transfer");
  await expect(page.getByText("Inspect a tar.zst archive")).toBeVisible();
  await expect(page.getByText("Upload and import")).toBeVisible();
});
