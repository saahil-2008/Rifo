# PRD — Overlay Misinformation Verification System

**Version:** 2.1 (final review)
**Phase:** 1 (Android overlay, screenshot-based verification)
**Status:** Ready for implementation
**Target:** Hackathon demo build. Not production, not deployed.

> **v2.0 changes from v1.2:** On-device OCR and region detection removed. The full screenshot is uploaded and a vision model performs extraction. All hashing removed; caching is vector-similarity only. Language scope expanded to all major Indian languages. See section 15 for what this traded away.

---

## 1. Problem

Misinformation on WhatsApp, Instagram, and news sites spreads faster than manual fact-checking can respond. Existing fact-checking tools require the user to leave the app, copy a link or text, open a website, and paste it. That friction means almost nobody checks anything.

## 2. Product goal

A floating overlay bubble on Android that verifies whatever is on screen, without the user leaving the app they are in.

The user long-presses the bubble. The screen is captured and uploaded, a vision model extracts the checkable claim, the claim is verified against retrieved evidence, and one of the five verdicts in section 3 appears on the bubble. Supporting evidence is available by tapping through to the app.

**Primary optimization target is end-to-end latency.** Where a design choice trades accuracy for speed, take the speed, and document the loss.

## 3. Verdict taxonomy

Exactly five output labels. Do not add, rename, or subdivide.

| Label | Meaning |
|---|---|
| `genuine` | Supported by credible sources |
| `misleading` | Partially true, missing critical context |
| `fake` | Contradicted by credible sources |
| `manipulated` | Media is real but out of context, or digitally altered |
| `insufficient` | Not enough evidence to judge — a valid, expected outcome |

---

## 4. Scope

### 4.1 In scope

- Android floating overlay bubble with long-press activation
- MediaProjection screen capture with a persistent session
- Client-side downscale and JPEG compression before upload
- Server-side vision extraction: OCR, claim identification, English normalization, in one call
- Text claim verification
- Image verification via reverse image search (out-of-context detection)
- FastAPI backend with a LangGraph verification pipeline
- Postgres + pgvector for vector-based claim caching and evidence storage
- React Native app shell: onboarding, permissions, verdict history, evidence detail
- WebSocket streaming so the verdict renders before the explanation

### 4.2 Out of scope — do not build

- Video or audio verification
- Real-time frame-by-frame processing
- Chrome extension
- iOS app of any kind
- On-device OCR, ML Kit of any variety
- Any hashing: perceptual, SHA-256, or otherwise
- Client-side region detection or selection-tint heuristics
- User accounts, authentication, login, signup
- Payment, subscriptions, analytics dashboards
- Deployment infrastructure, CI/CD, Kubernetes, Terraform
- Deepfake detection, Error Level Analysis
- Face detection
- Push notification infrastructure
- Multi-tenancy

If a requirement is not listed in section 4.1, it is out of scope. Do not add features that seem helpful.

---

## 5. Repository structure

```
/backend                          FastAPI + LangGraph    Python 3.11+
/app                              React Native shell     TypeScript
  └── android/app/src/main/java/  Kotlin overlay module
/db                               SQL migrations
/docs                             This PRD
```

The Kotlin overlay lives **inside** the React Native project's `android/` directory as a native module, not as a separate top-level project. React Native already owns that directory; creating a parallel `/android` root will produce two Gradle projects that cannot share a build.

The overlay, foreground service, MediaProjection session, and image downscaling are implemented in Kotlin and exposed to the JS layer through a `NativeModule` with a `DeviceEventEmitter` for verdict updates. The overlay is **not** implemented in React Native.

---

## 6. Tech stack — fixed

| Layer | Choice | Constraint |
|---|---|---|
| Backend | FastAPI, Python 3.11+ | async throughout |
| Orchestration | LangGraph | fixed graph, not a ReAct agent |
| Database | PostgreSQL 15+ with pgvector | |
| Vision extraction | Gemini 2.0 Flash (or GPT-4o-mini / Claude Haiku) | must accept images, must be a *fast* tier |
| Text embeddings | `multilingual-e5-small` | local, 384-dim, **must be multilingual** |
| NLI | `mDeBERTa-v3-base-xnli` | base, **not** large |
| Web + news search | Brave Search API | generous free tier, two endpoints |
| Reverse image search | SerpApi (Google Lens endpoint) | metered — call only on the image path |
| Fact-check lookup | Google Fact Check Tools API | free |
| Overlay / capture | Kotlin, Android SDK | minSdk 26, targetSdk current |
| App shell | React Native, TypeScript | results UI only |
| Local storage | SQLite via RN async storage | verdict history, device-local |

