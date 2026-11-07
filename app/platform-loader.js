(function () {
  "use strict";

  const capacitor = window.Capacitor;
  let isCapacitor = false;
  try {
    isCapacitor = !!(
      (capacitor && typeof capacitor.isNativePlatform === "function" && capacitor.isNativePlatform()) ||
      location.protocol === "capacitor:" ||
      location.protocol === "ionic:" ||
      (location.hostname === "localhost" && /;\\s*wv\\)/i.test(navigator.userAgent))
    );
  } catch (_) {
    isCapacitor = false;
  }

  const isTauri = !!(window.__TAURI_INTERNALS__ || window.__TAURI__);
  const isNative = isTauri || isCapacitor;
  window.LLINK_PLATFORM = Object.freeze({
    isNative,
    isTauri,
    isCapacitor,
    kind: isTauri ? "tauri" : (isCapacitor ? "capacitor" : "web")
  });

  function writeScript(src) {
    document.write('<script src="' + src + '"><\\/script>');
  }

  function writeLink(href) {
    document.write('<link rel="stylesheet" href="' + href + '">');
  }

  if (isNative) {
    // APK et logiciel Tauri : toutes les dépendances viennent du paquet installé.
    writeLink("./vendor/tailwind.min.css");
    writeScript("./vendor/lucide.min.js");
    writeScript("./vendor/dexie.min.js");
    writeScript("./vendor/marked.umd.js");
    writeScript("./vendor/purify.min.js");
    writeScript("./vendor/firebase-runtime.js");
    writeScript("./offline-engine.js");
    return;
  }

  // Site Web : aucun modèle ni moteur local n'est chargé.
  // Les bibliothèques UI et Firebase restent accessibles en ligne via leurs CDNs.
  window.canUseLlinkOffline = function () { return false; };
  window.isLlinkInstalledApp = function () { return false; };
  window.hasLlinkGoogleAccount = function () { return false; };
  window.isOfflineValid = false;

  window.tailwind = window.tailwind || {};
  window.tailwind.config = {
    darkMode: "class",
    theme: {
      extend: {
        colors: {
          campagne: { light: "#FDFBF7", dark: "#131314" },
          surface: { light: "#EFECE6", dark: "#1E1F20" },
          userBg: { light: "#E3DFD5", dark: "#2B2C2F" }
        },
        animation: {
          "pulse-fast": "pulse 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite"
        }
      }
    }
  };

  writeScript("https://cdn.tailwindcss.com");
  writeScript("https://unpkg.com/lucide@1.70.0/dist/umd/lucide.js");
  writeScript("https://unpkg.com/dexie@4.4.7/dist/dexie.js");
  writeScript("https://cdn.jsdelivr.net/npm/marked@18.1.2/lib/marked.umd.js");
  writeScript("https://cdn.jsdelivr.net/npm/dompurify@3.4.17/dist/purify.min.js");

  window.addEventListener("online", function () {
    window.isOnline = true;
    const dot = document.getElementById("network-status");
    if (dot) dot.className = "w-[0.875rem] h-[0.875rem] rounded-full bg-green-500 shadow-[0_0_8px_#34A853]";
  });
  window.addEventListener("offline", function () {
    window.isOnline = false;
    const dot = document.getElementById("network-status");
    if (dot) dot.className = "w-[0.875rem] h-[0.875rem] rounded-full bg-red-500";
  });
})();