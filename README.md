# Llink — CRYPT

Llink is the CRYPT AI application.

## Project layout

- `main.py`: FastAPI backend entry point.
- `requirements.txt`: Python backend dependencies.
- `app/index.html`: canonical web application.
- `capacitor/`: Capacitor 8 project and Android wrapper.

The Capacitor project uses `../app` as its web directory. There is no separate `www/index.html` copy.

## Android build

Requirements: Node.js 22+, Java 21, Android SDK.

From the repository root:

```bash
cd capacitor
npm ci

# First-time setup only:
npx cap add android

# Copy app/index.html and synchronize native dependencies:
npx cap sync android

# Build a local debug APK:
cd android
./gradlew assembleDebug
```

The GitHub Actions workflow `.github/workflows/android-build.yml` performs the same Android debug build and publishes the APK as a workflow artifact.

## Backend

Install the Python dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the API locally:

```bash
uvicorn main:app --reload
```

Configure backend credentials through environment variables (for example on Render). Never commit real `.env` files, API tokens, service-account JSON files, or private keys.