**Do not substitute `bge-small-en-v1.5`, `all-MiniLM-L6-v2`, or `DeBERTa-v3-base-MNLI`.** All three are English-only. They do not error on Hindi or Tamil input — they return meaningless vectors and near-random entailment scores, which corrupts cache matching and verdicts silently. `multilingual-e5-small` is 384-dim, matching the schema in section 9.

**Language scope:** every script the vision model can read, which covers Hindi, Marathi, Bengali, Tamil, Telugu, Kannada, Malayalam, Gujarati, Punjabi, Odia, Urdu, and romanized Hinglish. There is no script allowlist. This is the main benefit of moving extraction server-side.

---

## 7. Functional requirements

### FR-1 — Overlay bubble

The bubble is a persistent floating window, draggable, snapping to screen edges.

- Window type `TYPE_APPLICATION_OVERLAY`
- Flags include `FLAG_NOT_FOCUSABLE` so the bubble never steals focus from the app underneath
- Hosted by a foreground service with `foregroundServiceType="mediaProjection"`
- Long-press threshold 600 ms, with haptic feedback on trigger
- Displays four visual states: idle, working, verdict, error
- Verdict state is colour-coded per label and persists until dismissed or replaced

**Acceptance:** bubble persists across app switches and device rotation; dragging it does not trigger a capture; long-pressing does not disturb the app underneath.

### FR-2 — Screen capture

- `MediaProjection` consent requested **once** during onboarding; the session persists behind the foreground service
- `VirtualDisplay` and `ImageReader` created once per session and reused — recreating per capture costs ~400 ms
- The foreground service must be started **before** `getMediaProjection()` is called
- A `MediaProjection.Callback` must be registered, or the session is silently invalidated
- If the service is killed, consent must be re-requested; handle this without crashing
- Capture begins on `ACTION_DOWN`, not on long-press completion; discard the bitmap if the user lifts early
- All-black frames indicate a `FLAG_SECURE` app — detect and emit the `flag_secure` error state

**Acceptance:** second and subsequent captures show no consent dialog; capture-to-bitmap completes in under 150 ms; a banking app produces the error state rather than uploading a black frame.

### FR-3 — Client-side image preparation

This is the only image processing that happens on the device. There is no OCR, no region detection, no cropping heuristic.

- Downscale the bitmap so the longest edge is **1280 px**
- Encode JPEG at **quality 75**
- Target payload **under 200 KB**; log a warning above 300 KB
- Do all of this off the main thread
- Upload the whole frame — do not attempt to guess which part the user cared about

Upload size is the single largest controllable component of latency on mobile data. A full-resolution PNG screenshot is 2–4 MB and will add several seconds on a weak connection.

**Acceptance:** a 1440p screenshot produces a payload under 200 KB in under 120 ms; the UI does not jank during preparation.

### FR-4 — Vision extraction

One model call replaces what were previously four separate stages: OCR, region detection, claim extraction, and translation.

The model receives the screenshot and returns strict JSON:

```json
{
  "claim_id": 8412,
  "claim": "Amitabh Bachchan has died",
  "claim_original": "अमिताभ बच्चन का निधन हो गया",
  "source_lang": "hi",
  "content_type": "text_message",
  "has_image_content": false,
  "checkable": true
}
```

Requirements:

- `claim` is **exactly one** primary checkable claim, normalized to English. Not an array. The bubble displays one badge and the schema maps one claim per verification, so multiple claims have nowhere to go.
- `claim_original` preserves the source-language wording for display.
- `content_type` is one of `text_message`, `news_article`, `social_post`, `image_with_caption`, `image_only`, `other`.
- `has_image_content` is true when a photograph or graphic is present that itself warrants reverse image search.
- `checkable` is false for opinion, greetings, personal conversation, or anything with no verifiable assertion.
- When multiple candidate claims appear on screen, select the most prominent and most checkable. Do not concatenate.
- Constrain output with a JSON schema or response-format parameter. Do not parse free text.

