# Proposal

## Why

The Autonomous Incident Triage Agent needs a searchable store of remediation runbooks so it can
look up relevant steps when an engineer reports an incident. Without a knowledge base, the agent
has nothing to search; this is the foundational layer every other capability depends on.

## What Changes

- New SQL migration `db/migrations/001_incident_docs.sql`:
  - Enables the `pgvector` extension.
  - Creates `incident_docs` table (columns: `id`, `content text`, `metadata jsonb`, `embedding vector(768)`).
  - Creates `match_incident_docs(query_embedding vector, match_count int, filter jsonb)` RPC function using cosine similarity.
- New `requirements.txt` covering the full project runtime (gradio, fastapi, uvicorn, langgraph, langgraph-checkpoint-postgres, langchain-google-genai, langchain-core, psycopg[binary,pool], python-dotenv, pydantic, pytest).
- New `seed_rag.py`:
  - Embeds three sample runbooks (auth 504 timeouts, database high latency, payment gateway failures) using Gemini embeddings (`RETRIEVAL_DOCUMENT`, 768 dims).
  - Inserts via the Supabase transaction pooler (`prepare_threshold=None`).
  - Idempotent: re-running does not create duplicate rows.
- Unit tests in `tests/test_seed_rag.py` mocking the embeddings client and DB connection.

## Capabilities

### New Capabilities

- `knowledge-base`: Runbook storage, idempotent seeding, and semantic retrieval via pgvector cosine similarity.

### Modified Capabilities

_(none)_

## Impact

- **New files**: `db/migrations/001_incident_docs.sql`, `requirements.txt`, `seed_rag.py`, `tests/test_seed_rag.py`.
- **Dependencies**: `psycopg[binary,pool]`, `langchain-google-genai`, `python-dotenv`.
- **Manual step**: Migration must be run in Supabase SQL Editor by the developer (not automated).
- **Rollback**: Drop the `incident_docs` table and `match_incident_docs` function in Supabase SQL Editor. Delete `seed_rag.py` and revert `requirements.txt`.
