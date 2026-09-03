/**
 * WebSocket client for /v1/verify/stream (FR-7).
 *
 * Primary verification path. The bubble is updated the moment the `verdict`
 * frame arrives (before `explanation` is even generated); evidence/explanation
 * only matter to the Detail screen. Every terminating frame is either `done`
 * or `error` — never neither.
 */
import { VERIFY_TIMEOUT_MS, WS_URL } from './config';
import type { VerdictResult, WSFrame } from './types';

export interface VerifyHandlers {
  /** Verdict is available the instant its frame arrives — update the bubble. */
  onVerdict: (partial: Pick<VerdictResult, 'label' | 'confidence' | 'claimId' | 'checkCount'>) => void;
  /** Terminal success with the fully assembled result. */
  onDone?: (result: VerdictResult) => void;
  /** Terminal failure. */
  onError?: (code: string, message: string) => void;
}

function frameText(raw: string): string {
  return raw.replace(/<[^>]+>/g, ' ');
}

/** Open a single-shot connection, stream frames, resolve on done/error. */
export function verifyAndStream(
  imageB64: string,
  deviceId: string,
  handlers: VerifyHandlers,
): () => void {
  const ws = new WebSocket(WS_URL);
  const result: VerdictResult = {
    claim: '',
    claimOriginal: '',
    sourceLang: 'en',
    label: 'insufficient',
    confidence: 0,
    claimId: 0,
    checkCount: 0,
    cached: false,
    explanation: '',
    evidence: [],
  };

  let settled = false;
  const timeout = setTimeout(() => {
    if (!settled) {
      settled = true;
      ws.close();
      handlers.onError?.('timeout', 'The verification took too long.');
    }
  }, VERIFY_TIMEOUT_MS);

  function finish(code: string, message: string): void {
    if (settled) {
      return;
    }
    settled = true;
    clearTimeout(timeout);
    try {
      ws.close();
    } catch {
      /* already closed */
    }
    handlers.onError?.(code, message);
  }

  ws.onopen = () => {
    ws.send(JSON.stringify({ image_b64: imageB64, device_id: deviceId }));
  };

  ws.onmessage = (event) => {
    let frame: WSFrame;
    try {
      frame = JSON.parse(event.data as string) as WSFrame;
    } catch {
      return; // ignore malformed frame
    }

    switch (frame.stage) {
      case 'extracted':
        result.claim = frame.claim;
        result.claimOriginal = frame.claim_original;
        result.sourceLang = frame.source_lang;
        break;
      case 'cache_hit':
        result.cached = true;
        break;
      case 'cache_miss':
        result.cached = false;
        break;
      case 'verdict':
        result.label = frame.label;
        result.confidence = frame.confidence;
        result.claimId = frame.claim_id;
        result.checkCount = frame.check_count;
        // Bubble updates here — do NOT wait for evidence/explanation (FR-7).
        handlers.onVerdict({
          label: frame.label,
          confidence: frame.confidence,
          claimId: frame.claim_id,
          checkCount: frame.check_count,
        });
        break;
      case 'evidence':
        result.evidence = frame.items ?? [];
        break;
      case 'explanation':
        result.explanation = frame.text;
        break;
      case 'done':
        if (settled) {
          break;
        }
        settled = true;
        clearTimeout(timeout);
        // Explanation may be empty only if nothing was streamed.
        if (result.claimOriginal === '' && result.claim !== '') {
          result.claimOriginal = result.claim;
        }
        handlers.onDone?.(result);
        break;
      case 'error':
        finish(frame.code, frame.message);
        break;
      default:
        break;
    }
  };

  ws.onerror = () => finish('network', 'Could not reach the verification server.');
  ws.onclose = () => {
    if (!settled) {
      finish('network', 'Connection closed before verification completed.');
    }
  };

  return () => {
    if (!settled) {
      settled = true;
      clearTimeout(timeout);
      try {
        ws.close();
      } catch {
        /* noop */
      }
    }
  };
}

export { frameText };
