# Llink — Audit technique du dépôt et démarrage de la phase 1

**Date de l'audit :** 31 octobre 2026  
**Dépôt :** [klgaby440-lang/l-link-crypt](https://github.com/klgaby440-lang/l-link-crypt)  
**Branche examinée :** `main`  
**Commit de référence :** `0225b38c40aaad0d7d3baf5d539f21b1b098740c`  
**Branche de travail créée :** `phase-1/backend-core-foundation`

> Cet audit est une lecture du dépôt. Aucun fichier de production, variable Render, déploiement, base Firebase ou branche `main` n'a été modifié.

## 1. Périmètre et constat de version

Le dépôt contient actuellement un petit ensemble de fichiers : `main.py`, `requirements.txt`, `app/index.html`, `script.js`, `www/index.html`, `package.json`, `package-lock.json`, `capacitor.config.json`, `manifest.json` et un workflow GitHub Actions Android.

Les fichiers précédemment transmis dans la conversation — `server.py` et `Llink Kl.html` — ne figurent pas dans l'arborescence actuelle. Le fichier `main.py` reprend néanmoins la même architecture générale que le `server.py` précédemment examiné. **Pour la refactorisation, la branche GitHub est la source de vérité.** Les copies antérieures ne doivent pas être utilisées comme base de remplacement.

Le dernier commit de `main` renomme `index.html` en `app/index.html`. Le dépôt ne contient pas de configuration Vercel, Render ou Tauri permettant de confirmer à lui seul quels répertoires sont effectivement déployés.

## 2. Architecture réellement présente

### Backend

- Un seul fichier FastAPI : `main.py` (488 lignes).
- Firebase Admin / Firestore initialisé depuis `FIREBASE_CONFIG`.
- Identifiants de fournisseurs attendus depuis les variables d'environnement : `HF_TOKEN`, `GEMINI_API_KEY`, `RESEND_API_KEY`.
- Gemini via le paquet Python `google-generativeai`.
- Hugging Face via `https://router.huggingface.co/v1/chat/completions`.
- Endpoints : `/`, `/api/user/status`, `/api/verify-payment`, `/api/chat`, `/api/ocr`, `/api/audio`, `/api/history/sync`, `/api/history`.
- Le routeur de modèles est codé par conditions sur des chaînes de caractères dans `main.py`. Les choix réels sont Gemini 2.5 Flash, DeepSeek V3, Llama 3 8B et Mistral 7B.
- Aucun service backend visible pour Work, Live, la mémoire structurée, les crédits horaires, les Link's Experts ou la version B2B.

### Frontends

Il existe trois implémentations/artefacts à réconcilier :

1. **`app/index.html`** — HTML de 632 lignes avec la logique JavaScript intégrée. C'est la version du dépôt qui correspond le mieux au contrat de streaming actuel du backend.
2. **`www/index.html`** — autre HTML autonome, plus ancien et différent. `capacitor.config.json` définit `webDir: "www"`, donc ce répertoire est la source de l'application Capacitor configurée.
3. **`script.js`** — contient une troisième copie d'une grande partie de la logique de l'interface. `app/index.html` ne référence pas ce fichier par une balise `script src` ; il semble donc redondant ou destiné à une autre variante.

Le frontend réellement publié par Vercel ne peut pas être déterminé à partir du dépôt seul ; il faut vérifier le paramètre Root Directory dans Vercel.

## 3. Écarts et risques identifiés

### Critiques — à traiter avant une mise en production

**Paiement non vérifié.** Dans `main.py`, `/api/verify-payment` active un abonnement de 30 jours dès que l'identifiant de transaction contient au moins six caractères ; un identifiant spécial active dix ans. Aucun contrôle réel CinetPay/Think, aucune unicité de transaction et aucune validation de montant/plan ne sont effectués. Le modèle Pydantic ne déclare que `transactionId`, donc les détails de plan/moyen/fournisseur envoyés par certains clients ne sont pas utilisés.

**Authentification permissive.** `verify_token()` transforme l'absence de token, un token invalide et l'indisponibilité de Firestore en utilisateur `anonymous`. L'endpoint chat accepte cet utilisateur. Les routes OCR et audio n'imposent pas d'authentification dans leur définition actuelle. Il faudra distinguer précisément accès gratuit anonyme, utilisateur authentifié et routes protégées.

**Collecte globale des conversations.** Chaque échange peut être écrit dans `global_datasets` avec prompt, réponse, préférences, identifiant utilisateur, source, mode et date. Un export global est envoyé par e-mail tous les 50 échanges. Une commande secrète dans le texte de chat déclenche également cet export. Cette commande n'est pas un mécanisme d'administration sécurisé, puisque la route chat accepte les anonymes. La collecte doit être isolée de l'historique privé et encadrée par les règles de consentement et de confidentialité décidées pour Llink.

**Crédits et quotas absents.** Le backend ne possède pas de registre transactionnel de crédits, d'allocation horaire fixe, de quotas par tâche/modèle, de réservation avant tâche, ni de journal de consommation. Le statut utilisateur se limite essentiellement à `isPro` et `expirationDate`.

### Écarts de contrat frontend/backend

**Variante `www/index.html` incompatible avec le chat actuel.** Son payload `/api/chat` n'envoie pas le champ obligatoire `model` et le client attend une réponse JSON (`response.json())), tandis que le backend retourne un flux texte `StreamingResponse`. Dans cet état, cette variante ne correspond pas au contrat API actuel et risque d'obtenir une erreur 422 ou un échec de parsing.

**Traduction incomplètement câblée.** L'interface contient des sélecteurs de langue, mais le payload de `app/index.html` transmet `mode`, `model`, `preferences` et un champ `source` utilisé comme identifiant d'origine de l'application. Il ne transmet pas de paire source/cible explicite au backend. Dans `www/index.html`, les champs `source` et `target` ne correspondent pas au schéma backend : `source` y est utilisé comme origine de la requête et `target` n'est pas déclaré.

**Restauration de l'historique incomplète.** `restoreHistory()` récupère les discussions distantes, mais ne les réinjecte pas visiblement dans Dexie. Il n'existe pas non plus d'endpoint de suppression distante. Les IDs de conversation proviennent d'auto-incréments locaux, ce qui expose à des collisions lors d'une synchronisation multi-appareils.

### Offline et multimodal

- `app/index.html` interdit les téléchargements distants de modèles et cherche `SmolLM-135M-Instruct` dans `/models/`; aucun dossier `models` n'est présent dans l'arborescence versionnée.
- `www/index.html` autorise les téléchargements distants et charge `Xenova/Qwen1.5-0.5B-Chat`, ce qui ne garantit pas une première utilisation hors ligne.
- Les deux frontends n'utilisent donc pas la même configuration offline.
- OCR local Tesseract est présent ; la prise en charge STT/TTS locale, l'analyse des capacités matérielles et la sélection dynamique de modèles ne sont pas présentes dans les fichiers audités.
- Aucun transport/API de conversation Live audio-vidéo en temps réel n'est présent dans le backend.

### Déploiement et qualité du dépôt

- `.github/workflows/android-build.yml` référence `intranet-server`, `classnet-p`, `classnet-app` et `installer`, absents de l'arborescence Llink. Le job Android installe aussi Capacitor 6 dans `classnet-app`, alors que le `package.json` racine déclare Capacitor 8.3.4. Ce workflow n'est pas un workflow de build Llink cohérent.
- `package.json` ne contient pas de vraie commande de build et son script `test` retourne volontairement une erreur.
- Aucun dossier de tests n'est présent dans l'arborescence.
- `README.md` ne documente pratiquement rien ; pas de `render.yaml`, `vercel.json`, `Dockerfile` ni configuration Tauri visible.
- `.gitignore` ne couvre pas clairement `.env`, `.venv`, `__pycache__` et autres fichiers temporaires courants.
- `manifest.json` et l'icône référencée ne sont pas dans `www/`, alors que `www/index.html` référence le manifest relatif.

## 4. Dépendances et sécurité des secrets

Le backend utilise `google-generativeai`. Google indique que cet ancien SDK Python n'est plus activement maintenu depuis le 30 novembre 2025 et recommande `google-genai`. La migration doit être incluse dans la phase 1, en particulier pour préparer les futures fonctions Live.

Le scan du contenu actuel des fichiers racine examinés n'a trouvé aucun token Hugging Face, clé Gemini serveur, clé Resend ou clé privée de compte de service. La configuration Firebase contenant `apiKey` dans le frontend est une configuration client publique, pas une clé de compte de service ; elle doit néanmoins être restreinte et protégée par les règles Firebase appropriées. Cet audit du contenu actuel ne constitue pas une analyse exhaustive de tout l'historique Git.

## 5. Architecture cible proposée pour la phase 1

Ne pas nommer le package backend `app`, car `app/` est déjà le répertoire du frontend. Proposition :

```text
main.py                       # shim conservant uvicorn main:app
llink_api/
  main.py
  core/
    config.py
    firebase.py
    auth.py
    logging.py
  api/v1/
    chat.py
    users.py
    history.py
    media.py
    billing.py
    usage.py
  schemas/
    chat.py
    users.py
    payments.py
    usage.py
  providers/
    base.py
    gemini.py
    huggingface.py
  services/
    ai_router.py
    model_registry.py
    context_builder.py
    usage_ledger.py
  repositories/
    firestore.py
tests/
  unit/
  contract/
config/
  models.yaml
```

Le fichier `main.py` existant restera un point d'entrée compatible afin de ne pas casser la commande Render `uvicorn main:app` si c'est celle effectivement configurée. Les routes existantes seront préservées pendant la migration ; les changements de comportement seront testés séparément.

## 6. Ordre recommandé de la phase 1

1. Établir des tests de contrat pour les routes actuelles et capturer les formats réellement attendus par `app/index.html`.
2. Créer la structure `llink_api/` sans toucher à `app/` ni à `www/`.
3. Extraire Firebase, authentification, schémas et dépôts Firestore.
4. Migrer Gemini vers `google-genai`.
5. Créer une interface fournisseur commune et le registre de modèles/alias.
6. Extraire le chat/streaming, l'historique et les routes media.
7. Préparer les interfaces de mémoire, de crédits horaires et d'orchestration sans activer de logique de facturation non testée.
8. Ajouter tests unitaires et de contrat, puis vérifier la compatibilité frontend.
9. Ne déployer qu'après validation manuelle et après un test sur une copie de service Render.

## 7. Sécurité du travail GitHub

La branche de travail `phase-1/backend-core-foundation` a été créée depuis le commit examiné. La branche `main` était déclarée non protégée. Tous les changements de phase 1 doivent rester sur cette branche et ne seront pas fusionnés automatiquement dans `main`. Aucun déploiement Render ou Vercel n'a été déclenché par cet audit.

## 8. Informations externes vérifiées

- [Google GenAI SDK — bibliothèques officielles et statut des anciens SDK](https://ai.google.dev/gemini-api/docs/libraries)
- [Google GenAI SDK — guide de migration](https://ai.google.dev/gemini-api/docs/migrate)
- [Gemini API — modèles disponibles](https://ai.google.dev/gemini-api/docs/models)
- [Hugging Face — fournisseurs d'inférence et modèles supportés](https://huggingface.co/inference/models)

---

**Conclusion :** le backend est suffisamment petit pour être refactorisé progressivement, mais les contrats frontend sont actuellement divergents. La première priorité est de préserver la version `app/index.html` et son streaming, de rendre le backend modulaire et de migrer le SDK Gemini. Les crédits, la mémoire, Think, Work et Live seront ensuite branchés sur des services clairement séparés ; ils ne doivent pas être simulés dans le code actuel.
