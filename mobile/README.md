# Rifo — mobile app (React Native + Kotlin overlay)

Phase-2 scaffold for the Android app (PRD milestones 7–13). It is **staged
source**: the JS/TS shell and the Kotlin overlay are reviewed here, then
`scripts/init_mobile.ps1` assembles them into a buildable RN project at
`<repo>/app/`.

```
mobile/
├── App.tsx                     root: navigation + onboarding gate + overlay wiring
├── android-native/             the Kotlin overlay (documented by PATCHES.md)
│   ├── OverlayModule.kt        NativeModules.RifoOverlay bridge
│   ├── OverlayService.kt       foreground service: projection, capture, bubble host
│   ├── OverlayBubble.kt        floating bubble: idle/working/verdict/error rendering
│   ├── ImagePreparer.kt        downscale→1280 + JPEG q75 + FLAG_SECURE detector
│   └── PATCHES.md              AndroidManifest / MainApplication wiring reference
└── src/
    ├── config.ts               DEV_HOST (10.0.2.2 emulator, LAN IP for a phone)
    ├── types.ts                verdicts, HistoryRow, WSFrame (mirror schemas.py)
    ├── theme.ts                per-verdict colours/copy, confidence/number helpers
    ├── overlay.ts              typed bridge to NativeModules.RifoOverlay
    ├── deviceId.ts             anonymous per-install UUID (not an account)
    ├── wsClient.ts             /v1/verify/stream WebSocket consumer (FR-7 frames)
    ├── api.ts                  GET /v1/claim/{id} refresh; sync POST fallback
    ├── historyStore.ts         device-local verdict history (AsyncStorage)
    ├── navigation.ts           root stack + imperative navigate helper
    ├── useVerificationFlow.ts  overlay events → WS → bubble → local history
    ├── components/             VerdictBadge, EvidenceCard
    └── screens/                Onboarding, History, Detail, Settings (FR-9)
```

## How verification works end to end

1. The bubble is a **Kotlin** window (`TYPE_APPLICATION_OVERLAY`,
   `FLAG_NOT_FOCUSABLE`) — not React Native (PRD §5 + constraint #1).
2. `ACTION_DOWN` on the bubble begins a capture immediately; holding 600 ms
   fires haptics and commits; an early lift discards the frame; dragging moves
   the bubble and never captures (FR-1/FR-2).
3. The service reuses one `VirtualDisplay` + `ImageReader` per session (FR-2),
   downscales to 1280 px and JPEG-encodes at q75 **off the main thread**, then
   emits `RifoCaptureReady { jpegBase64, width, height }` (FR-3).
4. `useVerificationFlow` flips the bubble to *working*, streams the frame over
   WebSocket to `/v1/verify/stream`, applies the verdict colour the moment the
   `verdict` frame lands, and persists a **device-local** history row on `done`.
5. Tapping the verdict bubble opens the Detail screen. Consent is re-requested
   if the projection is torn down (`RifoServiceStopped`).

Four screens (FR-9): **Onboarding** (notification → overlay → screen-capture
permissions, `POST_NOTIFICATIONS` guarded to API 33+), **History** (local only —
no server accounts, constraint #21), **Detail** (claim + localized verdict +
explanation + evidence cards, refresh via `GET /v1/claim/{id}`), **Settings**
(bubble on/off, clear history, re-run onboarding).

## Build it

```powershell
# one-time: scaffold app/, copy staged code, patch manifest, install deps
.\scripts\init_mobile.ps1

cd app
npm start          # Metro (keep open)
npm run android    # build + install on a running emulator/device
```

Requires Node ≥ 18, the Android SDK/JDK. First Gradle build downloads the
toolchain — allow it time.

## Configuration

- `app/src/config.ts` — `DEV_HOST = '10.0.2.2'` reaches the host from the Android
  emulator. On a **physical phone**, set it to your machine's LAN IP (the phone's
  localhost is the phone itself) and re-run Metro.
- Backend must be running on the host at port 8000 (`uvicorn app.main:app`),
  with keys in `backend/.env` (see `backend/.env.example`).

## Native overlay notes (read `android-native/PATCHES.md`)

- Runs only with `newArchEnabled=false` (classic bridge) — already set by the
  init script.
- The MediaProjection grant is **single-use and dies with the process**: if the
  overlay stops, the app re-prompts for consent. That is intended Android
  behaviour (FR-2), not a bug.
- Debug the overlay on a device/emulator (PRD §12): the projection cannot be
  inspected from the JS debugger, and the bubble itself appears in the captured
  frame (small, near an edge after you drag it).
- The FLAG_SECURE detector sends nothing to the server for protected screens —
  it emits a `flag_secure` error instead.
