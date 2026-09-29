-- Migration: 001_incident_docs.sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create the runbook knowledge base table
CREATE TABLE IF NOT EXISTS incident_docs (
    id          BIGSERIAL PRIMARY KEY,
    content     TEXT NOT NULL,
    content_hash TEXT GENERATED ALWAYS AS (encode(sha256(content::bytea), 'hex')) STORED UNIQUE,
    metadata    JSONB DEFAULT '{}',
    embedding   VECTOR(768),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Index for cosine similarity search (optional but recommended for production)
-- CREATE INDEX ON incident_docs USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- RPC function: semantic search with optional metadata filter
CREATE OR REPLACE FUNCTION match_incident_docs(
    query_embedding VECTOR(768),
    match_count     INT DEFAULT 5,
    filter          JSONB DEFAULT '{}'
)
RETURNS TABLE (
    id          BIGINT,
    content     TEXT,
    metadata    JSONB,
    similarity  FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.content,
        d.metadata,
        1 - (d.embedding <=> query_embedding) AS similarity
    FROM incident_docs d
    WHERE d.metadata @> filter
    ORDER BY d.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
