import { test, expect } from "@playwright/test";

test("build page and jobs page load with seeded job cards", async ({ page }) => {
  await page.goto("/build");
  await expect(page.getByText("Magisk module")).toBeVisible();
  await page.goto("/jobs");
  await expect(page.getByText("Fixture failed install")).toBeVisible();
  await expect(page.getByText("Fixture module build")).toBeVisible();
});
