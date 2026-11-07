const { test, expect } = require("@playwright/test");

test("Live restaure les commandes vocales de référence et le portrait fixe dans l'appel vidéo", async ({ page }) => {
  const avatarRendererRequests = [];
  page.on("request", request => {
    if (/live-avatar\.js|three\.min\.js/i.test(request.url())) avatarRendererRequests.push(request.url());
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => typeof window.selectAppMode === "function"
      && typeof window.openLiveVideoCall === "function",
    { timeout: 45_000 }
  );

  await page.evaluate(() => window.selectAppMode("voice"));
  await expect(page.locator("#live-visual")).toBeVisible();
  await expect(page.locator(".live-wave-lines")).toBeVisible();
  await expect(page.locator(".live-wave-lines span")).toHaveCount(43);
  await expect(page.locator("#live-plus-button")).toBeVisible();

  // Les actions vidéo, micro, son et voix restent dans le menu vocal d'origine.
  await page.locator("#live-plus-button").click();
  await expect(page.locator("#live-effects-menu")).toBeVisible();
  await expect(page.locator('#live-effects-menu [aria-label="Appel vidéo"]')).toBeVisible();
  await expect(page.locator('#live-effects-menu [aria-label="Muet"]')).toBeVisible();
  await expect(page.locator('#live-effects-menu [aria-label="Voix"]')).toBeVisible();

  await page.locator('#live-effects-menu [aria-label="Appel vidéo"]').click();
  await expect(page.locator("#llcall")).toBeVisible();
  await expect(page.locator("#llcall-tile-ai")).toBeVisible();
  const portrait = page.locator("#llcall-tile-ai img.lia-svg");
  await expect(portrait).toBeVisible();
  await expect(portrait).toHaveAttribute("src", "./assets/lia-avatar.png");
  await expect(page.locator("#llcall-btn-mic")).toBeVisible();
  await expect(page.locator("#llcall-btn-cam")).toBeVisible();

  // Aucun renderer 3D/animé n'est chargé : le visage reste l'image exacte de référence.
  expect(avatarRendererRequests).toEqual([]);
  await expect(page.locator("#llcall-tile-ai canvas")).toHaveCount(0);

  await page.locator('#llcall [data-c="hang"]').click();
  await expect(page.locator("#llcall")).toBeHidden();
  // La vidéo est un panneau du Live vocal : raccrocher la vidéo revient à la voix.
  await expect(page.locator("body")).toHaveClass(/live-mode-active/);
  await expect(page.locator("#live-visual")).toBeVisible();
});
