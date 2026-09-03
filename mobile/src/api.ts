/**
 * HTTP helpers. The primary path is WebSocket; HTTP is used only for
 * GET /v1/claim/{id} (Detail-screen refresh of a stale local row, PRD §8)
 * and as a fallback POST /v1/verify.
 */
import { API } from './config';
import type { EvidenceItem, HistoryRow, VerdictLabel } from './types';

interface ClaimResponseRaw {
  claim_id: number;
  claim: string;
  claim_original: string;
  source_lang: string;
  label: VerdictLabel;
  confidence: number;
  check_count: number;
  first_seen: string;
  cached: boolean;
  evidence: EvidenceItem[];
  explanation: string;
}

async function getJson<T>(url: string, timeoutMs = 10_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

/** GET /v1/claim/{id} — returns the freshest server copy of a verdict. */
export async function fetchClaim(claimId: number): Promise<HistoryRow> {
  const raw = await getJson<ClaimResponseRaw>(API.claim(claimId));
  return {
    id: `server-${raw.claim_id}`,
    claimId: raw.claim_id,
    claim: raw.claim,
    claimOriginal: raw.claim_original ?? raw.claim,
    sourceLang: raw.source_lang || 'en',
    label: raw.label,
    confidence: raw.confidence,
    checkCount: raw.check_count,
    firstSeen: raw.first_seen,
    explanation: raw.explanation ?? '',
    evidence: raw.evidence ?? [],
    createdAt: Date.now(),
  };
}

/** POST /v1/verify — synchronous fallback used only when WS is unavailable. */
export async function verifySync(imageB64: string, deviceId: string): Promise<HistoryRow> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  try {
    const res = await fetch(API.verify, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_b64: imageB64, device_id: deviceId }),
      signal: controller.signal,
    });
    if (!res.ok) {
      let detail = '';
      try {
        detail = (await res.json()).detail?.message ?? '';
      } catch {
        /* noop */
      }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return mapResponse(await (res.json() as Promise<ClaimResponseRaw>));
  } finally {
    clearTimeout(timer);
  }
}

function mapResponse(raw: ClaimResponseRaw): HistoryRow {
  return {
    id: `server-${raw.claim_id}`,
    claimId: raw.claim_id,
    claim: raw.claim,
    claimOriginal: raw.claim_original ?? raw.claim,
    sourceLang: raw.source_lang || 'en',
    label: raw.label,
    confidence: raw.confidence,
    checkCount: raw.check_count,
    firstSeen: raw.first_seen,
    explanation: raw.explanation ?? '',
    evidence: raw.evidence ?? [],
    createdAt: Date.now(),
  };
}
