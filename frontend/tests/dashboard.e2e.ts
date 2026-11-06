import { test, expect } from "@playwright/test";
test("market, search, detail, rankings and analyst states", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Market Overview", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Bitcoin", { exact: true }).first()).toBeVisible({
    timeout: 30000,
  });
  await page
    .getByRole("button", { name: "Asset Explorer", exact: true })
    .click();
  await page.getByRole("textbox", { name: "Search assets" }).fill("ethereum");
  await expect(
    page.getByRole("button", { name: "Ethereum ETH", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Ethereum ETH", exact: true }).click();
  await expect(
    page.getByRole("img", { name: "Daily OHLC candlestick chart" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "30D", exact: true }).click();
  await page
    .getByRole("button", { name: "Risk Analytics", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Risk ranking", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Aligned daily returns", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "AI Analyst", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Ask the AI analyst" })
    .fill("Analyze Bitcoin risk");
  await expect(
    page.getByRole("button", { name: "Analyze", exact: true }),
  ).toBeEnabled();
  // Live model evaluation is separate; E2E must never spend tokens.
  await page.route("**/api/v1/ai/chat/stream", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "AI disabled for deterministic test" }),
    }),
  );
  await page.getByRole("button", { name: "Analyze", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "disabled" }),
  ).toBeVisible();
});
test("mobile layout stays within viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Market Overview", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("provider discovery, technical indicators and DeFi research", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Asset Explorer", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Search provider universe" })
    .fill("bitcoin");
  await expect(
    page
      .getByRole("region", { name: "Virtualized provider universe" })
      .getByText("Bitcoin", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("region", { name: "Virtualized provider universe" })
    .getByRole("button", { name: "Analyze", exact: true })
    .click();
  await page.getByLabel("Technical interval").selectOption("1h");
  await expect(
    page.getByRole("img", { name: "Hourly OHLC candlestick chart" }),
  ).toBeVisible();
  await page.getByLabel("Technical indicator").selectOption("macd");
  await expect(page.getByRole("img", { name: "macd chart" })).toBeVisible();
  await page
    .getByRole("button", { name: "Risk Analytics", exact: true })
    .click();
  await page.getByLabel("Ranking preset").selectOption("sharpe");
  await expect(
    page.getByText(
      "Sharpe ranking requires an explicit annual risk-free assumption",
    ),
  ).toBeVisible();
  await page.getByLabel("Risk-free assumption").fill("4");
  await expect(
    page.getByText(
      "Sharpe ranking requires an explicit annual risk-free assumption",
    ),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "DeFi Research", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Aave protocol exploration" }),
  ).toBeVisible();
  await expect(
    page.getByText("qualitative risk inventory; not a numeric rating"),
  ).toBeVisible();
});

test("validated stream renders a grounded report", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "AI Analyst", exact: true }).click();
  await page.route("**/api/v1/ai/chat/stream", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: [
        { stage: "received", session_id: "browser-fixture" },
        {
          stage: "validated_text",
          chunk: "Historical evidence.",
          session_id: "browser-fixture",
        },
        {
          stage: "completed",
          session_id: "browser-fixture",
          result: {
            answer: "Historical evidence.",
            key_findings: [],
            evidence: {},
            limitations: ["Synthetic browser fixture"],
            model: "test",
          },
        },
      ]
        .map((value) => "data: " + JSON.stringify(value) + "\n\n")
        .join(""),
    }),
  );
  await page.getByLabel("Ask the AI analyst").fill("Bitcoin historical risk");
  await page.getByRole("button", { name: "Analyze", exact: true }).click();
  await expect(page.getByText("Historical evidence.")).toBeVisible();
  await expect(page.getByText("BACKEND-GROUNDED FINDINGS")).toBeVisible();
});
