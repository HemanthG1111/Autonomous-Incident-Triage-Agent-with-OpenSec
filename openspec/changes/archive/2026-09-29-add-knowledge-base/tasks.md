# Tasks

## 1. Project Scaffolding

- [x] 1.1 Create `db/migrations/` directory and verify it exists at `incident-agent/db/migrations/`
- [x] 1.2 Create `tests/` directory with an empty `__init__.py` and verify the directory exists

## 2. Requirements File

- [x] 2.1 Create `requirements.txt` with all project dependencies (gradio, fastapi, uvicorn, langgraph, langgraph-checkpoint-postgres, langchain-google-genai, langchain-core, psycopg[binary,pool], python-dotenv, pydantic, pytest) and verify `pip install -r requirements.txt` succeeds in the `.venv`

## 3. Database Migration

- [x] 3.1 Create `db/migrations/001_incident_docs.sql` that: (a) enables `pgvector` extension, (b) creates `incident_docs` table with `id BIGSERIAL PRIMARY KEY`, `content TEXT NOT NULL`, `content_hash TEXT GENERATED ALWAYS AS (encode(sha256(content::bytea),'hex')) STORED UNIQUE`, `metadata JSONB DEFAULT '{}'`, `embedding VECTOR(768)`, (c) creates `match_incident_docs` RPC function using cosine similarity (`<=>`) ordered by similarity descending, filtered by `metadata @> filter` — verify file is valid SQL by visual inspection

## 4. Seed Script

- [x] 4.1 Create `seed_rag.py` that: (a) loads `GEMINI_API_KEY` and `DATABASE_URL` from environment/`.env`, (b) defines `EMBEDDING_MODEL = "models/text-embedding-004"` and `EMBEDDING_DIM = 768` as module-level constants, (c) defines three runbook dicts with `content` and `metadata` fields covering auth 504 timeouts, database high latency, and payment gateway failures, (d) embeds each runbook with `task_type="RETRIEVAL_DOCUMENT"` and `output_dimensionality=768`, (e) inserts via psycopg pool with `prepare_threshold=None` using `ON CONFLICT (content_hash) DO NOTHING`, (f) prints how many rows were inserted vs skipped — verify by running `python seed_rag.py` twice and confirming count stays at 3

## 5. Unit Tests

- [x] 5.1 Create `tests/test_seed_rag.py` with a test that patches the Gemini embeddings client to return a fixed 768-dim zero vector and patches the psycopg pool execute call, then calls the seed function and asserts: (a) embeddings are called with `task_type="RETRIEVAL_DOCUMENT"` and `output_dimensionality=768`, (b) three INSERT statements are issued — verify with `pytest -q tests/test_seed_rag.py` (all pass, no network calls)
- [x] 5.2 Add a test that calls the seed function twice (mocked) and asserts the insert SQL contains `ON CONFLICT (content_hash) DO NOTHING` — verify idempotency is enforced at the SQL level
