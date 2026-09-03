/**
 * Bridge to the native Kotlin overlay module (`RifoOverlay`).
 *
 * The overlay itself is Kotlin (PRD §5 + constraint #1) — NOT React Native.
 * JS only:
 *   - requests the three Android permissions during onboarding,
 *   - receives capture + error events from the overlay and runs verification,
 *   - pushes bubble-state changes back to the overlay so it renders
 *     idle / working / verdict / error without the JS thread.
 *
 * Event contract (native -> JS, DeviceEventEmitter):
 *   'RifoCaptureReady'  { jpegBase64, width, height }   long-press completed
 *   'RifoBubbleTapped'  {}                              tap on a verdict bubble
 *   'RifoError'         { code, message }               flag_secure | capture | other
 *   'RifoServiceStopped'{}                              service killed -> re-consent
 */
import { DeviceEventEmitter, NativeEventEmitter, NativeModules, Platform } from 'react-native';
import type { BubbleState, CapturePayload, VerdictLabel } from './types';

const native = NativeModules.RifoOverlay as
  | {
      requestOverlayPermission: () => Promise<boolean>;
      requestScreenCapture: () => Promise<boolean>;
      startOverlay: () => Promise<boolean>;
      stopOverlay: () => Promise<void>;
      isOverlayActive: () => Promise<boolean>;
      setBubbleState: (state: BubbleState, payload?: string) => void;
      dismissBubble: () => void;
    }
  | undefined;

// The native side emits events through a legacy NativeEventEmitter; in new-arch
// builds it still surfaces on the same NativeModules handle.
const emitter =
  native && NativeEventEmitter ? new NativeEventEmitter(NativeModules.RifoOverlay) : null;

const overlayUnavailable = !native || Platform.OS !== 'android';

function guard<T>(p: () => Promise<T>, fallback: T): Promise<T> {
  return overlayUnavailable ? Promise.resolve(fallback) : p();
}

export const RifoOverlay = {
  available: !overlayUnavailable,

  /** SYSTEM_ALERT_WINDOW. Prompts via the system intent if not yet granted. */
  requestOverlayPermission: () => guard(() => native!.requestOverlayPermission(), false),

  /** MediaProjection consent -> starts the foreground service + bubble on grant. */
  requestScreenCapture: () => guard(() => native!.requestScreenCapture(), false),

  /** (Re)start the overlay service with an already-granted projection. */
  startOverlay: () => guard(() => native!.startOverlay(), false),

  stopOverlay: () => guard(() => native!.stopOverlay(), undefined),

  isOverlayActive: () => guard(() => native!.isOverlayActive(), false),

  /** Update the bubble's visual state. `payload` = JSON with label/claim/message. */
  setBubbleState: (state: BubbleState, payload?: Record<string, unknown>) => {
    if (!overlayUnavailable) {
      native!.setBubbleState(state, payload ? JSON.stringify(payload) : undefined);
    }
  },

  dismissBubble: () => {
    if (!overlayUnavailable) {
      native!.dismissBubble();
    }
  },
};

export type OverlayEvents = {
  captureReady: (payload: CapturePayload) => void;
  bubbleTapped: () => void;
  error: (e: { code: string; message: string }) => void;
  serviceStopped: () => void;
};

/** Subscribe to native overlay events. Returns an unsubscribe function. */
export function subscribeOverlay(handlers: OverlayEvents): () => void {
  const subs =
    emitter != null
      ? [
          emitter.addListener('RifoCaptureReady', (p: CapturePayload) => handlers.captureReady(p)),
          emitter.addListener('RifoBubbleTapped', () => handlers.bubbleTapped()),
          emitter.addListener('RifoError', (e) => handlers.error(e)),
          emitter.addListener('RifoServiceStopped', () => handlers.serviceStopped()),
        ]
      : [];
  return () => subs.forEach((s) => s.remove());
}

/** Bubble label colours keyed by verdict — mirrored in Kotlin. */
export const BUBBLE_COLORS: Record<VerdictLabel, string> = {
  genuine: '#0A7B3E',
  misleading: '#B26A00',
  fake: '#B3261E',
  manipulated: '#7B1FA2',
  insufficient: '#616161',
};

/** For screens/tests that run without the native module (web/emulator without
 *  the overlay). Keeps DeviceEventEmitter listeners to a minimum. */
export const overlayEmitter = DeviceEventEmitter;
