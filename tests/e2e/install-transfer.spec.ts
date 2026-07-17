import { test, expect } from "@playwright/test";

test("install wizard can submit a seeded guided install flow", async ({ page }) => {
  await page.route("**/install", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 303,
      headers: { location: "/jobs/e2e-install-submit?toast=Install+job+queued" },
      body: "",
    });
  });

  await page.goto("/install");
  await expect(page.getByText("Queue a guided install job")).toBeVisible();
  await page.getByLabel("Chroot name").fill("androidos");
  await page.getByRole("button", { name: "Start install" }).click();
  await expect(page).toHaveURL(/\/jobs\/e2e-install-submit\?toast=Install\+job\+queued/);
});

test("transfer page covers seeded inspect and import submits", async ({ page }) => {
  await page.route("**/transfer/inspect", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body: `<!doctype html><html><body><main><h1>Inspection ready</h1><p>checksum verified</p></main></body></html>`,
    });
  });
  await page.route("**/transfer/import", async (route) => {
    await route.fulfill({
      status: 303,
      headers: { location: "/jobs/e2e-transfer-import?toast=Import+queued" },
      body: "",
    });
  });

  await page.goto("/transfer");
  await expect(page.getByText("Export, inspect, and import tar.zst chroots")).toBeVisible();

  await page.getByRole("textbox", { name: "Archive path" }).last().fill("/tmp/androidos.tar.zst");
  await page.getByRole("button", { name: "Inspect archive path" }).click();
  await expect(page.getByText("Inspection ready")).toBeVisible();

  await page.goto("/transfer");
  await page.getByRole("textbox", { name: "Archive path" }).last().fill("/tmp/androidos.tar.zst");
  await page.getByRole("textbox", { name: "Target name" }).fill("androidos-imported");
  await page.getByRole("button", { name: "Import archive" }).click();
  await expect(page).toHaveURL(/\/jobs\/e2e-transfer-import\?toast=Import\+queued/);
});


test("transfer export confirms and download link works in fixture mode", async ({ page }) => {
  await page.route("**/transfer/export", async (route) => {
    await route.fulfill({
      status: 303,
      headers: { location: "/jobs/e2e-transfer-export?toast=Export+queued" },
      body: "",
    });
  });
  await page.route("**/transfer/download/androidos", async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/zstd",
        "content-disposition": 'attachment; filename="androidos.tar.zst"',
      },
      body: "fixture-archive",
    });
  });

  await page.goto("/transfer");
  await page.getByRole("button", { name: "Queue export" }).first().click();
  await expect(page.getByText("Confirm chroot export")).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: /Download androidos\.tar\.zst/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("androidos.tar.zst");

  await page.goto("/transfer");
  await page.getByRole("button", { name: "Queue export" }).first().click();
  await page.getByRole("button", { name: "Queue export" }).last().click();
  await expect(page).toHaveURL(/\/jobs\/e2e-transfer-export\?toast=Export\+queued/);
});
