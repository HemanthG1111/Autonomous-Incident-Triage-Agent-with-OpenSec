"""seed_rag.py — Idempotently seed the incident_docs runbook knowledge base.

Usage:
    python seed_rag.py

Requires .env with GEMINI_API_KEY and DATABASE_URL.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from psycopg_pool import ConnectionPool

load_dotenv()

EMBEDDING_MODEL = "models/text-embedding-004"
EMBEDDING_DIM = 768

# ── Runbooks ─────────────────────────────────────────────────────────────────

RUNBOOKS: list[dict[str, Any]] = [
    {
        "content": (
            "Auth Service 504 Timeout Runbook\n\n"
            "Symptom: The auth service returns HTTP 504 Gateway Timeout errors.\n\n"
            "Possible causes:\n"
            "  1. Redis session store is unavailable or overloaded.\n"
            "  2. Token-refresh endpoint is blocked by upstream rate limiting.\n"
            "  3. Network latency spike between auth service and database.\n\n"
            "Remediation steps:\n"
            "  1. Check Redis health: `redis-cli ping` — expect PONG.\n"
            "  2. Inspect auth service logs for connection timeout traces.\n"
            "  3. Restart the token-refresh worker pod if idle connections are exhausted.\n"
            "  4. If Redis is down, failover to in-memory session cache (temporary).\n"
            "  5. Page the infra on-call if latency exceeds 5 s for > 2 min.\n"
        ),
        "metadata": {"service": "auth", "severity": "high", "type": "runbook"},
    },
    {
        "content": (
            "Database High Latency Runbook\n\n"
            "Symptom: Query latencies exceed 2 s; connection pool is exhausted.\n\n"
            "Possible causes:\n"
            "  1. Missing or invalidated index on a hot query path.\n"
            "  2. Long-running transaction blocking row locks.\n"
            "  3. Disk I/O saturation on the primary node.\n\n"
            "Remediation steps:\n"
            "  1. Run `SELECT * FROM pg_stat_activity WHERE state = 'active' ORDER BY duration DESC LIMIT 10;`\n"
            "  2. Terminate blocking queries: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE duration > interval '30s';`\n"
            "  3. Check `pg_stat_user_indexes` for sequential-scan hotspots.\n"
            "  4. VACUUM ANALYZE the affected table if bloat is high.\n"
            "  5. Escalate to DBA on-call if primary disk I/O > 90 %.\n"
        ),
        "metadata": {"service": "database", "severity": "high", "type": "runbook"},
    },
    {
        "content": (
            "Payment Gateway Failure Runbook\n\n"
            "Symptom: Payment transactions are failing or returning HTTP 502/503.\n\n"
            "Possible causes:\n"
            "  1. Third-party payment provider outage (check provider status page).\n"
            "  2. Invalid or expired API credentials for the payment gateway.\n"
            "  3. Webhook endpoint is down, causing retries to queue up.\n\n"
            "Remediation steps:\n"
            "  1. Check provider status: https://status.stripe.com (or equivalent).\n"
            "  2. Verify API key rotation: compare key prefix in Secrets Manager vs provider dashboard.\n"
            "  3. Inspect webhook queue depth; drain or pause if > 1000 pending.\n"
            "  4. Enable fallback payment method (manual transfer prompt) if outage > 10 min.\n"
            "  5. Notify finance team and open a P1 ticket if revenue impact is confirmed.\n"
        ),
        "metadata": {"service": "payments", "severity": "critical", "type": "runbook"},
    },
]

# ── Helpers ───────────────────────────────────────────────────────────────────


def get_embeddings_client() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        google_api_key=os.environ["GEMINI_API_KEY"],
        task_type="RETRIEVAL_DOCUMENT",
    )


def embed_runbooks(
    runbooks: list[dict[str, Any]],
    embeddings: GoogleGenerativeAIEmbeddings,
) -> list[dict[str, Any]]:
    """Return runbooks enriched with an 'embedding' key."""
    texts = [r["content"] for r in runbooks]
    vectors = embeddings.embed_documents(
        texts, output_dimensionality=EMBEDDING_DIM
    )
    return [dict(r, embedding=v) for r, v in zip(runbooks, vectors)]


INSERT_SQL = """
INSERT INTO incident_docs (content, metadata, embedding)
VALUES (%s, %s::jsonb, %s::vector)
ON CONFLICT (content_hash) DO NOTHING
RETURNING id
"""


def seed(
    runbooks: list[dict[str, Any]] | None = None,
    *,
    database_url: str | None = None,
    embeddings_client: GoogleGenerativeAIEmbeddings | None = None,
) -> dict[str, int]:
    """Seed the knowledge base. Returns {'inserted': N, 'skipped': N}."""
    if runbooks is None:
        runbooks = RUNBOOKS
    if database_url is None:
        database_url = os.environ["DATABASE_URL"]
    if embeddings_client is None:
        embeddings_client = get_embeddings_client()

    enriched = embed_runbooks(runbooks, embeddings_client)

    inserted = skipped = 0
    pool_kwargs = {"prepare_threshold": None}  # required for Supabase transaction pooler

    with ConnectionPool(
        database_url, min_size=1, max_size=2, kwargs=pool_kwargs
    ) as pool:
        with pool.connection() as conn:
            for row in enriched:
                result = conn.execute(
                    INSERT_SQL,
                    (row["content"], __import__("json").dumps(row["metadata"]), row["embedding"]),
                )
                if result.rowcount:
                    inserted += 1
                else:
                    skipped += 1

    return {"inserted": inserted, "skipped": skipped}


if __name__ == "__main__":
    result = seed()
    print(
        f"Seeding complete — inserted: {result['inserted']}, "
        f"skipped (already existed): {result['skipped']}"
    )
