const { test, expect } = require("@playwright/test");

const API = "https://llink-usz9.onrender.com";
const CORS_HEADERS = {
  "access-control-allow-origin": "http://127.0.0.1:4173",
  "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  "access-control-allow-headers": "Authorization, Content-Type",
  "access-control-max-age": "600",
  "vary": "Origin"
};

async function openWork(page, savedEffort = null) {
  await page.addInitScript(effort => {
    if (effort) localStorage.setItem("llink_effort", effort);
    else localStorage.removeItem("llink_effort");
  }, savedEffort);
  await page.route(API + "/api/work/tools", async route => {
    if (route.request().method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: CORS_HEADERS });
    }
    return route.fulfill({
      status: 200,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
      body: JSON.stringify({
        tools: {
          web_search: false, python: false, exports: true,
          document_create: true, file_attachments: true
        }
      })
    });
  });

  await page.route(API + "/api/work/agent/status", async route => {
    if (route.request().method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: CORS_HEADERS });
    }
    return route.fulfill({
      status: 200,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
      body: JSON.stringify({
        agent: "llink-work",
        version: "native-functions-v1",
        protocol: "native_function_calling",
        tools: ["update_plan", "document_begin", "document_add_blocks", "document_finalize", "artifact_verify"],
        limits: { model_turns: 24, tool_calls: 32, seconds: 240 }
      })
    });
  });
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
  await expect(page.locator("#work-tool-status")).toContainText("Agent natif native-functions-v1");
  await expect(page.locator("#work-tool-status")).toContainText("Réflexion extra");
}

async function mockAgentEvents(page, events, verifyRequest = null) {
  await page.route(API + "/api/work/agent", async route => {
    if (route.request().method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: CORS_HEADERS });
    }
    if (verifyRequest) verifyRequest(route.request().postDataJSON());
    const body = events.map(event => "data: " + JSON.stringify(event) + "\n\n").join("");
    return route.fulfill({
      status: 200,
      headers: {
        ...CORS_HEADERS,
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache"
      },
      body
    });
  });
}

function plan(summary, steps) {
  return {
    type: "plan",
    summary,
    steps: steps.map(label => ({ label, status: "done" })),
    decisions: ["Les actions sont exécutées par des outils natifs côté serveur."],
    acceptance_criteria: ["Les actions sont confirmées par leurs retours d'outils."],
    limitations: []
  };
}

function toolEvent(type, tool, label, status, detail) {
  return { type, tool, label, status, detail };
}

function finalEvent(answer, artifact = null, reasoningOverride = null) {
  const reasoning = reasoningOverride || {
    summary: "La tâche a été exécutée et le résultat contrôlé.",
    steps: [
      { label: "Analyser la demande", status: "done" },
      { label: "Exécuter l'outil", status: "done" },
      { label: "Vérifier le résultat", status: "done" }
    ],
    decisions: ["Le fichier est remis uniquement après vérification."],
    acceptance_criteria: ["La vérification indépendante est réussie."],
    limitations: [],
    events: [],
    status: "completed",
    tool_calls: artifact ? 3 : 0
  };
  return { type: "final", answer, reasoning, artifacts: artifact ? [artifact] : [] };
}

test("Work crée et télécharge un fichier Markdown éditable par l'agent serveur", async ({ page }) => {
  await openWork(page);
  const text = "# Rapport CI\n\nContenu créé par le nouvel agent.";
  const artifact = {
    artifact_id: "artifact-md",
    filename: "rapport-agent-ci.md",
    mime_type: "text/markdown",
    size_bytes: Buffer.byteLength(text),
    content_base64: Buffer.from(text).toString("base64"),
    verification: { passed: true, utf8_valid: true }
  };
  await mockAgentEvents(page, [
    plan("Je vais créer puis vérifier le fichier demandé.", ["Comprendre la demande", "Créer le fichier", "Contrôler son contenu"]),
    toolEvent("tool_start", "create_text_file", "Création d'un fichier", "in_progress"),
    toolEvent("tool_result", "create_text_file", "Création d'un fichier", "done", "rapport-agent-ci.md · vérifié"),
    finalEvent("Le fichier Markdown a été créé et vérifié.", artifact)
  ], payload => {
    expect(payload.mode).toBe("work");
    expect(payload.effort).toBe("extra");
    expect(payload.message).toContain("fichier Markdown");
  });

  await page.locator("#work-prompt").fill("Crée un fichier Markdown nommé rapport-agent-ci.md.");
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#work-send").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("rapport-agent-ci.md");
  await expect(page.locator("#work-file-name")).toHaveText("rapport-agent-ci.md");

  const saved = await page.evaluate(async () => {
    const files = await db.workFiles.where("ownerUid").equals("anonymous").toArray();
    const file = files.find(item => item.name === "rapport-agent-ci.md");
    return file ? { isBinary: file.isBinary, content: file.content } : null;
  });
  expect(saved).toEqual({ isBinary: false, content: text });
});

