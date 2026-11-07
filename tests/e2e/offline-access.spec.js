const { test, expect } = require("@playwright/test");

test("le Web n'importe jamais le moteur local et refuse le mode hors ligne", async ({ page }) => {
  const nativeRequests = [];
  const pageErrors = [];
  page.on("request", request => {
    if (/offline-engine\.js|\/vendor\//i.test(request.url())) nativeRequests.push(request.url());
  });
  page.on("pageerror", error => pageErrors.push(error.message));

  // Les CDNs sont simulés à partir des fichiers construits en CI : le test
  // vérifie la sélection de plateforme, pas la disponibilité d'Internet.
  await page.route("https://cdn.tailwindcss.com", route => route.fulfill({
    status: 200, contentType: "application/javascript",
    body: "window.tailwind=window.tailwind||{};"
  }));
  await page.route("https://unpkg.com/lucide@1.70.0/dist/umd/lucide.js", route => route.fulfill({
    status: 200, contentType: "application/javascript",
    body: "window.lucide={createIcons:function(){}};"
  }));
  await page.route("https://unpkg.com/dexie@4.4.7/dist/dexie.js", route => route.fulfill({
    path: require("path").join(__dirname, "../../app/vendor/dexie.min.js")
  }));
  await page.route("https://cdn.jsdelivr.net/npm/marked@18.1.2/lib/marked.umd.js", route => route.fulfill({
    path: require("path").join(__dirname, "../../app/vendor/marked.umd.js")
  }));
  await page.route("https://cdn.jsdelivr.net/npm/dompurify@3.4.17/dist/purify.min.js", route => route.fulfill({
    path: require("path").join(__dirname, "../../app/vendor/purify.min.js")
  }));
  await page.route("https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js", route => route.fulfill({
    status: 200, contentType: "application/javascript",
    body: "export const initializeApp=(config)=>({config}); export const getApps=()=>[]; export const getApp=()=>({});"
  }));
  await page.route("https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js", route => route.fulfill({
    status: 200, contentType: "application/javascript",
    body: "export const getAuth=()=>({currentUser:null}); export const signInWithPopup=async()=>null; export class GoogleAuthProvider{}; export const onAuthStateChanged=(auth,cb)=>{Promise.resolve().then(()=>cb(null));return ()=>{};}; export const signOut=async()=>{};"
  }));

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => typeof window.canUseLlinkOffline === "function" && !!window.auth);
  expect(await page.evaluate(() => window.LLINK_PLATFORM.kind)).toBe("web");
  expect(await page.evaluate(() => window.canUseLlinkOffline())).toBe(false);
  expect(await page.evaluate(() => typeof window.Dexie)).toBe("function");
  expect(await page.evaluate(() => !!window.LLINK_SERVER_URL)).toBe(true);
  expect(nativeRequests).toEqual([]);
  expect(pageErrors.filter(message => /Dexie|SERVER_URL|Firebase local/i.test(message))).toEqual([]);
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
    return { passwordOnly, google, platform: window.LLINK_PLATFORM.kind };
  });
  expect(results.platform).toBe("capacitor");
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
    return { anonymous, google, platform: window.LLINK_PLATFORM.kind };
  });
  expect(results.platform).toBe("tauri");
  expect(results.anonymous).toBe(false);
  expect(results.google).toBe(true);
});
