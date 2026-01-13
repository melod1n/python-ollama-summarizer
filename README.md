# Ollama Article Summarizer (FastAPI)

A small FastAPI service that **summarizes web articles** and generates **high-level topic tags** using a locally running LLM via **Ollama**.

It works like this:

1. Accepts an article **URL**
2. Downloads HTML and extracts the main readable content (`readability-lxml`)
3. Runs a quick heuristic “is this an article?” check (and optionally an LLM check)
4. If the prompt would be too large, **chunks** the text using `tiktoken`
5. Calls **Ollama** (`/api/generate`) to produce JSON: `{ "summary": "...", "tags": ["..."] }`
6. Stores results in **SQLite** and provides polling via `/status/{request_id}`

---

## Features

- ✅ FastAPI + OpenAPI docs (`/docs`)
- ✅ Article extraction (Readability) + HTML → text cleanup
- ✅ Token-based chunking with overlap for long articles
- ✅ Tag normalization + tag re-filtering via LLM (≤ 10 tags)
- ✅ Simple in-memory queue with max size (`MAX_QUEUE_SIZE`)
- ✅ SQLite persistence (`summaries.db`)
- ✅ Logs to console + rotating log file

---

## Requirements

- **Python 3.12+** recommended (Docker image uses Python 3.12)
- A running **Ollama** instance and at least one pulled model

> Note about Python 3.13: some environments may have trouble installing `uvicorn[standard]` due to optional speedups (e.g. `httptools`). If you hit install errors, use `uvicorn` without `[standard]` and add `watchfiles` for reload.

---

## Quick start (local)

### 1) Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

### 2) Configure environment

Create a `.env` file in the project root:

```env
# Ollama
OLLAMA_API_URL=http://localhost:11434/api/generate
MODEL_NAME=mistral

# Summarization
MAX_TOKENS=6000
MAX_QUEUE_SIZE=5
CHUNK_MAX_TOKENS=1500
CHUNK_OVERLAP=200

# Optional overrides
# DB_PATH=./summaries.db
# LOG_PATH=./summary.log
```

### 3) Start Ollama and pull a model

```bash
ollama serve
ollama pull mistral
```

### 4) Run the API

```bash
uvicorn main:app --reload
```

Open:
- Swagger UI: `http://localhost:8000/docs`

---

## Quick start (Docker)

Build:

```bash
docker build -t ollama-summarizer .
```

Run (persist DB + logs to local folders):

```bash
docker run --rm -p 8000:8000 \
  -e IN_DOCKER=true \
  -e MODEL_NAME=mistral \
  -e OLLAMA_API_URL=http://host.docker.internal:11434/api/generate \
  -v "$(pwd)/db:/db" \
  -v "$(pwd)/logs:/logs" \
  ollama-summarizer
```

Notes:
- On **macOS/Windows**, `host.docker.internal` usually works.
- On **Linux**, you can use `--network host` or set `OLLAMA_API_URL` to your host IP.

---

## API

### `POST /summarize`

Queues a new summarization job and returns a `request_id`.

Request:

```json
{ "url": "https://example.com/some-article" }
```

Response (`202 Accepted`):

```json
{ "request_id": "0b4e0d0f-2b9d-4c7a-9b45-9b9f8c9c8e31" }
```

### `GET /status/{request_id}`

Poll job status.

Response examples:

**In progress**
```json
{ "status": "in_progress" }
```

**Success**
```json
{
  "status": "success",
  "result": {
    "url": "https://example.com/some-article",
    "summary": "One-sentence topic-style summary.",
    "tags": ["ai", "web", "software-engineering"],
    "chunks": 3
  }
}
```

**Failure**
```json
{ "status": "failure", "error": "..." }
```

---

## Configuration

All settings are configured via environment variables (see `app/core/config.py`).

| Variable | Default | Description |
|---|---:|---|
| `OLLAMA_API_URL` | `http://localhost:11434/api/generate` | Ollama generate endpoint |
| `MODEL_NAME` | `mistral` | Ollama model name |
| `MAX_TOKENS` | `6000` | Max prompt tokens before chunking |
| `MAX_QUEUE_SIZE` | `5` | Max number of in-flight jobs |
| `CHUNK_MAX_TOKENS` | `1500` | Chunk size (tokens) |
| `CHUNK_OVERLAP` | `200` | Chunk overlap (tokens) |
| `IN_DOCKER` | `false` | Enables default `/db` and `/logs` paths |
| `DB_PATH` | *(auto)* | Override DB file path |
| `LOG_PATH` | *(auto)* | Override log file path |

Paths:
- Local defaults: `app/summaries.db`, `app/summary.log`
- Docker defaults: `/db/summaries.db`, `/logs/summary.log`

---

## Project structure

```
.
├── app/
│   ├── api/               # FastAPI routes
│   ├── core/              # config + logging + runtime globals
│   ├── db/                # SQLAlchemy async engine + models
│   ├── schemas/           # Pydantic models
│   └── services/          # chunking + ollama + summarize pipeline
├── main.py                # FastAPI app + lifespan startup
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## Notes / limitations

- The queue and job status are **in-memory** (reset on server restart). The final result is still stored in SQLite.
- The worker uses a **thread per request** and runs blocking HTTP calls to fetch pages / call Ollama.
- This project is intended to run with **a single process** (one Uvicorn worker). Multiple workers won’t share the in-memory queue.
- Some websites block bots; you may need to adjust the `User-Agent` header.

---

## License

See `LICENSE`.
