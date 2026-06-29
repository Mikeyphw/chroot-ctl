
import { test, expect } from "@playwright/test";

test("repair page previews fixes and opens confirmation modal", async ({ page }) => {
  await page.route("**/api/registry/repair/apply-selective", async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload?.decisions?.length).toBeGreaterThan(0);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "queued", location: "/jobs/e2e-repair?toast=Repair+queued" }),
    });
  });

  await page.goto("/repair");
  await expect(page.getByText("Review and repair drift")).toBeVisible();
  await page.getByRole("button", { name: "Preview selected fixes" }).click();
  await expect(page.getByText("Preview ready")).toBeVisible();
  await page.getByRole("button", { name: "Apply selected fixes" }).click();
  await expect(page.getByText("Review repair plan before queueing")).toBeVisible();
  await expect(page.getByText("Current state")).toBeVisible();
  await expect(page.getByText("Planned state")).toBeVisible();
  await expect(page.getByRole("button", { name: "Queue repair job" })).toBeVisible();
  await page.getByRole("button", { name: "Queue repair job" }).click();
  await expect(page).toHaveURL(/toast=Repair\+queued/);
});

test("failed job supports retry replay and latest snapshot recovery actions", async ({ page }) => {
  await page.route("**/api/jobs/e2e-failed-install/retry", async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload).toBeTruthy();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "queued", location: "/jobs/e2e-failed-install?toast=Retry+queued" }),
    });
  });
  await page.route("**/api/chroots/androidos/recovery/latest-snapshot", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "queued", location: "/jobs/e2e-failed-install?toast=Snapshot+recovery+queued" }),
    });
  });

  await page.goto("/jobs/e2e-failed-install");
  await expect(page.getByText("Failure summary")).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry now" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Retry with fixes/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Restore latest snapshot/ })).toBeVisible();

  await page.getByRole("button", { name: "Retry now" }).click();
  await expect(page.getByText("Confirm retry")).toBeVisible();
  await page.getByRole("button", { name: "Queue retry" }).click();
  await expect(page).toHaveURL(/toast=Retry\+queued/);

  await page.goto("/jobs/e2e-failed-install");
  await page.getByRole("button", { name: /Restore latest snapshot/ }).click();
  await expect(page.getByText("Confirm latest snapshot recovery")).toBeVisible();
  await page.getByRole("button", { name: "Queue snapshot recovery" }).click();
  await expect(page).toHaveURL(/toast=Snapshot\+recovery\+queued/);
});

test("quick start highlights seeded recovery entry flow", async ({ page }) => {
  await page.goto("/quickstart");
  await expect(page.getByText("Quick start")).toBeVisible();
  await expect(page.getByText("androidos")).toBeVisible();
  await expect(page.getByText("Fixture mode is enabled for browser tests.")).toBeVisible();
});
