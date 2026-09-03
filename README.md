# Rifo — Overlay Misinformation Verification System

Backend API for real-time misinformation verification via a floating Android overlay.

## Quick Start

### Prerequisites
- Python 3.11+
- Docker (for PostgreSQL + pgvector)

### Setup

```bash
# 1. Start PostgreSQL with pgvector
docker compose up -d

# 2. Set up Python environment
cd backend
python -m venv venv
.\venv\Scripts\activate    # Windows
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
# Edit .env with your API keys

# 4. Run the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Test with curl

```bash
# Health check
curl http://localhost:8000/health

# Sync verification (POST)
curl -X POST http://localhost:8000/v1/verify \
  -H "Content-Type: application/json" \
  -d '{"image_b64": "dGVzdA==", "device_id": "test-uuid"}'

# Fetch cached claim
curl http://localhost:8000/v1/claim/1

# WebSocket verification (wscat)
wscat -c ws://localhost:8000/v1/verify/stream
> {"image_b64": "dGVzdA==", "device_id": "test-uuid"}
```

## Project Structure

```
/backend                    FastAPI + LangGraph    Python 3.11+
  app/
    main.py                 FastAPI app entry point
    config.py               Pydantic Settings
    models/
      state.py              LangGraph pipeline state
      schemas.py            API request/response models
    graph/
      builder.py            StateGraph construction
      routing.py            Conditional edge functions
      nodes/                Pipeline nodes (10 total)
    services/               External API clients
    db/                     Database CRUD modules
    routes/                 FastAPI route handlers
/db                         SQL migrations
/docs                       Documentation
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| WS | `/v1/verify/stream` | Primary path, progressive frames |
| POST | `/v1/verify` | Sync fallback, full response |
| GET | `/v1/claim/{id}` | Re-fetch cached verdict |
| GET | `/health` | Readiness probe |
