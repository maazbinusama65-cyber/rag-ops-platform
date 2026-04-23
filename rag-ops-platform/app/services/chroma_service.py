"""
ChromaDB service — handles vector embeddings and semantic search.
"""

import time
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import chroma_vectors_total

logger = get_logger(__name__)


class ChromaService:
    def __init__(self):
        self.client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        """Get or create the runbooks collection."""
        collection = self.client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"✅ ChromaDB collection ready: {settings.CHROMA_COLLECTION}")
        return collection

    def upsert_documents(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> int:
        """Upsert document chunks with their embeddings."""
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        count = self.collection.count()
        chroma_vectors_total.set(count)
        logger.info(f"✅ Upserted {len(ids)} vectors. Total: {count}")
        return count

    def similarity_search(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        where: Optional[dict] = None,
    ) -> dict:
        """
        Perform a cosine similarity search and return results.
        Returns: {ids, documents, metadatas, distances}
        """
        kwargs = dict(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        if where:
            kwargs["where"] = where

        results = self.collection.query(**kwargs)
        return results

    def delete_by_filename(self, filename: str):
        """Delete all chunks associated with a given filename."""
        self.collection.delete(where={"filename": filename})
        count = self.collection.count()
        chroma_vectors_total.set(count)
        logger.info(f"✅ Deleted vectors for {filename}. Total: {count}")

    def get_vector_count(self) -> int:
        count = self.collection.count()
        chroma_vectors_total.set(count)
        return count

    def health_check(self) -> bool:
        try:
            self.client.heartbeat()
            return True
        except Exception:
            return False


# Singleton instance
chroma_service = ChromaService()