test("Work livre un PDF vérifié comme fichier binaire", async ({ page }) => {
  await openWork(page);
  const pdf = Buffer.from("%PDF-1.4\n% Llink agent test\n1 0 obj <<>> endobj\n%%EOF\n");
  const artifact = {
    artifact_id: "artifact-pdf",
    filename: "analyse-agent-ci.pdf",
    mime_type: "application/pdf",
    size_bytes: pdf.length,
    content_base64: pdf.toString("base64"),
    verification: { passed: true, bytes_read_back: pdf.length, pages: 1 }
  };
  await mockAgentEvents(page, [
    plan("Je prépare l'export et contrôle que le PDF est lisible.", ["Préparer le contenu", "Générer le PDF", "Vérifier le fichier"]),
    toolEvent("tool_start", "export_file", "Export PDF", "in_progress"),
    toolEvent("tool_result", "export_file", "Export PDF", "done", "1 page · vérification réussie"),
    finalEvent("Le PDF a été généré et vérifié.", artifact)
  ]);

  await page.locator("#work-prompt").fill("Crée un PDF de synthèse.");
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#work-send").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("analyse-agent-ci.pdf");
  await expect(page.locator("#work-file-name")).toHaveText("analyse-agent-ci.pdf");

  const saved = await page.evaluate(async () => {
    const files = await db.workFiles.where("ownerUid").equals("anonymous").toArray();
    const file = files.find(item => item.name === "analyse-agent-ci.pdf");
    return file ? { isBinary: file.isBinary, size: file.blob?.size ?? 0 } : null;
  });
  expect(saved?.isBinary).toBe(true);
  expect(saved.size).toBeGreaterThan(0);
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
  const importedText = await page.evaluate(async () => {
    const files = await db.workFiles.where("ownerUid").equals("anonymous").toArray();
    return files.find(file => file.name === "import-ci.txt")?.content ?? null;
  });
  expect(importedText).toContain("Fichier importé par le test");
});

test("Work utilise le journal d'outils natifs pour créer et vérifier un DOCX", async ({ page }) => {
  await openWork(page);
  const docx = Buffer.from("PK\u0003\u0004Llink Work DOCX native agent test");
  const artifact = {
    artifact_id: "artifact-docx",
    filename: "rapport-docx-agent.docx",
    mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    size_bytes: docx.length,
    content_base64: docx.toString("base64"),
    verification: { passed: true, docx_reopened: true, paragraphs_checked: 2, tables_found: 1 }
  };
  await mockAgentEvents(page, [
    plan("Je rédige le document par sections, puis je vérifie le fichier Word final.", ["Établir le plan", "Rédiger les sections", "Générer le DOCX", "Vérifier le DOCX"]),
    toolEvent("tool_start", "document_begin", "Initialisation du document", "in_progress"),
    toolEvent("tool_result", "document_begin", "Initialisation du document", "done", "Brouillon initialisé"),
    toolEvent("tool_start", "document_add_blocks", "Rédaction d'une section", "in_progress"),
    toolEvent("tool_result", "document_add_blocks", "Rédaction d'une section", "done", "6 blocs ajoutés"),
    toolEvent("tool_start", "document_finalize", "Génération et vérification du fichier", "in_progress"),
    toolEvent("tool_result", "document_finalize", "Génération et vérification du fichier", "done", "DOCX réouvert · tableaux et paragraphes vérifiés"),
    toolEvent("tool_start", "artifact_verify", "Vérification indépendante du fichier", "in_progress"),
    toolEvent("tool_result", "artifact_verify", "Vérification indépendante du fichier", "done", "Toutes les vérifications ont réussi"),
    finalEvent("Le document Word est prêt. Il a été généré en plusieurs sections, rouvert et vérifié.", artifact)
  ]);

  await page.locator("#work-prompt").fill("Crée un document Word professionnel et vérifie-le.");
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#work-send").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("rapport-docx-agent.docx");
  await expect(page.locator("#work-file-name")).toHaveText("rapport-docx-agent.docx");
  await expect(page.locator(".work-reasoning")).toContainText("Vérification indépendante du fichier");
  await expect(page.locator(".work-reasoning")).toContainText("vérifiés");
  await expect(page.locator(".work-message-body").last()).toContainText("généré en plusieurs sections");

  const saved = await page.evaluate(async () => {
    const files = await db.workFiles.where("ownerUid").equals("anonymous").toArray();
    const file = files.find(item => item.name === "rapport-docx-agent.docx");
    return file ? { isBinary: file.isBinary, size: file.blob?.size ?? 0 } : null;
  });
  expect(saved?.isBinary).toBe(true);
  expect(saved.size).toBeGreaterThan(0);
});

