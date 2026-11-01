const { test, expect } = require("@playwright/test");

const API = "https://llink-usz9.onrender.com";
const CORS_HEADERS = {
  "access-control-allow-origin": "http://127.0.0.1:4173",
  "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  "access-control-allow-headers": "Authorization, Content-Type",
  "access-control-max-age": "600",
  "vary": "Origin"
};

async function openWork(page) {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => typeof window.Dexie === "function"
      && typeof window.selectAppMode === "function"
      && typeof window.initLlinkWorkWorkspace === "function",
    { timeout: 45_000 }
  );
  await page.evaluate(() => window.selectAppMode("work"));
  await expect(page.locator(".work-brand-title")).toHaveText("Llink Work");
  await expect(page.locator("#work-list")).toBeVisible();
}

async function mockChatResponse(page, text) {
  await page.route(`${API}/api/chat`, async route => {
    if (route.request().method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: CORS_HEADERS });
    }
    return route.fulfill({
      status: 200,
      headers: {
        ...CORS_HEADERS,
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache"
      },
      body: text
    });
  });
}

async function askWorkToCreate(page, responseText) {
  await mockChatResponse(page, responseText);
  await page.locator("#work-prompt").fill("Prépare un document de test et retourne son contenu.");
  await page.locator("#work-send").click();
  const message = page.locator(".work-message.assistant").last();
  await expect(message.locator(".work-message-body")).toContainText("Contenu de test");
  await message.locator('[data-act="create-code"]').click();
  await expect(page.locator("#work-input-dialog")).toBeVisible();
}

test("Work crée, enregistre et télécharge un fichier Markdown", async ({ page }) => {
  const relevantErrors = [];
  page.on("pageerror", error => {
    if (/createFile is not defined|saveFile is not defined|setEditorValue is not defined/i.test(error.message)) {
      relevantErrors.push(error.message);
    }
  });

  await openWork(page);
  await askWorkToCreate(
    page,
    "Voici le document demandé.\n\n```markdown\n# Contenu de test\n\nCréé depuis une réponse de Llink Work.\n```"
  );

  await page.locator("#work-dialog-value").fill("rapport-ci.md");
  await page.locator("#work-input-dialog button[type='submit']").click();

  await expect(page.locator("#work-file-name")).toHaveText("rapport-ci.md");
  await expect(page.locator("#work-editor-host")).toContainText("Contenu de test");

  const downloadPromise = page.waitForEvent("download");
  await page.locator('[data-act="download"]').first().click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("rapport-ci.md");
  expect(relevantErrors).toEqual([]);
});

test("Work génère et télécharge un PDF depuis une réponse", async ({ page }) => {
  await openWork(page);
  await askWorkToCreate(
    page,
    "Voici le document demandé.\n\n```text\nContenu de test pour le PDF.\n```"
  );

  await page.route(`${API}/api/work/exports/pdf`, async route => {
    if (route.request().method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: CORS_HEADERS });
    }
    return route.fulfill({
      status: 200,
      headers: {
        ...CORS_HEADERS,
        "content-type": "application/pdf",
        "content-disposition": 'attachment; filename="rapport-ci.pdf"'
      },
      body: Buffer.from("%PDF-1.4\n% Llink Work CI smoke test\n%%EOF\n")
    });
  });

  await page.locator("#work-dialog-value").fill("rapport-ci.pdf");
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#work-input-dialog button[type='submit']").click();
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toBe("rapport-ci.pdf");
  await expect(page.locator("#work-file-name")).toHaveText("rapport-ci.pdf");
});

test("Work importe un fichier texte dans l'espace local", async ({ page }) => {
  await openWork(page);
  await page.locator("#work-upload-input").setInputFiles({
    name: "import-ci.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Fichier importé par le test d'interface.")
  });

  await expect(page.locator(".work-file-item").filter({ hasText: "import-ci.txt" })).toBeVisible();
  await expect(page.locator("#work-file-name")).toHaveText("import-ci.txt");
  await expect(page.locator("#work-editor-host")).toContainText("Fichier importé par le test");
});
