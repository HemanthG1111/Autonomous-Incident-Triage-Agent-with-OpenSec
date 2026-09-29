# Design

## Context

See `proposal.md → Why` for motivation. The agent requires a pgvector store to perform
semantic similarity search over runbooks. Supabase provides managed Postgres + pgvector on
the free tier. The transaction pooler (port 6543) is used because the direct connection
limit on the free tier is too low for concurrent use; the pooler multiplexes connections.

## Goals / Non-Goals

**Goals:**
- A `incident_docs` table with pgvector support (768-dim cosine similarity).
- An RPC function `match_incident_docs` callable via Supabase client or raw SQL.
- Idempotent `seed_rag.py` that loads three canonical runbooks on first run and is safe to re-run.
- Full project `requirements.txt` so downstream changes can `pip install -r requirements.txt` without additions.

**Non-Goals:**
- Dynamic runbook ingestion from files (future change).
- Authentication / row-level security on `incident_docs` (not in scope for free tier MVP).
- Automatic migration execution (manual Supabase SQL Editor run is acceptable for now).

## Decisions

### D1 — Idempotency via content-hash unique constraint

**Decision:** Add a `UNIQUE` constraint on `sha256(content)` stored as a generated column (`content_hash`), and use `ON CONFLICT DO NOTHING` in the seed insert.

**Alternatives considered:**
- *Check by title string* — fragile if the title changes; a hash is content-stable.
- *DELETE + re-insert* — destructive; would change row IDs and break cached queries.
- *Check row count* — would fail if partial seeding had occurred.

### D2 — Transaction pooler with `prepare_threshold=None`

**Decision:** Pass `prepare_threshold=None` in `psycopg_pool.ConnectionPool` kwargs.

**Reason:** The Supabase transaction pooler (PgBouncer in transaction mode) does not support
named prepared statements. Without this setting, `psycopg` v3 auto-prepares statements after
the first execution, which causes `prepared statement already exists` errors on subsequent
connections. This is the most common Supabase gotcha with psycopg v3.

**Alternatives considered:**
- *Async pool* — not needed for the seed script, which is synchronous.
- *asyncpg* — different library, would require different driver everywhere.

### D3 — Gemini embedding model and dimensions

**Decision:** Use `models/text-embedding-004` (current free-tier embedding model in Google AI Studio) with `output_dimensionality=768`. Store dimension in a single constant `EMBEDDING_DIM = 768`.

**Reason:** 768 is the recommended output size for this model; it balances recall quality and storage cost. The vector column is declared as `vector(768)` in the migration so mismatches are caught at insert time.

**Free-tier note:** Gemini Embeddings API on AI Studio allows up to 1 500 req/min. The three-runbook seed script stays well inside this limit.

### D4 — RPC function vs. direct SQL in application code

**Decision:** Create a `match_incident_docs` PL/pgSQL function in the migration, callable via raw SQL (`SELECT * FROM match_incident_docs(...)`).

**Reason:** Keeps the cosine-similarity query logic colocated with the schema; the agent code stays readable and the function can be improved (adding IVFFlat index later) without changing Python.

**Alternatives considered:**
- *Application-level SQL string* — leaks query details into Python; harder to tune.
- *Supabase JS client RPC* — not applicable; agent is Python.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Gemini model name changes (free tier models rotate) | `seed_rag.py` and `agent.py` read `EMBEDDING_MODEL` from a constant; update one place |
| Supabase free-tier pauses the project after 7 days of inactivity | Wake it manually before demo; state is preserved |
| `pgvector` extension not available on older Supabase projects | Migration includes `CREATE EXTENSION IF NOT EXISTS vector` |
| Transaction pooler rejects prepared statements | `prepare_threshold=None` in all pool configurations (D2) |

## Migration Plan

1. Developer runs `db/migrations/001_incident_docs.sql` in the Supabase SQL Editor.
2. Developer runs `python seed_rag.py` (with `.env` populated) to load runbooks.
3. Verify: Supabase Table Editor → `incident_docs` → confirm 3 rows.

**Rollback:** In Supabase SQL Editor:
```sql
DROP FUNCTION IF EXISTS match_incident_docs;
DROP TABLE IF EXISTS incident_docs;
DROP EXTENSION IF EXISTS vector;
```
Then delete `seed_rag.py` and revert `requirements.txt`.
