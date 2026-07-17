import { test, expect } from "@playwright/test";

test("seeded pages expose recovery and operator context across the app", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/Filesystem and registry drift detected|Fastest working path/i)).toBeVisible();

  await page.goto("/transfer");
  await expect(page.getByText(/Finalize on device later/i)).toBeVisible();

  await page.goto("/tools");
  await expect(page.getByText("git")).toBeVisible();

  await page.goto("/addons");
  await expect(page.getByText("xfce-tweaks")).toBeVisible();

  await page.goto("/jobs/e2e-failed-install");
  await expect(page.getByText(/Choose user: no non-root users available/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Retry with fixes/i })).toBeVisible();
});
