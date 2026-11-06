import { request, type FullConfig } from "@playwright/test";
import { readFileSync, chmodSync } from "node:fs";
export default async function setup(config: FullConfig) {
  const path = process.env.CRYPTOLENS_TEST_CREDENTIALS;
  if (!path) return;
  const account = JSON.parse(readFileSync(path, "utf8"))[0];
  const baseURL = config.projects[0].use.baseURL!;
  const api = await request.newContext({ baseURL, ignoreHTTPSErrors: true });
  const response = await api.post("/api/v1/auth/login", {
    headers: { Origin: baseURL },
    data: { username: account.username, password: account.password },
  });
  if (!response.ok())
    throw new Error(`Test account login failed: ${response.status()}`);
  await api.storageState({ path: "../.local/browser-auth.json" });
  chmodSync("../.local/browser-auth.json", 0o600);
  await api.dispose();
}
