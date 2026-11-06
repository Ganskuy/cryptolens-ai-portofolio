import { defineConfig } from "@playwright/test";
export default defineConfig({
  globalSetup: "./tests/setup.ts",
  testDir: "./tests",
  testMatch: "*.e2e.ts",
  use: {
    baseURL: process.env.CRYPTOLENS_BASE_URL || "http://localhost:3100",
    screenshot: "only-on-failure",
    ignoreHTTPSErrors: !!process.env.CRYPTOLENS_TEST_CREDENTIALS,
    storageState: process.env.CRYPTOLENS_TEST_CREDENTIALS
      ? "../.local/browser-auth.json"
      : undefined,
  },
  reporter: "list",
});
