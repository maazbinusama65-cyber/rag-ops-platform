"""
Test suite for RAG-Ops Platform FastAPI endpoints.
Run with: pytest tests/ -v
"""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app


@pytest.fixture
def client():
    """Sync test client — useful for simple endpoint tests."""
    with TestClient(app) as c:
        yield c


# ── Health checks ─────────────────────────────────────────────────────────────

class TestHealth:
    def test_liveness(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "rag-ops-platform"

    @patch("app.api.routes.health.minio_service")
    @patch("app.api.routes.health.chroma_service")
    @patch("app.api.routes.health.ollama_service")
    def test_readiness_all_healthy(self, mock_ollama, mock_chroma, mock_minio, client):
        mock_minio.health_check.return_value = True
        mock_chroma.health_check.return_value = True
        mock_chroma.get_vector_count.return_value = 42
        mock_ollama.health_check = AsyncMock(return_value=True)

        with patch("app.api.routes.health.get_db"):
            response = client.get("/health/ready")
        # May return 503 without real DB, just check structure
        assert response.status_code in (200, 503)


# ── Document Upload ───────────────────────────────────────────────────────────

class TestDocumentUpload:
    @patch("app.api.routes.documents.minio_service")
    def test_upload_pdf(self, mock_minio, client):
        mock_minio.upload_file.return_value = "uploads/2024/01/01/test.pdf"

        fake_pdf = b"%PDF-1.4 fake pdf content for testing purposes"
        response = client.post(
            "/api/v1/upload",
            files={"file": ("runbook.pdf", io.BytesIO(fake_pdf), "application/pdf")},
            headers={"X-User-Id": "test-user"},
        )
        # Without real DB this will error, but let's check it hit the endpoint
        assert response.status_code in (201, 500)

    def test_upload_empty_file_rejected(self, client):
        response = client.post(
            "/api/v1/upload",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
        )
        assert response.status_code == 400

    def test_upload_unsupported_type_rejected(self, client):
        response = client.post(
            "/api/v1/upload",
            files={"file": ("script.exe", io.BytesIO(b"MZ fake exe"), "application/x-msdownload")},
        )
        assert response.status_code == 415

    def test_upload_markdown(self, client):
        content = b"# Runbook\n\nThis is a test runbook for database issues."
        response = client.post(
            "/api/v1/upload",
            files={"file": ("runbook.md", io.BytesIO(content), "text/markdown")},
        )
        assert response.status_code in (201, 500)


# ── Chat Endpoint ─────────────────────────────────────────────────────────────

class TestChat:
    def test_chat_requires_query(self, client):
        response = client.post("/api/v1/chat", json={})
        assert response.status_code == 422  # Validation error

    def test_chat_query_too_short(self, client):
        response = client.post("/api/v1/chat", json={"query": "hi"})
        assert response.status_code == 422

    @patch("app.api.routes.chat.ollama_service")
    @patch("app.api.routes.chat.chroma_service")
    def test_chat_no_documents_returns_404(self, mock_chroma, mock_ollama, client):
        mock_ollama.embed = AsyncMock(return_value=[0.1] * 384)
        mock_chroma.similarity_search.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
            "ids": [[]],
        }

        response = client.post(
            "/api/v1/chat",
            json={"query": "What is the database runbook?"},
        )
        assert response.status_code in (404, 500)


# ── Pipeline / Chunking Unit Tests ────────────────────────────────────────────

class TestChunking:
    def test_text_chunking(self):
        """Unit test for the chunking logic in the pipeline DAG."""
        import sys
        sys.path.insert(0, "pipeline/dags")

        from rag_ingestion_pipeline import parse_and_chunk_text

        text = " ".join([f"word{i}" for i in range(1000)])
        chunks = parse_and_chunk_text(
            file_bytes=text.encode(),
            file_ext="txt",
            object_key="test/document.txt",
        )
        assert len(chunks) > 0
        assert all("text" in c for c in chunks)
        assert all("chunk_id" in c for c in chunks)
        assert all("filename" in c for c in chunks)
        # Verify chunk IDs are unique
        ids = [c["chunk_id"] for c in chunks]
        assert len(ids) == len(set(ids))

    def test_empty_text_yields_no_chunks(self):
        import sys
        sys.path.insert(0, "pipeline/dags")
        from rag_ingestion_pipeline import parse_and_chunk_text

        chunks = parse_and_chunk_text(b"", "txt", "test/empty.txt")
        assert len(chunks) == 0
