# Llink — CRYPT

Llink est l'application d'assistance IA de CRYPT.

## Structure du dépôt

- \`main.py\` : point d'entrée FastAPI stable (\`uvicorn main:app\`).
- \`llink_api/\` : backend modulaire, routes, fournisseurs, services, schémas et sécurité.
- \`app/index.html\` : application web canonique.
- \`capacitor/\` : projet Capacitor 8 et wrapper Android.
- \`docs/API_CONTRACTS.md\` : contrats HTTP utilisés par le frontend.
- \`docs/API_SECURITY.md\` : variables, quotas et règles d'accès.
- \`docs/DATA_LIFECYCLE.md\` : limites actuelles de conservation et de suppression.
- \`docs/PHASE_1.md\`, \`docs/PHASE_2.md\`, \`docs/PHASE_3.md\` : notes de réalisation et limites de livraison.

Le projet Capacitor utilise \`../app\` comme répertoire web.

## Build Android

Prérequis : Node.js 22+, Java 21 et Android SDK.

\`\`\`bash
cd capacitor
npm ci
npx cap sync android
cd android
./gradlew assembleDebug
\`\`\`

## Backend

\`\`\`bash
python -m pip install -r requirements.txt
uvicorn main:app --reload
\`\`\`

Tests :

\`\`\`bash
python -m pip install -r requirements-dev.txt
APP_ENV=test python -m pytest -q
\`\`\`

## Configuration de production

Configurer via les variables d'environnement Render : \`APP_ENV=production\`, \`FIREBASE_CONFIG\`, \`GEMINI_API_KEY\`, \`ZAI_API_KEY\`, \`MINIMAX_API_KEY\`, \`DEEPSEEK_API_KEY\`, \`HF_TOKEN\` et \`CORS_ORIGINS\`.

Les plafonds monétaires horaires facultatifs utilisent \`LLINK_HOURLY_CREDIT_LIMITS_USD\`. Lire [API_SECURITY.md](docs/API_SECURITY.md) et [PHASE_3.md](docs/PHASE_3.md) avant tout changement de production.

Ne jamais committer de fichier \`.env\`, de token, de compte de service ou de clé privée.
