import { Module } from "./zstd.js";

let initPromise = null;

function isError(code) {
  return Module._ZSTD_isError(code) !== 0;
}

export async function init(path = "/vendor/zstd-wasm/zstd.wasm") {
  if (initPromise) return initPromise;
  initPromise = new Promise((resolve) => {
    const previous = Module.onRuntimeInitialized;
    Module.onRuntimeInitialized = () => {
      if (typeof previous === "function") previous();
      resolve();
    };
    Module.init(path);
  });
  return initPromise;
}

export function compress(input, level = 3) {
  const source = input instanceof Uint8Array ? input : new Uint8Array(input);
  const bound = Module._ZSTD_compressBound(source.byteLength);
  const outputPtr = Module._malloc(bound);
  const inputPtr = Module._malloc(source.byteLength);
  Module.HEAPU8.set(source, inputPtr);
  try {
    const sizeOrError = Module._ZSTD_compress(outputPtr, bound, inputPtr, source.byteLength, level);
    if (isError(sizeOrError)) {
      throw new Error(`Zstandard compression failed with code ${sizeOrError}.`);
    }
    return new Uint8Array(Module.HEAPU8.buffer, outputPtr, sizeOrError).slice();
  } finally {
    Module._free(outputPtr);
    Module._free(inputPtr);
  }
}

export function decompress(input) {
  const source = input instanceof Uint8Array ? input : new Uint8Array(input);
  const inputPtr = Module._malloc(source.byteLength);
  Module.HEAPU8.set(source, inputPtr);
  let outputPtr = 0;
  try {
    const contentSize = Module._ZSTD_getFrameContentSize(inputPtr, source.byteLength);
    if (!Number.isFinite(contentSize) || contentSize <= 0) {
      throw new Error("Zstandard frame does not include a known decompressed size.");
    }
    outputPtr = Module._malloc(contentSize);
    const sizeOrError = Module._ZSTD_decompress(outputPtr, contentSize, inputPtr, source.byteLength);
    if (isError(sizeOrError)) {
      throw new Error(`Zstandard decompression failed with code ${sizeOrError}.`);
    }
    return new Uint8Array(Module.HEAPU8.buffer, outputPtr, sizeOrError).slice();
  } finally {
    if (outputPtr) Module._free(outputPtr);
    Module._free(inputPtr);
  }
}
