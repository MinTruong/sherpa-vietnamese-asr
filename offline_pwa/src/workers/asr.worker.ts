import { runOfflinePipeline } from "../engine/pipeline";

self.onmessage = async (event: MessageEvent) => {
  try {
    const result = await runOfflinePipeline();
    self.postMessage({ type: "result", requestId: event.data?.requestId, result });
  } catch (error) {
    self.postMessage({
      type: "error",
      requestId: event.data?.requestId,
      message: error instanceof Error ? error.message : String(error),
    });
  }
};

