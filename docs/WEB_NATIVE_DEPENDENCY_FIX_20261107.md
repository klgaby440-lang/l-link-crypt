# Correction — sélection des dépendances Web et natives

## Cause

L'index partagé chargeait en permanence `./vendor/dexie.min.js`, `./vendor/firebase-runtime.js` et `./offline-engine.js`. Ces fichiers sont générés pendant les builds Android/Windows et sont ignorés par Git ; ils ne sont donc pas présents sur le déploiement Web. Le code Work dépendait aussi d'une constante lexicale `SERVER_URL` plutôt que d'un contrat global explicite.

## Correction

- `platform-loader.js` identifie Tauri/Capacitor dès le début du chargement.
- En Web : charge Tailwind, Lucide, Dexie, Marked et DOMPurify depuis les CDN ; Firebase est importé depuis le SDK Web officiel. Le moteur offline et le modèle ne sont jamais chargés, et `canUseLlinkOffline()` retourne toujours `false`.
- En APK/Tauri : charge uniquement les bibliothèques et le SDK Firebase présents dans `vendor/`, puis `offline-engine.js`. Aucun CDN n'est requis pour les dépendances d'interface ni le modèle.
- `workspace.js` utilise maintenant `window.LLINK_SERVER_URL`, avec une version d'URL mise à jour pour invalider le cache.
- Les deux environnements conservent le même `index.html` et la même interface : aucune copie complète Web/native à maintenir.

## Vérifications ajoutées

Playwright teste explicitement que le Web n'effectue aucune requête vers `offline-engine.js` ou les scripts `vendor/`, que Dexie et Firebase s'initialisent, que l'URL du backend est visible par Work et que l'accès hors ligne reste refusé dans le navigateur.
Les tests Capacitor/Tauri vérifient toujours l'exigence de connexion Google.

## À valider après déploiement

1. Le site Web déployé charge les CDN et Firebase, puis Work s'ouvre sans les trois erreurs de console.
2. Le nouvel APK et le nouveau logiciel Tauri chargent leurs dépendances locales.
3. Le mode avion dans l'application native conserve le Chat SmolLM local.
