/** Shared TypeScript types. Mirrors the backend contracts in
 *  backend/app/models/schemas.py (REST + WS frames) — keep in sync. */

export type VerdictLabel =
  | 'genuine'
  | 'misleading'
  | 'fake'
  | 'manipulated'
  | 'insufficient';

export type Stance = 'supports' | 'refutes' | 'neutral';

export type BubbleState = 'idle' | 'working' | 'verdict' | 'error';

/** One evidence card (matches GET /v1/claim/{id} evidence[] entries). */
export interface EvidenceItem {
  url: string;
  domain: string;
  title: string;
  snippet: string;
  stance: Stance;
  stance_score: number;
  published_at: string | null;
  credibility: number;
}

/** A verdict the client persisted locally after a `done` frame (FR-9 #2).
 *  Stored device-locally only — the server has no accounts. */
export interface HistoryRow {
  id: string; // local uuid
  claimId: number;
  claim: string; // English-normalized
  claimOriginal: string; // source-language wording
  sourceLang: string;
  label: VerdictLabel;
  confidence: number;
  checkCount: number;
  firstSeen: string; // ISO
  explanation: string;
  evidence: EvidenceItem[];
  createdAt: number; // ms epoch, for sorting
}

/** WebSocket frames from /v1/verify/stream (FR-7). Order on the wire:
 *  extracted → cache_hit|cache_miss → verdict → evidence → explanation → done,
 *  or error on any terminating failure. */
export type WSFrame =
  | { stage: 'extracted'; claim: string; claim_original: string; source_lang: string }
  | { stage: 'cache_hit' }
  | { stage: 'cache_miss' }
  | {
      stage: 'verdict';
      claim_id: number;
      label: VerdictLabel;
      confidence: number;
      check_count: number;
    }
  | { stage: 'evidence'; items: EvidenceItem[] }
  | { stage: 'explanation'; text: string }
  | { stage: 'done' }
  | { stage: 'error'; code: string; message: string };

/** Consolidated result a screen/bubble can render. */
export interface VerdictResult {
  claim: string;
  claimOriginal: string;
  sourceLang: string;
  label: VerdictLabel;
  confidence: number;
  claimId: number;
  checkCount: number;
  cached: boolean;
  explanation: string;
  evidence: EvidenceItem[];
}

/** Payload sent from the native overlay after a successful capture. */
export interface CapturePayload {
  jpegBase64: string;
  width: number;
  height: number;
}
