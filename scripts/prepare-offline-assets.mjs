import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { Readable, Transform } from "node:stream";
import { createWriteStream } from "node:fs";
import { pipeline as streamPipeline } from "node:stream/promises";
import { createRequire } from "node:module";

const root = process.cwd();
const require = createRequire(path.join(root, "build-tools", "package.json"));
const esbuild = require("esbuild");
const skipModel = process.argv.includes("--skip-model");
const modelId = "onnx-community/SmolLM-135M-Instruct-ONNX";
const revision = "7e78273381b84cc2dae12daceb53552c8b115eef";
const modelDirectory = path.join(root, "app", "models", ...modelId.split("/"));
const vendorDirectory = path.join(root, "app", "vendor");
const mkdir = directory => fs.mkdir(directory, { recursive: true });

async function download(url, destination, minimumSize = 1) {
  await mkdir(path.dirname(destination));
  const existing = await fs.readFile(destination).catch(() => null);
  if (existing && existing.length >= minimumSize) return existing;
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok || !response.body) throw new Error("Téléchargement HTTP " + response.status + " : " + url);
  const hash = createHash("sha256");
  let size = 0;
  const meter = new Transform({
    transform(chunk, encoding, callback) {
      size += chunk.length;
      hash.update(chunk);
      callback(null, chunk);
    }
  });
  await streamPipeline(Readable.fromWeb(response.body), meter, createWriteStream(destination));
  if (size < minimumSize) throw new Error("Fichier trop petit après téléchargement : " + destination);
  const digest = hash.digest("hex");
  console.log("OK", path.relative(root, destination), size, "octets SHA256", digest);
  return fs.readFile(destination);
}

function packageRoot(packageName) {
  let directory = path.dirname(require.resolve(packageName));
  while (directory !== path.dirname(directory)) {
    if (fsSyncExists(path.join(directory, "package.json"))) return directory;
    directory = path.dirname(directory);
  }
  throw new Error("Racine npm introuvable : " + packageName);
}

function fsSyncExists(file) {
  try { require("node:fs").accessSync(file); return true; } catch (_) { return false; }
}

let modelManifest = { model: modelId, revision, format: "onnx", quantization: "q4", bundled: !skipModel };
if (!skipModel) {
  await mkdir(modelDirectory);
  for (const file of [
    "config.json", "generation_config.json", "merges.txt", "quantize_config.json",
    "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.json"
  ]) {
    await download(
      "https://huggingface.co/" + modelId + "/resolve/" + revision + "/" + file,
      path.join(modelDirectory, file)
    );
  }
  const model = await download(
    "https://huggingface.co/" + modelId + "/resolve/" + revision + "/onnx/model_q4.onnx?download=true",
    path.join(modelDirectory, "onnx", "model_q4.onnx"),
    100_000_000
  );
  modelManifest = {
    ...modelManifest,
    model_file: "onnx/model_q4.onnx",
    model_size_bytes: model.length,
    model_sha256: createHash("sha256").update(model).digest("hex")
  };
} else {
  console.log("Mode --skip-model : le modèle ONNX est omis pour les tests d'interface.");
}

await mkdir(vendorDirectory);
const bundle = async (entry, output, target = "es2022") => esbuild.build({
  entryPoints: [path.join(root, entry)],
  bundle: true,
  format: "iife",
  platform: "browser",
  nodePaths: [path.join(root, "build-tools", "node_modules")],
  target: [target],
  outfile: path.join(vendorDirectory, output),
  minify: true,
  sourcemap: false
});

await bundle("scripts/offline-transformers-entry.js", "transformers.min.js");
await bundle("scripts/offline-tesseract-entry.js", "tesseract.min.js", "es2020");
await bundle("scripts/firebase-entry.js", "firebase-runtime.js");

const copyPackageFile = async (packageName, packageRelativePath, outputName) => {
  const source = path.join(packageRoot(packageName), packageRelativePath);
  const destination = path.join(vendorDirectory, outputName);
  await mkdir(path.dirname(destination));
  await fs.copyFile(source, destination);
  const stat = await fs.stat(destination);
  if (!stat.size) throw new Error("Fichier vendor vide : " + destination);
  console.log("Copié", path.relative(root, destination), stat.size, "octets");
};

await copyPackageFile("lucide", "dist/umd/lucide.js", "lucide.min.js");
await copyPackageFile("dexie", "dist/dexie.min.js", "dexie.min.js");
await copyPackageFile("marked", "lib/marked.umd.js", "marked.umd.js");
await copyPackageFile("dompurify", "dist/purify.min.js", "purify.min.js");

const ortRoot = packageRoot("onnxruntime-web");
const ortDistribution = path.join(ortRoot, "dist");
const ortDestination = path.join(vendorDirectory, "onnxruntime");
await mkdir(ortDestination);
for (const file of await fs.readdir(ortDistribution)) {
  if (/^ort-wasm.*\.(wasm|mjs|js)$/.test(file)) {
    await fs.copyFile(path.join(ortDistribution, file), path.join(ortDestination, file));
  }
}
if (!(await fs.readdir(ortDestination)).some(file => file.endsWith(".wasm"))) {
  throw new Error("Aucun binaire WASM ONNX Runtime n'a été copié.");
}

const tessRoot = packageRoot("tesseract.js");
await copyPackageFile("tesseract.js", "dist/worker.min.js", "tesseract-worker.min.js");
const coreRoot = packageRoot("tesseract.js-core");
const coreDistribution = path.join(coreRoot, "dist");
const coreDestination = path.join(vendorDirectory, "tesseract-core");
await mkdir(coreDestination);
for (const file of await fs.readdir(coreDistribution)) {
  if (/tesseract-core.*\.(wasm|js)$/.test(file)) {
    await fs.copyFile(path.join(coreDistribution, file), path.join(coreDestination, file));
  }
}
if (!(await fs.readdir(coreDestination)).some(file => file.endsWith(".wasm"))) {
  throw new Error("Le binaire WASM de Tesseract est absent.");
}

const tessdataDirectory = path.join(root, "app", "tessdata");
await download(
  "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/fra.traineddata",
  path.join(tessdataDirectory, "fra.traineddata"),
  1_000_000
);
await download(
  "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/eng.traineddata",
  path.join(tessdataDirectory, "eng.traineddata"),
  1_000_000
);

await fs.writeFile(
  path.join(root, "app", "offline-assets-manifest.json"),
  JSON.stringify({
    ...modelManifest,
    languages: ["fra", "eng"],
    generated_at: new Date().toISOString()
  }, null, 2) + "\n",
  "utf8"
);
console.log("Ressources hors ligne préparées. Modèle inclus :", !skipModel);