If `checkable` is false, short-circuit immediately and emit an **error** frame with code `no_claim_found`. Do not emit a verdict frame, and persist nothing. There is no claim for a verdict to attach to, so `insufficient` is the wrong response here — that label is for claims that exist but cannot be resolved.

**Acceptance:** a WhatsApp screenshot in Devanagari returns a correct English claim and `source_lang: "hi"`; a Tamil screenshot does the same; a screenshot of a personal chat returns `checkable: false`; the response always parses as JSON without cleanup.

### FR-5 — Verification pipeline

```
vision_extract ──[not checkable]──→ RETURN insufficient
       │
       ▼
  embed_claim
       │
       ▼
 cache_probe ──[hit]──→ RETURN CACHED
       │
    [miss]
       ▼
 factcheck_hit ──[hit]──→ RETURN
       │
       ▼
   retrieve  (single asyncio.gather:
       │        source-language search + English search + vector corpus
       │        + reverse_image_search when has_image_content)
       ▼
  nli_stance
       │
       ▼
  aggregate → EMIT VERDICT
       │
       ▼
   explain → localize → stream
```

One conditional retry edge: if `aggregate` yields `insufficient` and `retry_count == 0`, loop to `retrieve` with a broadened query. Hard cap at one retry.

Node requirements, in execution order:

- **`vision_extract`** — see FR-4. Single call, JSON-constrained, fast model tier.
- **`embed_claim`** — `multilingual-e5-small` over the normalized English claim. Local, no network call, ~20 ms.
- **`cache_probe`** — **pgvector cosine similarity only. There is no hash lookup.** Threshold 0.93 against `claims.embedding`, filtered to non-expired verdicts. A single indexed vector query. Increment `check_count` on hit.
  Threshold 0.93 is deliberately tighter than the 0.92 used when a hash provided an exact-match first pass. Without that safety net, a loose threshold will collide semantically similar but factually distinct claims — "X was arrested" and "X was released" embed closely. If you observe false cache hits, raise the threshold, do not lower it.
- **`factcheck_hit`** — Google Fact Check Tools API plus a local ClaimReview mirror. Short-circuit on match above threshold. Resolves most celebrity death hoaxes in ~150 ms.
- **`retrieve`** — **must** use `asyncio.gather` across Brave web search, Brave news search, and the local vector corpus. Per-source timeout 800 ms, `return_exceptions=True`, proceed with partial results.
  When `source_lang != "en"`, fork the query: search in the source language **and** in English within the same `gather`. Regional-language debunks live on regional fact-checkers (Vishvas News, Newschecker, BOOM, Factly) and will not surface from an English query. Translate non-English evidence snippets to English before `nli_stance`. Because the fork is parallel, it costs no additional latency.
- **`nli_stance`** — model loaded once at FastAPI startup into module scope. All (claim, evidence) pairs batched into a **single** forward pass.
- **`reverse_image_search`** — runs only when `has_image_content` is true, and **inside the same `asyncio.gather` as `retrieve`**, not as a step after it. SerpApi Google Lens endpoint, 1–2 s typical. Run in parallel and it costs nothing, since retrieval is already the long pole; run it sequentially after `nli_stance` and it adds its full duration to every image verification. Extract the earliest publication date across results and persist to `verdicts.earliest_date`.
- **`aggregate`** — deterministic rules weighted by source credibility. No model call.
- **`explain`** — constrained strictly to summarizing retrieved snippets. Must not introduce facts absent from the evidence set. Persist to `verdicts.explanation` so cache hits serve it without regenerating.
- **`localize`** — translate the verdict label and explanation into `source_lang` before streaming. Evidence titles and snippets stay in their original language with the source domain shown. No-op when `source_lang == "en"`.

**Acceptance:** graph is deterministic across repeated identical inputs; no node makes an unbounded number of tool calls; the NLI model is instantiated exactly once per process; a cache hit performs no retrieval and no explanation generation.

### FR-6 — Aggregation rules

Deterministic, no model call. Weight each stance by the credibility score of its source domain, then:

