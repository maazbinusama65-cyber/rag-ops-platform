"""
RAG Chat endpoint.
POST /api/v1/chat — performs vector similarity search + LLM generation with full audit logging.
"""

import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.metrics import (
    active_requests,
    llm_generation_latency,
    queries_total,
    rag_retrieval_latency,
)
from app.models.audit import ChatLog
from app.services.chroma_service import chroma_service
from app.services.ollama_service import ollama_service

logger = get_logger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000, description="The user's question")
    session_id: Optional[str] = Field(None, description="Optional session ID for conversation tracking")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of context documents to retrieve")
    stream: bool = Field(default=False, description="Whether to stream the response")


class ChatResponse(BaseModel):
    log_id: str
    query: str
    answer: str
    retrieved_documents: list[dict]
    retrieval_latency_ms: float
    generation_latency_ms: float
    total_latency_ms: float
    model_used: str


@router.post("/chat")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    x_user_id: str = Header(default="anonymous"),
):
    """
    Query the knowledge base using RAG:

    1. Log incoming query to PostgreSQL
    2. Embed the query using Ollama
    3. Retrieve top-K similar chunks from ChromaDB
    4. Generate an answer using Ollama + retrieved context
    5. Update PostgreSQL log with answer, latencies, and retrieved doc IDs

    Supports both regular JSON and streaming (SSE) responses.
    """
    log_id = str(uuid.uuid4())
    total_start = time.time()
    active_requests.inc()

    # ── Step 1: Create initial audit log entry ─────────────────────────────
    chat_log = ChatLog(
        id=uuid.UUID(log_id),
        session_id=request.session_id,
        user_id=x_user_id,
        query=request.query,
        status="pending",
        model_used=settings.OLLAMA_MODEL,
    )
    db.add(chat_log)
    await db.flush()

    try:
        # ── Step 2: Embed the query ───────────────────────────────────────
        query_embedding = await ollama_service.embed(request.query)

        # ── Step 3: Vector similarity search in ChromaDB ─────────────────
        retrieval_start = time.time()
        results = chroma_service.similarity_search(
            query_embedding=query_embedding,
            n_results=request.top_k,
        )
        retrieval_ms = (time.time() - retrieval_start) * 1000

        # Record retrieval latency metric
        rag_retrieval_latency.observe(retrieval_ms / 1000)

        # Extract context documents
        docs = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        ids = results.get("ids", [[]])[0]

        if not docs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No relevant documents found in the knowledge base. Please upload relevant runbooks first.",
            )

        retrieved_docs_info = [
            {
                "id": doc_id,
                "filename": meta.get("filename", "unknown"),
                "page": meta.get("page_number", 0),
                "chunk": meta.get("chunk_index", 0),
                "relevance_score": round(1 - dist, 4),
                "preview": doc[:200] + "..." if len(doc) > 200 else doc,
            }
            for doc_id, meta, dist, doc in zip(ids, metadatas, distances, docs)
        ]

        # ── Step 4: Stream or generate response ───────────────────────────
        if request.stream:
            return _stream_response(
                request=request,
                docs=docs,
                log_id=log_id,
                chat_log=chat_log,
                db=db,
                retrieval_ms=retrieval_ms,
                retrieved_docs_info=retrieved_docs_info,
                total_start=total_start,
                x_user_id=x_user_id,
            )

        # Non-streaming generation
        generation_start = time.time()
        answer = await ollama_service.generate(
            prompt=request.query,
            context_docs=docs,
        )
        generation_ms = (time.time() - generation_start) * 1000
        total_ms = (time.time() - total_start) * 1000

        # Record generation latency metric
        llm_generation_latency.observe(generation_ms / 1000)

        # ── Step 5: Update audit log ───────────────────────────────────────
        chat_log.answer = answer
        chat_log.retrieved_doc_ids = ids
        chat_log.retrieved_doc_names = [m.get("filename", "unknown") for m in metadatas]
        chat_log.retrieval_latency_ms = round(retrieval_ms, 2)
        chat_log.generation_latency_ms = round(generation_ms, 2)
        chat_log.total_latency_ms = round(total_ms, 2)
        chat_log.status = "success"
        await db.flush()

        queries_total.labels(status="success").inc()
        active_requests.dec()

        logger.info(
            f"💬 Chat query | user={x_user_id} | retrieval={retrieval_ms:.0f}ms "
            f"| generation={generation_ms:.0f}ms | docs={len(docs)}"
        )

        return ChatResponse(
            log_id=log_id,
            query=request.query,
            answer=answer,
            retrieved_documents=retrieved_docs_info,
            retrieval_latency_ms=round(retrieval_ms, 2),
            generation_latency_ms=round(generation_ms, 2),
            total_latency_ms=round(total_ms, 2),
            model_used=settings.OLLAMA_MODEL,
        )

    except HTTPException:
        chat_log.status = "error"
        chat_log.error_message = "No documents found"
        queries_total.labels(status="error").inc()
        active_requests.dec()
        raise
    except Exception as e:
        chat_log.status = "error"
        chat_log.error_message = str(e)
        await db.flush()
        queries_total.labels(status="error").inc()
        active_requests.dec()
        logger.error(f"❌ Chat query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query processing failed: {str(e)}")


async def _stream_response(
    request, docs, log_id, chat_log, db, retrieval_ms, retrieved_docs_info, total_start, x_user_id
):
    """Returns a Server-Sent Events streaming response."""
    import json

    async def event_generator():
        full_answer = []
        generation_start = time.time()

        # Send metadata first
        yield f"data: {json.dumps({'type': 'metadata', 'log_id': log_id, 'retrieved_documents': retrieved_docs_info})}\n\n"

        async for token in ollama_service.generate_stream(
            prompt=request.query, context_docs=docs
        ):
            full_answer.append(token)
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

        generation_ms = (time.time() - generation_start) * 1000
        total_ms = (time.time() - total_start) * 1000
        answer = "".join(full_answer)

        # Update audit log
        chat_log.answer = answer
        chat_log.retrieval_latency_ms = round(retrieval_ms, 2)
        chat_log.generation_latency_ms = round(generation_ms, 2)
        chat_log.total_latency_ms = round(total_ms, 2)
        chat_log.status = "success"
        await db.flush()
        await db.commit()

        llm_generation_latency.observe(generation_ms / 1000)
        queries_total.labels(status="success").inc()
        active_requests.dec()

        yield f"data: {json.dumps({'type': 'done', 'generation_latency_ms': round(generation_ms, 2), 'total_latency_ms': round(total_ms, 2)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"X-Log-ID": log_id},
    )
