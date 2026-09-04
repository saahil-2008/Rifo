# Rifo — Chrome Extension Misinformation Verifier

Real-time claim verification via a Chrome extension (MV3). Right-click any
text or image on any page — including WhatsApp Web — to fact-check it through
the Rifo LangGraph pipeline.

## Quick Start

### Prerequisites
- Python 3.11+
- Docker (for PostgreSQL + pgvector)
- Google Chrome (or any Chromium browser supporting MV3 extensions)

### 1 — Start the backend

```bash
# Start PostgreSQL with pgvector
docker compose up -d

# Set up Python environment
cd backend
python -m venv venv
.\venv\Scripts\activate    # Windows
# source venv/bin/activate # macOS / Linux
pip install -r requirements.txt

# Configure environment
copy .env.example .env
# Edit .env with your API keys (GEMINI_API_KEY is required for image verification)

# Run the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2 — Load the extension (load-unpacked)

1. Open **chrome://extensions** in Chrome.
2. Enable **Developer mode** (toggle in the top-right corner).
3. Click **Load unpacked**.
4. Select the `extension/` folder inside this repository.
5. The Rifo icon appears in the Chrome toolbar.

### 3 — Verify a claim

**Text:** Select any text on a web page → right-click → **"Verify this claim"**.

**Image:** Right-click any image → **"Verify this image"**.

A floating card appears near your selection and streams the verdict, evidence,
and explanation as they arrive. Press **Escape** or click outside to dismiss.

### Test with curl / wscat

```bash
# Health check
curl http://localhost:8000/health

# WebSocket — text claim (skips vision model, fastest path)
wscat -c ws://localhost:8000/v1/verify/stream
> {"type":"text","content":"Amitabh Bachchan has died","device_id":"test-uuid"}

# WebSocket — image URL (server fetches and runs vision extraction)
wscat -c ws://localhost:8000/v1/verify/stream
> {"type":"image","image_url":"https://example.com/image.jpg","device_id":"test-uuid"}

# Legacy image_b64 (still supported for backward compatibility)
wscat -c ws://localhost:8000/v1/verify/stream
> {"image_b64":"dGVzdA==","device_id":"test-uuid"}
```

## Project Structure

```
/backend                    FastAPI + LangGraph    Python 3.11+
  app/
    main.py                 FastAPI app entry point
    config.py               Pydantic Settings
    models/
      state.py              LangGraph pipeline state
      schemas.py            API request/response models (VerifyRequest + ExtensionRequest)
    graph/
      builder.py            StateGraph construction
      routing.py            Conditional edge functions
      nodes/                Pipeline nodes (9 total)
    services/               External API clients
    db/                     Database CRUD modules
    routes/                 FastAPI route handlers

/extension                  Chrome Extension (MV3)   Plain JS, no bundler
  manifest.json             MV3 manifest
  background.js             Service worker — context menu + WebSocket owner
  content.js                Injected into pages — Shadow DOM verdict card
  icons/                    16 / 48 / 128 px PNGs

/db                         SQL migrations
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| WS | `/v1/verify/stream` | Primary path, progressive frames |
| POST | `/v1/verify` | Sync fallback, full response |
| GET | `/v1/claim/{id}` | Re-fetch cached verdict |
| GET | `/health` | Readiness probe |

### WebSocket request shapes

| Shape | When |
|---|---|
| `{"type":"text","content":"...","device_id":"..."}` | Extension text selection |
| `{"type":"image","image_url":"...","device_id":"..."}` | Extension image right-click |
| `{"image_b64":"...","device_id":"..."}` | Legacy (curl / wscat tests) |

Text requests skip `vision_extract` and enter the pipeline at `embed_claim`,
making them the fastest path (no vision API call, no OCR).

