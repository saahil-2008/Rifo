/**
 * Device-local verdict history (FR-9 #2, constraint #21).
 *
 * Stored in AsyncStorage only. The server has no accounts, so history is never
 * fetched from the backend; the client persists a row when the `done` frame
 * arrives. `claimId` is stored alongside so the Detail screen can refresh via
 * GET /v1/claim/{id} later.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { HistoryRow, VerdictResult } from './types';

const KEY = 'rifo.history.v1';
const MAX_ROWS = 100;

function localId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Build a HistoryRow from a streamed result once `done` fires. */
export function rowFromResult(result: VerdictResult): HistoryRow {
  return {
    id: localId(),
    claimId: result.claimId,
    claim: result.claim,
    claimOriginal: result.claimOriginal ?? result.claim,
    sourceLang: result.sourceLang || 'en',
    label: result.label,
    confidence: result.confidence,
    checkCount: result.checkCount,
    firstSeen: new Date().toISOString(),
    explanation: result.explanation ?? '',
    evidence: result.evidence ?? [],
    createdAt: Date.now(),
  };
}

export async function loadHistory(): Promise<HistoryRow[]> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as HistoryRow[]) : [];
  } catch {
    return [];
  }
}

/** Persist on `done`. Re-checks of an already-stored claim update the row in
 *  place (the viral count advances) instead of appending a duplicate. */
export async function saveHistory(row: HistoryRow): Promise<HistoryRow[]> {
  const all = await loadHistory();
  const idx = all.findIndex((r) => row.claimId > 0 && r.claimId === row.claimId);
  if (idx >= 0) {
    const updated: HistoryRow = { ...all[idx], ...row, id: all[idx].id, createdAt: Date.now() };
    all.splice(idx, 1);
    all.unshift(updated);
  } else {
    all.unshift(row);
  }
  const trimmed = all.slice(0, MAX_ROWS);
  await AsyncStorage.setItem(KEY, JSON.stringify(trimmed));
  return trimmed;
}

export async function clearHistory(): Promise<void> {
  await AsyncStorage.removeItem(KEY);
}