```
refutes dominant, credible sources          → fake
supports dominant, credible sources         → genuine
support and refute both present, mixed      → misleading
image earliest publication predates the
  claimed context by a wide margin          → manipulated
top evidence credibility-weighted score
  below floor, or fewer than 2 sources      → insufficient
```

`manipulated` takes precedence over `genuine` when both conditions hold — a real photo used out of context is the more useful verdict.

**Acceptance:** identical evidence sets always produce identical labels; every label in section 3 is reachable by some input.

### FR-7 — Streaming response

WebSocket at `/v1/verify/stream`.

Cache miss:

```json
{"stage":"extracted","claim":"Amitabh Bachchan has died","claim_original":"...","source_lang":"hi"}
{"stage":"cache_miss"}
{"stage":"verdict","claim_id":8412,"label":"fake","confidence":0.94,"check_count":4231}
{"stage":"evidence","items":[...]}
{"stage":"explanation","text":"..."}
{"stage":"done"}
```

Cache hit:

```json
{"stage":"extracted","claim":"...","claim_original":"...","source_lang":"hi"}
{"stage":"cache_hit"}
{"stage":"verdict","claim_id":8412,"label":"fake","confidence":0.94,"check_count":4232}
{"stage":"evidence","items":[...]}
{"stage":"explanation","text":"..."}
{"stage":"done"}
```

Error:

```json
{"stage":"error","code":"flag_secure|no_claim_found|upload_failed|timeout","message":"..."}
```

The `extracted` frame must carry the claim on **both** paths — the Detail screen renders it, and omitting it on cache hits leaves that field blank.

The `verdict` frame must be emitted before the explanation is generated. The bubble updates on `verdict` and ignores every later frame; only the Detail screen consumes `evidence` and `explanation`.

**Acceptance:** the bubble displays a label while `explanation` is still streaming; the claim text is present on the cache-hit path; every terminating path emits either `done` or `error`, never neither.

### FR-8 — Viral counter

Increment `claims.check_count` on every cache hit. Return it in the `verdict` frame. Display in the app as:

> This has been checked 4,231 times. First seen 3 days ago.

**Acceptance:** submitting the same claim twice returns an incremented count on the second call.

### FR-9 — React Native app shell

Four screens only:

1. **Onboarding** — permission requests in order: `POST_NOTIFICATIONS`, `SYSTEM_ALERT_WINDOW`, start service, MediaProjection consent. Guard `POST_NOTIFICATIONS` behind an API 33 check; it does not exist below that and requesting it unconditionally throws on older devices.
2. **History** — list of past verdicts with label, timestamp, truncated claim. **Stored device-locally in SQLite, not fetched from the backend.** There are no accounts, so the server cannot scope history to a user; `device_id` is an anonymous counter for the viral count only and must not be used as a pseudo-account. Persist locally when the `done` frame arrives.
3. **Detail** — claim in both original and English, verdict, confidence, evidence cards with source domain, date, stance, outbound link.
4. **Settings** — toggle bubble, clear history.

**Acceptance:** onboarding completes on a fresh install with no crash; tapping the bubble's verdict state opens the Detail screen for that verification.

---

## 8. API contracts

```
WS   /v1/verify/stream       primary path, progressive frames
POST /v1/verify              sync fallback, full response
GET  /v1/claim/{id}          re-fetch one cached verdict
GET  /health                 readiness, includes model-loaded status
```

`GET /v1/claim/{id}` lets the Detail screen refresh a stale local record. It takes the `claim_id` returned in the verdict response, which the client must persist alongside the local history row — without it this endpoint is uncallable. It is **not** a history listing endpoint; there is no endpoint returning all verdicts for a device, because there are no accounts.

There is no separate image endpoint. Every request is a screenshot; the vision model decides whether image content is present.

Request:

```json
{
  "image_b64": "<downscaled JPEG, under 200KB>",
  "device_id": "anon-uuid"
}
```

No `client_hash`. No `phash`. No `content` field — the server extracts everything from the image.

Response:

```json
{
  "claim_id": 8412,
  "claim": "Amitabh Bachchan has died",
  "claim_original": "अमिताभ बच्चन का निधन हो गया",
  "source_lang": "hi",
  "label": "fake",
  "confidence": 0.94,
  "check_count": 4231,
  "first_seen": "2026-08-31T09:12:00Z",
  "cached": false,
  "evidence": [
    {
      "url": "https://...",
      "domain": "altnews.in",
      "title": "...",
      "snippet": "...",
      "stance": "refutes",
      "stance_score": 0.91,
      "published_at": "2026-09-01T04:00:00Z",
      "credibility": 0.88
    }
  ],
  "explanation": "..."
}
```

