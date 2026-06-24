import { test, expect } from "@playwright/test";

test("build page and jobs page load", async ({ page }) => {
  await page.goto("/build");
  await expect(page.getByText("Magisk module")).toBeVisible();
  await page.goto("/jobs");
  await expect(page.getByText("Jobs")).toBeVisible();
});
