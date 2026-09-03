/**
 * Connects the native overlay to verification (FR-7 / FR-10 orchestration).
 *
 * Flow:
 *   long-press → Kotlin captures + prepares the JPEG → emits `RifoCaptureReady`
 *     → JS sets the bubble to "working", opens /v1/verify/stream
 *     → the `verdict` frame flips the bubble to its colour-coded state
 *     → `done` persists a history row locally (constraint #21)
 *     → tapping the verdict bubble navigates to the Detail screen
 *
 * Runs once from the app root. Exposes an event the UI can react to when the
 * overlay service dies so consent can be re-requested (FR-2).
 */
import { useEffect, useRef } from 'react';
import { getDeviceId } from './deviceId';
import { rowFromResult, saveHistory } from './historyStore';
import { navigateTo } from './navigation';
import { RifoOverlay, subscribeOverlay } from './overlay';
import type { VerdictLabel } from './types';
import { verifyAndStream } from './wsClient';

const ERROR_IDLE_MS = 4000;

export interface LastVerdict {
  label: VerdictLabel;
  confidence: number;
  claimId: number;
}

/**
 * Registers the app-wide verification handlers. Call exactly once from the
 * root component. `onServiceStopped` lets the shell prompt for re-consent.
 */
export function useVerificationFlow(onServiceStopped?: () => void): {
  lastVerdictRef: React.MutableRefObject<LastVerdict | null>;
} {
  const lastVerdictRef = useRef<LastVerdict | null>(null);
  const busyRef = useRef(false);
  const cancelRef = useRef<(() => void) | null>(null);
  const onStoppedRef = useRef(onServiceStopped);
  onStoppedRef.current = onServiceStopped;

  useEffect(() => {
    function scheduleIdle(): void {
      setTimeout(() => {
        if (RifoOverlay.available) {
          RifoOverlay.setBubbleState('idle');
        }
      }, ERROR_IDLE_MS);
    }

    function release(): void {
      busyRef.current = false;
      cancelRef.current = null;
    }

    async function handleCapture(jpegBase64: string): Promise<void> {
      if (busyRef.current) {
        return; // one verification at a time — drop an overlapping capture
      }
      busyRef.current = true;
      try {
        RifoOverlay.setBubbleState('working');
        const deviceId = await getDeviceId();
        cancelRef.current = verifyAndStream(jpegBase64, deviceId, {
          onVerdict: (v) => {
            lastVerdictRef.current = v;
            RifoOverlay.setBubbleState('verdict', {
              label: v.label,
              confidence: v.confidence,
              claim_id: v.claimId,
            });
          },
          onDone: async (result) => {
            release();
            if (result.claimId > 0 || result.claim) {
              await saveHistory(rowFromResult(result));
            }
            // Bubble already shows the verdict; nothing more to push.
          },
          onError: (code, message) => {
            release();
            RifoOverlay.setBubbleState('error', { code, message });
            scheduleIdle();
          },
        });
      } catch {
        release();
        RifoOverlay.setBubbleState('error', { code: 'local', message: 'Could not start verification.' });
        scheduleIdle();
      }
    }

    const unsub = subscribeOverlay({
      captureReady: (payload) => {
        void handleCapture(payload.jpegBase64);
      },
      bubbleTapped: () => {
        const last = lastVerdictRef.current;
        if (last && last.claimId > 0) {
          // Detail resolves the row from local history by claimId.
          navigateTo('Detail', { claimId: last.claimId });
        }
      },
      error: (e) => {
        RifoOverlay.setBubbleState('error', { code: e.code, message: e.message });
        scheduleIdle();
      },
      serviceStopped: () => {
        onStoppedRef.current?.();
      },
    });

    // At launch the overlay may already be running (service persisted across
    // app restarts); sync it to a clean idle bubble rather than guessing.
    if (RifoOverlay.available) {
      RifoOverlay.isOverlayActive().then((active) => {
        if (!active) {
          RifoOverlay.setBubbleState('idle');
        }
      });
    }

    return () => {
      unsub();
      cancelRef.current?.();
      cancelRef.current = null;
    };
  }, []);

  return { lastVerdictRef };
}