`claim` is singular throughout. Do not reintroduce an array.

---

## 9. Data model

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE claims (
    id            BIGSERIAL PRIMARY KEY,
    text          TEXT NOT NULL,          -- normalized English claim
    text_original TEXT,                   -- source-language wording
    lang          VARCHAR(8),
    embedding     VECTOR(384) NOT NULL,   -- sole cache key
    first_seen    TIMESTAMPTZ DEFAULT NOW(),
    check_count   INT DEFAULT 1
);
CREATE INDEX ON claims USING hnsw (embedding vector_cosine_ops);

CREATE TABLE verdicts (
    id          BIGSERIAL PRIMARY KEY,
    claim_id    BIGINT REFERENCES claims(id) ON DELETE CASCADE,
    label       VARCHAR(16) NOT NULL
                CHECK (label IN ('genuine','misleading','fake',
                                 'manipulated','insufficient')),
    confidence  REAL NOT NULL,
    explanation TEXT,                     -- nullable: written after verdict
    earliest_url  TEXT,                   -- reverse image search, image path only
    earliest_date TIMESTAMPTZ,            -- drives the `manipulated` label
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON verdicts (claim_id, expires_at DESC);

CREATE TABLE evidence (
    id           BIGSERIAL PRIMARY KEY,
    verdict_id   BIGINT REFERENCES verdicts(id) ON DELETE CASCADE,
    url          TEXT NOT NULL,
    domain       VARCHAR(255),
    title        TEXT,
    snippet      TEXT,
    stance       VARCHAR(16) CHECK (stance IN ('supports','refutes','neutral')),
    stance_score REAL,
    published_at TIMESTAMPTZ
);

CREATE TABLE sources (
    domain            VARCHAR(255) PRIMARY KEY,
    credibility_score REAL NOT NULL,
    category          VARCHAR(32),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
```

**There are no hash columns.** Caching is vector similarity on the text claim only. Do not reintroduce `claim_hash`, `claim_hash_raw`, or `phash`.

**There is no separate image cache and no image embedding model.** Reverse image search results are stored on the verdict row, so a repeated forward hits the text cache and skips the search entirely. Caching images independently would require a CLIP model, a second table, and a second probe, to serve only the narrow case of one image circulating under two different captions. Not worth it in Phase 1.

`claims.text_original` is what the API calls `claim_original`; `claims.text` is what the API calls `claim`. Map accordingly.

`verdicts.explanation` is **nullable**. The verdict row is written at `aggregate` time, when the explanation does not yet exist, because the design requires emitting the verdict before generating it. A `NOT NULL` constraint forces either an insert-then-update dance or a delayed write that blocks the verdict frame.

`verdicts.expires_at` is mandatory. Breaking-news claims get a 6-hour TTL; settled historical claims get 30 days. Expired verdicts must not be served from cache.

**`sources` must be seeded by a migration.** `aggregate` depends on `credibility_score` and will weight every source at zero against an empty table. Seed with: IFCN-signatory Indian fact-checkers (Alt News, BOOM, Factly, Vishvas News, Newschecker) at 0.9; established wire services and national dailies at 0.75–0.85; unrated domains defaulting to 0.4; known low-credibility domains at 0.1. Around 60 rows is enough.

---

## 10. Latency budget

| Stage | Cold | Cache hit |
|---|---|---|
| Capture → bitmap | 80 ms | 80 ms |
| Downscale + JPEG encode | 100 ms | 100 ms |
| Upload (~180 KB) | 200–400 ms | 200–400 ms |
| Vision extraction | 700–1200 ms | 700–1200 ms |
| Embed claim | 20 ms | 20 ms |
| Vector cache probe | 30 ms | 30 ms |
| Fact-check lookup | 150 ms | — |
| Parallel retrieval (incl. reverse image search when present) | 400–2000 ms | — |
| NLI batch, single pass | 200–400 ms | — |
| Aggregation | 5 ms | — |
| **Verdict on bubble, text only** | **1.9–3.2 s** | **1.1–1.8 s** |
| **Verdict on bubble, with image** | **2.5–4.4 s** | **1.1–1.8 s** |
| Explanation streamed after | +1–2 s | cached, instant |

| Requirement | Target |
|---|---|
| Cache hit → verdict | ≤ 1.8 s |
| Cache miss, English → verdict | ≤ 3.0 s |
| Cache miss, translated → verdict | ≤ 3.5 s |
| Cache miss, image path → verdict | ≤ 4.5 s |
| Upload payload | ≤ 200 KB |
| Capture → bitmap | ≤ 150 ms |

**The vision call is now the floor on every request, including cache hits.** This is the direct cost of moving extraction server-side. The cache still eliminates retrieval, NLI, and explanation — roughly 1.5–2 s — so it remains the largest single lever available. It no longer produces a sub-second path.

Latency optimizations that must be implemented:

1. Downscale aggressively before upload (FR-3)
2. Use a fast vision tier, never a flagship model
3. Emit the verdict before the explanation (FR-7)
4. Parallel retrieval via `asyncio.gather` (FR-5)
5. Single batched NLI forward pass (FR-5)
6. Begin capture on `ACTION_DOWN` (FR-2)
7. Keep the WebSocket connection warm while the bubble is active, so no handshake is on the critical path

---

## 11. Hard constraints

Each is a rejection condition.

1. **Do not implement the overlay or capture in React Native.** Kotlin native module only.
2. **Do not create a top-level `/android` directory.** The native module belongs inside the React Native project's existing `android/` tree.
3. **Do not use `AccessibilityService`** for screen reading. Play Store policy restricts it to genuine accessibility use.
4. **Do not add on-device OCR or any ML Kit dependency.** Extraction is server-side, in the vision model.
5. **Do not implement client-side region detection**, selection-tint scanning, or crop heuristics. Upload the whole frame.
6. **Do not hash anything.** No perceptual hashing, no SHA-256 claim hashing, no hash columns. Caching is vector similarity on the text claim only.
6b. **Do not add an image embedding model or image cache table.** Reverse image results live on the verdict row.
7. **Do not build a ReAct or tool-choosing agent.** LangGraph must be a fixed graph with explicit conditional edges.
8. **Do not perform retrieval sequentially.** Use `asyncio.gather`.
9. **Do not load the NLI or embedding models per request.** Load once at application startup.
10. **Do not use an English-only embedding or NLI model.** They fail silently on Indic input rather than erroring.
11. **Do not use `DeBERTa-v3-large`** or a flagship vision tier. Latency is the primary target.
12. **Do not return more than one claim.** `claim` is a string, not an array, everywhere it appears.
13. **Do not block the verdict on the explanation.** Emit `verdict` first, stream `explanation` after.
14. **Do not make `verdicts.explanation` NOT NULL.** It is written after the verdict row exists.
15. **Do not regenerate the explanation on a cache hit.** Serve the persisted one.
16. **Do not omit the `extracted` frame on the cache-hit path.** The Detail screen needs the claim text.
17. **Do not allow uncapped retries.** Maximum one retry on `insufficient`.
18. **Do not let the explanation model introduce facts** absent from the retrieved evidence set. Hallucinated citations are a fatal defect in a fact-checking product.
19. **Do not call reverse image search unless `has_image_content` is true**, and never outside the `retrieve` gather. It is the only metered API in the stack and the slowest single call in the pipeline.
19b. **Do not return a verdict for `no_claim_found`.** It is an error frame.
20. **Do not add authentication, user accounts, or deployment configuration.**
21. **Do not fetch verdict history from the backend.** It is device-local SQLite.
22. **Do not request `POST_NOTIFICATIONS` without an API 33 guard.**
23. **Do not remove `insufficient` as a possible verdict.** Abstention is required behavior, not a gap.
24. **Do not lower the cache similarity threshold below 0.93** to increase hit rate. False cache hits produce confidently wrong verdicts, which is the worst failure this system can have.

---

## 12. Build sequence

Backend first. The overlay is impressive but worthless with nothing behind it, and MediaProjection debugging can silently consume a full day.

| # | Milestone | Independently demoable |
|---|---|---|
| 1 | LangGraph graph, mocked retrieval, hardcoded evidence | via curl |
| 2 | Vision extraction from an uploaded image file | via curl |
| 3 | Postgres schema, `sources` seed migration | via curl |
| 4 | Vector cache probe, check_count | via curl |
| 5 | Real retrieval, NLI, aggregation rules | via curl |
| 6 | Forked multilingual retrieval, localize node | via curl |
| 7 | Kotlin overlay bubble, permissions, foreground service | on device |
| 8 | MediaProjection session and capture | on device |
| 9 | Downscale, encode, upload | on device |
| 10 | WebSocket client, bubble verdict states | end-to-end |
| 11 | RN history (local SQLite) and detail screens | end-to-end |
| 12 | Reverse image search inside the retrieve gather | end-to-end |
| 13 | Demo hardening, cache seeding | — |

Milestones 1–5 constitute a complete, demoable system on their own, driven by uploading screenshot files with curl.

---

## 13. Demo acceptance criteria

The build is done when all of the following hold on a physical Android device:

- [ ] A WhatsApp text forward is verified end-to-end without leaving WhatsApp
- [ ] A Devanagari-script forward returns a verdict, localized back to Hindi
- [ ] A Tamil or Bengali screenshot returns a correct English claim and a verdict
- [ ] A repeated claim returns from cache under 1.8 s with an incremented check count
- [ ] The cache-hit path performs zero retrieval and zero explanation generation, verified in logs
- [ ] The same claim submitted in two different languages resolves to the same cache entry
- [ ] At least one demo claim returns `genuine` with supporting sources
- [ ] At least one demo claim returns `insufficient` and displays that state clearly
- [ ] A screenshot of a personal chat returns `no_claim_found` rather than a verdict
- [ ] An out-of-context image returns `manipulated` with the original publication date shown
- [ ] Evidence cards show source domain, publication date, stance, and a working outbound link
- [ ] A `FLAG_SECURE` app produces the error state rather than a crash or a garbage verdict
- [ ] Upload payloads stay under 200 KB across a range of screenshots

---

## 14. Demo hardening

- **Pre-seed the cache** with 20–30 real WhatsApp forwards you have collected. Those claims return fast and look strong. This is not cheating — it is exactly how the system behaves once a claim has been seen once.
- **Have a `genuine` example ready.** If every demo claim comes back `fake`, a reviewer will assume the verdict is hardcoded.
- **Show `insufficient` deliberately.** A system that admits uncertainty reads as more credible than one that always has an answer.
- **Record a backup video.** Overlay permissions on an unfamiliar device on conference wifi is a genuinely risky live demo.
- **Test on the phone you will demo on.** MediaProjection behaviour varies across OEM skins; MIUI and OneUI both add consent friction.

---

## 15. Known limitations

State these rather than waiting to be asked.

- **The full screenshot is uploaded to the server.** This is a deliberate Phase 1 tradeoff to get correct extraction across every Indian script. It means surrounding private messages leave the device. A production version would need on-device extraction or a consent gate; see section 16.
- **Cache hits no longer produce a sub-second path.** The vision call is on every request. The previous on-device OCR design hit ~400 ms on cache but was limited to Devanagari and Latin scripts and depended on a fragile selection-tint heuristic.
- `FLAG_SECURE` apps cannot be captured at all.
- Only one claim per screenshot is verified. A screenshot containing several distinct claims verifies the most prominent one.
- Claims newer than available reporting correctly return `insufficient`, which resembles failure but is correct behavior.
- Vector-only caching has no exact-match safety net, so the similarity threshold is the sole guard against false hits.
- `AccessibilityService` would produce cleaner text than a screenshot but is ruled out by platform policy.

---

## 16. Deferred to a real product

Not to be built in Phase 1. Listed so the architecture does not foreclose them.

- **On-device extraction as a fast path.** Run local OCR first; fall back to the vision model when OCR is empty or the script is unsupported. Recovers the sub-second cache path and the privacy story without losing language coverage.
- **Pre-upload consent gate** for screenshots that appear to be personal rather than public content.
- Video and audio verification via shared links plus ASR.
- Chrome extension, where DOM text removes the OCR problem entirely.
- iOS via Back Tap Shortcut and Share Extension.
