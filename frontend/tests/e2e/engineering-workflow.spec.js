import { expect, test } from "@playwright/test";


test("engineer persists a design and completes the DOE-to-CAD workflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "System overview" })).toBeVisible();

  await page.getByRole("button", { name: /Design Space/ }).click();
  await expect(page.getByRole("heading", { name: "Design space" })).toBeVisible();
  const thickness = page.locator("label.range-row", { hasText: "Fin thickness" }).getByRole("slider");
  await thickness.fill("0.8");
  await page.getByRole("button", { name: /Save design space/ }).click();
  await expect(page.getByText(/PostgreSQL record/)).toBeVisible();

  await page.getByRole("button", { name: /DOE/ }).click();
  await page.getByRole("button", { name: /LHS/ }).click();
  await page.getByRole("button", { name: /Run DOE \+ Phase 1/ }).click();
  await expect(page.getByText(/Phase 1 complete/)).toBeVisible({ timeout: 180_000 });

  await page.getByRole("button", { name: /Analysis/ }).click();
  await expect(page.getByLabel("Residual QQ plot")).toBeVisible();
  await expect(page.getByLabel("Residual histogram")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Correlation matrix" })).toBeVisible();

  await page.getByRole("button", { name: /Digital Twin/ }).click();
  await expect(page.getByTestId("computed-response-surface")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByLabel("Computed response contour")).toBeVisible();

  await page.getByRole("button", { name: /CAD/ }).click();
  await expect(page.getByTestId("three-cad-viewer").locator("canvas")).toBeVisible();
});
