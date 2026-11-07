(() => {
  "use strict";

  const MODEL_ID = "onnx-community/SmolLM-135M-Instruct-ONNX";
  const MODEL_NAME = "SmolLM-135M-Instruct · ONNX Q4";
  let modelPromise = null;
  let modelInstance = null;
  let ocrPromise = null;

  function isInstalledApp() {
    // La plateforme est identifiée une seule fois par platform-loader.js.
    return window.LLINK_PLATFORM?.isNative === true;
  }

  function hasGoogleAccount() {
    const user = window.auth && window.auth.currentUser;
    return !!(user && (
      (Array.isArray(user.providerData) && user.providerData.some(item => item && item.providerId === "google.com")) ||
      window.LLINK_GOOGLE_AUTH_UID === user.uid
    ));
  }

  function canUseOffline() {
    return isInstalledApp() && hasGoogleAccount();
  }

  function refreshEligibility() {
    window.isOfflineValid = canUseOffline();
    window.dispatchEvent(new CustomEvent("llink-offline-eligibility", {
      detail: {
        eligible: window.isOfflineValid,
        installed: isInstalledApp(),
        googleAccount: hasGoogleAccount()
      }
    }));
    if (typeof window.updateOfflineUI === "function") window.updateOfflineUI();
    return window.isOfflineValid;
  }

  function setStatus(loadingId, message) {
    const target = loadingId && document.getElementById(loadingId)?.querySelector(".msg-content");
    if (target) target.textContent = message;
  }

  function loadScript(src, id) {
    return new Promise((resolve, reject) => {
      const previous = document.getElementById(id);
      if (previous?.dataset.loaded === "true") return resolve();
      const script = previous || document.createElement("script");
      if (script.dataset.loading === "true") {
        script.addEventListener("load", resolve, { once: true });
        script.addEventListener("error", () => reject(new Error("Ressource locale absente : " + src)), { once: true });
        return;
      }
      script.id = id;
      script.src = src;
      script.dataset.loading = "true";
      script.onload = () => {
        script.dataset.loading = "false";
        script.dataset.loaded = "true";
        resolve();
      };
      script.onerror = () => {
        script.dataset.loading = "false";
        reject(new Error("Ressource locale absente : " + src));
      };
      if (!previous) document.head.appendChild(script);
    });
  }

  async function loadLocalModel(loadingId) {
    if (!canUseOffline()) throw new Error("Connecte-toi avec Google dans l'application Llink installée pour utiliser le mode hors ligne.");
    if (modelInstance) return modelInstance;
    if (!modelPromise) {
      modelPromise = (async () => {
        setStatus(loadingId, "Initialisation du moteur Transformers.js embarqué…");
        await loadScript("./vendor/transformers.min.js", "llink-transformers-runtime");
        const runtime = window.LlinkOfflineRuntime;
        if (!runtime || typeof runtime.pipeline !== "function") {
          throw new Error("Transformers.js n'est pas présent dans cette version de Llink.");
        }
        setStatus(loadingId, "Chargement du modèle SmolLM-135M-Instruct (ONNX Q4)…");
        modelInstance = await runtime.pipeline("text-generation", MODEL_ID, {
          device: "wasm",
          dtype: "q4",
          progress_callback: event => {
            if (event?.status === "progress" && Number.isFinite(event.progress)) {
              setStatus(loadingId, "Chargement du modèle local : " + Math.round(event.progress) + "%");
            }
          }
        });
        return modelInstance;
      })().catch(error => {
        modelPromise = null;
        modelInstance = null;
        throw error;
      });
    }
    return modelPromise;
  }

  function buildMessages(history, prompt) {
    const recent = (Array.isArray(history) ? history : [])
      .map(item => ({
        role: item.role === "bot" ? "assistant" : item.role,
        content: String(item.content ?? item.text ?? "").trim()
      }))
      .filter(item => ["system", "user", "assistant"].includes(item.role) && item.content)
      .slice(-8)
      .map(item => ({ role: item.role, content: item.content.slice(-1200) }));
    recent.push({ role: "user", content: String(prompt || "").slice(0, 3000) });
    return recent;
  }

  async function generate(prompt, loadingId, history) {
    if (!canUseOffline()) throw new Error("Mode hors ligne réservé à l'APK ou au logiciel Llink avec un compte Google connecté.");
    const model = await loadLocalModel(loadingId);
    setStatus(loadingId, "SmolLM réfléchit localement…");
    const result = await model(buildMessages(history, prompt), {
      max_new_tokens: 160,
      do_sample: true,
      temperature: 0.65,
      repetition_penalty: 1.08
    });
    const generated = result?.[0]?.generated_text;
    if (Array.isArray(generated)) {
      const last = generated[generated.length - 1];
      return String(last?.content ?? last?.text ?? "").trim();
    }
    return String(generated || "").trim();
  }

  async function runOCR(file) {
    if (!canUseOffline()) throw new Error("OCR local réservé à l'application Llink installée avec un compte Google.");
    if (!ocrPromise) {
      ocrPromise = loadScript("./vendor/tesseract.min.js", "llink-tesseract-runtime").then(() => {
        if (!window.Tesseract || typeof window.Tesseract.recognize !== "function") {
          throw new Error("Tesseract.js n'est pas présent dans cette version.");
        }
        return window.Tesseract;
      }).catch(error => {
        ocrPromise = null;
        throw error;
      });
    }
    const Tesseract = await ocrPromise;
    const result = await Tesseract.recognize(file, "fra+eng", {
      workerPath: new URL("./vendor/tesseract-worker.min.js", document.baseURI).href,
      corePath: new URL("./vendor/tesseract-core/", document.baseURI).href,
      langPath: new URL("./tessdata/", document.baseURI).href,
      gzip: false
    });
    return {
      text: String(result?.data?.text || ""),
      confidence: Number(result?.data?.confidence || 0)
    };
  }

  function syncNetworkUI() {
    const dot = document.getElementById("network-status");
    const model = document.getElementById("model-selector");
    const mic = document.getElementById("mic-btn");
    if (dot) dot.className = window.isOnline
      ? "w-[0.875rem] h-[0.875rem] rounded-full bg-green-500 shadow-[0_0_8px_#34A853]"
      : "w-[0.875rem] h-[0.875rem] rounded-full bg-red-500";
    if (model) { model.disabled = !window.isOnline; model.style.opacity = window.isOnline ? 1 : 0.5; }
    if (mic) { mic.disabled = !window.isOnline; mic.style.opacity = window.isOnline ? 1 : 0.5; }
    if (typeof window.updateOfflineUI === "function") window.updateOfflineUI();
  }

  window.isLlinkInstalledApp = isInstalledApp;
  window.hasLlinkGoogleAccount = hasGoogleAccount;
  window.canUseLlinkOffline = canUseOffline;
  window.refreshOfflineEligibility = refreshEligibility;
  window.generateOfflineText = generate;
  window.runOfflineOCR = runOCR;
  window.LlinkOffline = {
    model: MODEL_NAME,
    isInstalledApp,
    hasGoogleAccount,
    canUseOffline,
    refreshEligibility,
    unload: () => {
      modelInstance = null;
      modelPromise = null;
    }
  };

  window.addEventListener("llink-auth-state-changed", refreshEligibility);
  window.addEventListener("online", () => {
    window.isOnline = true;
    syncNetworkUI();
  });
  window.addEventListener("offline", () => {
    window.isOnline = false;
    refreshEligibility();
    syncNetworkUI();
  });
  window.addEventListener("DOMContentLoaded", () => {
    refreshEligibility();
    syncNetworkUI();
  });
  refreshEligibility();
})();
