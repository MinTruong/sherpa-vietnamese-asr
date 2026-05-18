export type PipelinePhase =
  | "audio"
  | "vad"
  | "asr"
  | "punctuation"
  | "diarization"
  | "quality"
  | "overlap";

export interface PipelineProgress {
  phase: PipelinePhase;
  percent: number;
  message: string;
}

export interface OfflinePipelineOptions {
  asrModelId: string;
  speakerModelId: string;
  punctuation: boolean;
  diarization: boolean;
  overlapSeparation: boolean;
  bypassVad: boolean;
}

export interface OfflineTranscriptSegment {
  type: "text" | "speaker" | "gap";
  text?: string;
  speaker_id?: number;
  start_time?: number;
  end_time?: number;
}

export interface OfflinePipelineResult {
  model: string;
  duration_sec: number;
  segments: OfflineTranscriptSegment[];
  speaker_names: Record<string, string>;
}

export async function runOfflinePipeline(): Promise<OfflinePipelineResult> {
  throw new Error("Offline browser inference pipeline is not implemented in the baseline scaffold.");
}

