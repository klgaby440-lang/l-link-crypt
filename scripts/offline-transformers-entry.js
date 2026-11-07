import { env, pipeline } from "@huggingface/transformers";

env.allowLocalModels = true;
env.allowRemoteModels = false;
env.localModelPath = new URL("./models/", document.baseURI).href;
env.useBrowserCache = true;
env.backends.onnx.wasm.wasmPaths = new URL("./vendor/onnxruntime/", document.baseURI).href;
env.backends.onnx.wasm.numThreads = 1;
env.backends.onnx.wasm.proxy = false;

globalThis.LlinkOfflineRuntime = { env, pipeline };
