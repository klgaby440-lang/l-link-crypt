const { test, expect } = require("@playwright/test");

test("le Web charge ses bibliothèques UI sans importer le moteur local et refuse le mode hors ligne", async ({ page }) => {
  const nativeRequests = [];
  const uiRequests = [];
  const pageErrors = [];
  page.on("request", request => {
    const url = request.url();
    // Les bibliothèques d'interface locales sont partagées par le Web et le natif.
    // Seuls le runtime offline, l'ONNX et les ressources OCR sont interdits sur le Web.
    if (/offline-engine\.js|\/vendor\/(?:transformers|tesseract|firebase-runtime|onnxruntime)(?:[./?]|$)|\/models\/|\/tessdata\//i.test(url)) {
      nativeRequests.push(url);
    }
    if (/\/vendor\/(?:tailwind\.min\.css|lucide\.min\.js|dexie\.min\.js|marked\.umd\.js|purify\.min\.js)(?:\?|$)/i.test(url)) {
      uiRequests.push(url);
    }
  });
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.route("https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js", route => route.fulfill({
    status: 200, contentType: "application/javascript",
    body: "export const initializeApp=(config)=>({config}); export const getApps=()=>[]; export const getApp=()=>({});"
  }));
  await page.route("https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js", route => route.fulfill({
    status: 200, contentType: "application/javascript",
    body: `export const getAuth=()=>({currentUser:null}); export const signInWithPopup=async()=>null; export const signInWithCustomToken=async()=>({user:{uid:"desktop-user"}}); export class GoogleAuthProvider{}; export const onAuthStateChanged=(auth,cb)=>{Promise.resolve().then(()=>cb(null));return ()=>{};}; export const signOut=async()=>{};`
  }));

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => typeof window.canUseLlinkOffline === "function" && !!window.auth);
  expect(await page.evaluate(() => window.LLINK_PLATFORM.kind)).toBe("web");
  expect(await page.evaluate(() => window.canUseLlinkOffline())).toBe(false);
  expect(await page.evaluate(() => typeof window.Dexie)).toBe("function");
  expect(await page.evaluate(() => !!window.LLINK_SERVER_URL)).toBe(true);
  expect(uiRequests.some(url => url.includes("tailwind.min.css"))).toBe(true);
  expect(uiRequests.some(url => url.includes("lucide.min.js"))).toBe(true);
  expect(uiRequests.some(url => url.includes("dexie.min.js"))).toBe(true);
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

test("Tauri accepte une connexion Google confirmée par le custom claim Firebase", async ({ page }) => {
  await page.addInitScript(() => { window.__TAURI_INTERNALS__ = {}; });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => typeof window.canUseLlinkOffline === "function");
  const result = await page.evaluate(() => {
    window.auth = { currentUser: { uid: "desktop-google-user", providerData: [] } };
    window.LLINK_GOOGLE_AUTH_UID = "desktop-google-user";
    return { platform: window.LLINK_PLATFORM.kind, accepted: window.canUseLlinkOffline() };
  });
  expect(result.platform).toBe("tauri");
  expect(result.accepted).toBe(true);
});
