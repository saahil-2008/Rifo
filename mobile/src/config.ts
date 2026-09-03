/**
 * Central config for the Rifo mobile app (dev build).
 *
 * The Android emulator reaches the host machine at 10.0.2.2. On a physical
 * device set DEV_HOST to your development machine's LAN IP (the phone's
 * "localhost" is the phone itself). This file is JS-only — editing it needs
 * no native rebuild, just a Metro reload.
 */
const DEV_HOST = '10.0.2.2'; // Android emulator -> host. Change to your LAN IP for a physical device.

export const API_BASE = `http://${DEV_HOST}:8000`;
export const WS_URL = `ws://${DEV_HOST}:8000/v1/verify/stream`;

export const API = {
  /** GET /v1/claim/{id} — refresh a single cached verdict (Detail screen). */
  claim: (claimId: number): string => `${API_BASE}/v1/claim/${claimId}`,
  /** POST /v1/verify — synchronous fallback (not the primary path). */
  verify: `${API_BASE}/v1/verify`,
  health: `${API_BASE}/health`,
};

export const VERIFY_TIMEOUT_MS = 30_000;
