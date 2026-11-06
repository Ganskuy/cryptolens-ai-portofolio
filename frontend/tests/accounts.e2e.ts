import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

test("account form signs in and revokes access on sign out", async ({
  browser,
}) => {
  test.skip(
    !process.env.CRYPTOLENS_TEST_CREDENTIALS,
    "Requires isolated TLS account fixture",
  );
  const credentials = JSON.parse(
    readFileSync(process.env.CRYPTOLENS_TEST_CREDENTIALS!, "utf8"),
  )[0];
  const context = await browser.newContext({
    baseURL: process.env.CRYPTOLENS_BASE_URL,
    ignoreHTTPSErrors: true,
    storageState: { cookies: [], origins: [] },
  });
  const page = await context.newPage();
  try {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "CryptoLens workspace" }),
    ).toBeVisible();
    await page
      .getByLabel("Username", { exact: true })
      .fill(credentials.username);
    await page
      .getByLabel("Password", { exact: true })
      .fill(credentials.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Market Overview", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "CryptoLens workspace" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Market Overview", exact: true }),
    ).toHaveCount(0);
  } finally {
    await context.close();
  }
});
