const { test, expect } = require("@playwright/test");

test("le Web ne peut jamais activer le mode hors ligne, même avec un compte Google", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => typeof window.canUseLlinkOffline === "function");
  await page.evaluate(() => {
    window.auth = { currentUser: { providerData: [{ providerId: "google.com" }] } };
  });
  expect(await page.evaluate(() => window.canUseLlinkOffline())).toBe(false);
});

test("Capacitor Android exige un compte Google", async ({ page }) => {
  await page.addInitScript(() => {
    window.Capacitor = {
      isNativePlatform: () => true,
      getPlatform: () => "android"
    };
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => typeof window.canUseLlinkOffline === "function");
  const results = await page.evaluate(() => {
    window.auth = { currentUser: { providerData: [{ providerId: "password" }] } };
    const passwordOnly = window.canUseLlinkOffline();
    window.auth = { currentUser: { providerData: [{ providerId: "google.com" }] } };
    const google = window.canUseLlinkOffline();
    return { passwordOnly, google };
  });
  expect(results.passwordOnly).toBe(false);
  expect(results.google).toBe(true);
});

test("Tauri Windows est une application installée, mais exige toujours Google", async ({ page }) => {
  await page.addInitScript(() => {
    window.__TAURI_INTERNALS__ = {};
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => typeof window.canUseLlinkOffline === "function");
  const results = await page.evaluate(() => {
    window.auth = { currentUser: { providerData: [] } };
    const anonymous = window.canUseLlinkOffline();
    window.auth = { currentUser: { providerData: [{ providerId: "google.com" }] } };
    const google = window.canUseLlinkOffline();
    return { anonymous, google };
  });
  expect(results.anonymous).toBe(false);
  expect(results.google).toBe(true);
});
