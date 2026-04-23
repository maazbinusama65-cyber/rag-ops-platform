"""
Health check endpoints for Kubernetes liveness/readiness probes
and dependency status monitoring.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.services.chroma_service import chroma_service
from app.services.minio_service import minio_service
from app.services.ollama_service import ollama_service

logger = get_logger(__name__)
router = APIRouter()


@router.get("/health", summary="Liveness probe")
async def liveness():
    """Kubernetes liveness probe — confirms the app is running."""
    return {"status": "ok", "service": "rag-ops-platform"}


@router.get("/health/ready", summary="Readiness probe")
async def readiness(db: AsyncSession = Depends(get_db)):
    """
    Kubernetes readiness probe — checks all downstream dependencies.
    Returns 503 if any critical dependency is unavailable.
    """
    checks = {}
    all_healthy = True

    # PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
        checks["postgresql"] = "ok"
    except Exception as e:
        checks["postgresql"] = f"error: {str(e)}"
        all_healthy = False

    # MinIO
    checks["minio"] = "ok" if minio_service.health_check() else "error"
    if checks["minio"] != "ok":
        all_healthy = False

    # ChromaDB
    checks["chromadb"] = "ok" if chroma_service.health_check() else "error"
    if checks["chromadb"] != "ok":
        all_healthy = False

    # Ollama (non-critical — degrades gracefully)
    checks["ollama"] = "ok" if await ollama_service.health_check() else "degraded"

    status_code = 200 if all_healthy else 503
    return {
        "status": "ready" if all_healthy else "degraded",
        "checks": checks,
        "vector_count": chroma_service.get_vector_count() if checks["chromadb"] == "ok" else -1,
    }
