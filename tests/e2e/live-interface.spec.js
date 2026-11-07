const { test, expect } = require("@playwright/test");

test("Live partage le même visage 3D entre l'écran vocal et l'appel vidéo", async ({ page }) => {
  // Le test vérifie le fallback et les transitions d'interface sans dépendre du CDN WebGL.
  await page.route("https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js", route => route.abort());

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => typeof window.selectAppMode === "function"
      && typeof window.connectLlinkLiveSession === "function",
    { timeout: 45_000 }
  );

  await page.evaluate(() => window.selectAppMode("voice"));
  await expect(page.locator("#live-avatar-stage")).toBeVisible();
  await expect(page.locator("#live-voice-mic")).toBeVisible();
  await expect(page.locator("#live-voice-video")).toBeVisible();
  await expect(page.locator("#live-avatar-status")).toContainText("Connecte-toi");

  // Sans compte de test, le bouton micro ne démarre pas de flux audio ni de session fictive.
  await page.locator("#live-voice-mic").click();
  await expect(page.locator("#live-avatar-status")).toContainText("Connexion au service vocal en cours");

  await page.locator("#live-voice-video").click();
  await expect(page.locator("#llcall")).toBeVisible();
  await expect(page.locator("#llcall-tile-ai")).toBeVisible();
  await expect(page.locator("#llcall-btn-mic")).toBeVisible();

  // Raccrocher termine toute la session Live et revient au mode précédent.
  await page.locator('#llcall [data-c="hang"]').click();
  await expect(page.locator("#llcall")).toBeHidden();
  await expect(page.locator("body")).not.toHaveClass(/live-mode-active/);
});
