import type { Stance, VerdictLabel } from './types';

/** Colour + copy metadata for the five verdict labels (PRD §3 taxonomy).
 *  Used by screens/badges. The floating bubble's colours live in Kotlin
 *  (it must render without the JS thread). */
export const VERDICT_META: Record<
  VerdictLabel,
  { title: string; accent: string; soft: string; onAccent: string }
> = {
  genuine: { title: 'Genuine', accent: '#0A7B3E', soft: '#E3F3E9', onAccent: '#FFFFFF' },
  misleading: { title: 'Misleading', accent: '#B26A00', soft: '#FFF1DE', onAccent: '#FFFFFF' },
  fake: { title: 'Fake', accent: '#B3261E', soft: '#FBE9E7', onAccent: '#FFFFFF' },
  manipulated: { title: 'Manipulated', accent: '#7B1FA2', soft: '#F3E7FA', onAccent: '#FFFFFF' },
  insufficient: { title: 'Insufficient', accent: '#616161', soft: '#EDEDED', onAccent: '#FFFFFF' },
};

export const STANCE_META: Record<Stance, { title: string; color: string }> = {
  supports: { title: 'Supports', color: '#0A7B3E' },
  refutes: { title: 'Refutes', color: '#B3261E' },
  neutral: { title: 'Neutral', color: '#616161' },
};

export function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function formatCheckCount(n: number): string {
  return n.toLocaleString('en-IN');
}
