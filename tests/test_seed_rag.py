"""tests/test_seed_rag.py — Unit tests for seed_rag.py.

All tests are offline: no Gemini API calls, no database connections.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import pytest

import seed_rag


# ── Helpers ───────────────────────────────────────────────────────────────────

FAKE_VECTOR = [0.0] * seed_rag.EMBEDDING_DIM


def make_mock_embeddings(vector: list[float] | None = None) -> MagicMock:
    """Return a mock GoogleGenerativeAIEmbeddings."""
    mock = MagicMock()
    v = vector if vector is not None else FAKE_VECTOR
    # embed_documents returns a list of vectors, one per document
    mock.embed_documents.return_value = [v] * len(seed_rag.RUNBOOKS)
    return mock


def make_mock_pool_ctx(rowcounts: list[int]) -> tuple[MagicMock, MagicMock]:
    """
    Return (mock_pool_instance, mock_conn) where mock_conn.execute returns
    successive result objects with the given rowcounts.
    """
    results = [MagicMock(rowcount=rc) for rc in rowcounts]

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = results

    mock_pool = MagicMock()
    mock_pool.__enter__.return_value = mock_pool
    mock_pool.connection.return_value.__enter__.return_value = mock_conn

    return mock_pool, mock_conn


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestEmbedding:
    """Verify embed_runbooks calls the client with correct parameters."""

    def test_embed_documents_called_with_retrieval_document_task_type(self):
        """Spec: seed uses task_type='RETRIEVAL_DOCUMENT' and output_dimensionality=768."""
        mock_emb = make_mock_embeddings()
        result = seed_rag.embed_runbooks(seed_rag.RUNBOOKS, mock_emb)

        # Should be called exactly once with all texts
        mock_emb.embed_documents.assert_called_once()
        call_args = mock_emb.embed_documents.call_args

        # First positional arg: list of texts
        texts = call_args.args[0] if call_args.args else call_args.kwargs.get("texts", [])
        assert len(texts) == len(seed_rag.RUNBOOKS)

        # output_dimensionality keyword
        assert call_args.kwargs.get("output_dimensionality") == seed_rag.EMBEDDING_DIM

    def test_embed_runbooks_returns_enriched_dicts(self):
        """Each returned dict has an 'embedding' key matching the mock vector."""
        mock_emb = make_mock_embeddings()
        result = seed_rag.embed_runbooks(seed_rag.RUNBOOKS, mock_emb)

        assert len(result) == len(seed_rag.RUNBOOKS)
        for item in result:
            assert "embedding" in item
            assert item["embedding"] == FAKE_VECTOR


class TestSeedIdempotency:
    """Verify INSERT uses ON CONFLICT DO NOTHING and reports skipped rows correctly."""

    @patch("seed_rag.ConnectionPool")
    def test_all_inserted_on_first_run(self, mock_pool_cls):
        """Three runbooks → three inserts → inserted=3, skipped=0."""
        mock_pool_cls_instance, mock_conn = make_mock_pool_ctx([1, 1, 1])
        mock_pool_cls.return_value = mock_pool_cls_instance

        mock_emb = make_mock_embeddings()
        result = seed_rag.seed(
            database_url="postgresql://fake/db",
            embeddings_client=mock_emb,
        )

        assert result["inserted"] == 3
        assert result["skipped"] == 0

    @patch("seed_rag.ConnectionPool")
    def test_all_skipped_on_second_run(self, mock_pool_cls):
        """rowcount=0 for all three → inserted=0, skipped=3 (idempotency)."""
        mock_pool_cls_instance, mock_conn = make_mock_pool_ctx([0, 0, 0])
        mock_pool_cls.return_value = mock_pool_cls_instance

        mock_emb = make_mock_embeddings()
        result = seed_rag.seed(
            database_url="postgresql://fake/db",
            embeddings_client=mock_emb,
        )

        assert result["inserted"] == 0
        assert result["skipped"] == 3

    @patch("seed_rag.ConnectionPool")
    def test_insert_sql_contains_on_conflict_clause(self, mock_pool_cls):
        """SQL uses ON CONFLICT (content_hash) DO NOTHING for idempotency."""
        assert "ON CONFLICT (content_hash) DO NOTHING" in seed_rag.INSERT_SQL

    @patch("seed_rag.ConnectionPool")
    def test_pool_uses_prepare_threshold_none(self, mock_pool_cls):
        """Pool must be created with prepare_threshold=None for Supabase pooler."""
        mock_pool_cls_instance, _ = make_mock_pool_ctx([1, 1, 1])
        mock_pool_cls.return_value = mock_pool_cls_instance

        mock_emb = make_mock_embeddings()
        seed_rag.seed(database_url="postgresql://fake/db", embeddings_client=mock_emb)

        call_kwargs = mock_pool_cls.call_args.kwargs
        assert call_kwargs.get("kwargs", {}).get("prepare_threshold") is None