test("Work affiche et conserve le plan, les décisions et les actions réelles", async ({ page }) => {
  await openWork(page);
  const summary = "Je vérifie la demande, sélectionne les outils utiles et contrôle le résultat.";
  const reasoning = {
    summary,
    steps: [
      { label: "Analyser la demande", status: "done" },
      { label: "Vérifier les informations", status: "done" },
      { label: "Présenter le résultat", status: "done" }
    ],
    decisions: ["Je sépare les faits vérifiés des hypothèses."],
    acceptance_criteria: ["Les actions sont confirmées par leurs retours d'outils."],
    limitations: ["Aucune source externe n'a été consultée pour ce test."],
    events: [
      { label: "Recherche sur le Web", status: "done", detail: "3 résultats vérifiés.", tool: "web_search" }
    ],
    status: "completed",
    tool_calls: 1
  };
  await mockAgentEvents(page, [
    plan(summary, ["Analyser la demande", "Vérifier les informations", "Présenter le résultat"]),
    { type: "model_start", detail: "Le modèle analyse le contexte et choisit la prochaine action." },
    { type: "model_done", detail: "Analyse terminée ; 1 action sélectionnée.", tool_calls: 1 },
    toolEvent("tool_start", "web_search", "Recherche sur le Web", "in_progress"),
    toolEvent("tool_result", "web_search", "Recherche sur le Web", "done", "3 résultats vérifiés."),
    finalEvent("Voici le résultat de démonstration.", null, reasoning)
  ]);

  await page.locator("#work-prompt").fill("Explique ta démarche et vérifie les faits.");
  await page.locator("#work-send").click();
  const message = page.locator(".work-message.assistant").last();
  const panel = message.locator(".work-reasoning");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("Démarche de Llink");
  await expect(panel).toContainText("Analyser la demande");
  await expect(panel).toContainText("Terminé");
  await expect(panel).toContainText("Je sépare les faits vérifiés");
  await expect(panel).toContainText("Analyse et planification");
  await expect(panel).toContainText("Analyse terminée ; 1 action sélectionnée.");
  await expect(panel).toContainText("Recherche sur le Web");
  await expect(panel).toContainText("Critères de réussite");
  await expect(panel).toContainText("Les actions sont confirmées par leurs retours d'outils.");
  await expect(message.locator(".work-message-body")).toContainText("résultat de démonstration");

  const saved = await page.evaluate(async () => {
    const messages = await db.msgs.toArray();
    return messages.find(item => item.role === "bot" && item.reasoning)?.reasoning ?? null;
  });
  expect(saved?.summary).toBe(summary);
  expect(saved?.events).toHaveLength(2);
  expect(saved?.events.some(event => event.tool === "model_reasoning")).toBe(true);
  expect(saved?.events.some(event => event.tool === "web_search")).toBe(true);
});


test("Work refuse d'exécuter une tâche si Render utilise encore l'ancien protocole", async ({ page }) => {
  await openWork(page);
  let agentCalls = 0;
  await page.route(API + "/api/work/agent/status", async route => {
    return route.fulfill({
      status: 200,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
      body: JSON.stringify({
        agent: "llink-work",
        version: "legacy",
        protocol: "text_tool_tags",
        tools: ["create_document"]
      })
    });
  });
  await page.route(API + "/api/work/agent", async route => {
    agentCalls += 1;
    return route.fulfill({ status: 500, body: "Should not be called" });
  });

  await page.locator("#work-prompt").fill("Crée un document Word.");
  await page.locator("#work-send").click();

  await expect(page.locator(".work-message.assistant").last()).toContainText("protocole ancien");
  await expect(page.locator(".work-message.assistant").last().locator(".work-reasoning")).toContainText("Interrompue");
  await expect(page.locator(".work-message.assistant").last().locator(".work-reasoning")).toContainText("agent_preflight");
  expect(agentCalls).toBe(0);
});


test("Work respecte un réglage explicite de réflexion Normal", async ({ page }) => {
  await openWork(page, "normal");
  await mockAgentEvents(page, [
    plan("Je réponds en respectant le niveau de réflexion choisi.", ["Analyser la demande", "Répondre"])
      ,
    finalEvent("Le réglage Normal a été respecté.")
  ], payload => {
    expect(payload.effort).toBe("normal");
  });
  await expect(page.locator("#work-tool-status")).toContainText("Réflexion normal");
  await page.locator("#work-prompt").fill("Réponds brièvement à cette question.");
  await page.locator("#work-send").click();
  await expect(page.locator(".work-message-body").last()).toContainText("réglage Normal");
});
