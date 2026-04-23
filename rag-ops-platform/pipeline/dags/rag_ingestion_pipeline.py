"""
RAG-Ops Ingestion Pipeline DAG
================================
Event-driven pipeline that processes new files from MinIO:
  1. Extract  — Download raw file from MinIO
  2. Transform — Parse text, split into chunks
  3. Embed    — Generate vector embeddings via Ollama
  4. Load     — Upsert vectors into ChromaDB

Triggered by MinIO event sensor or on schedule as fallback.
"""

import hashlib
import io
import logging
import os
import uuid
from datetime import datetime, timedelta

import chromadb
import httpx
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from minio import Minio

logger = logging.getLogger(__name__)

# ── Config from Airflow Variables (or env) ───────────────────────────────────
MINIO_ENDPOINT = Variable.get("MINIO_ENDPOINT", default_var=os.getenv("MINIO_ENDPOINT", "minio:9000"))
MINIO_ACCESS_KEY = Variable.get("MINIO_ACCESS_KEY", default_var="minioadmin")
MINIO_SECRET_KEY = Variable.get("MINIO_SECRET_KEY", default_var="minioadmin")
MINIO_BUCKET = Variable.get("MINIO_BUCKET", default_var="runbooks")

CHROMA_HOST = Variable.get("CHROMA_HOST", default_var="chromadb")
CHROMA_PORT = int(Variable.get("CHROMA_PORT", default_var="8000"))
CHROMA_COLLECTION = Variable.get("CHROMA_COLLECTION", default_var="runbooks")

OLLAMA_BASE_URL = Variable.get("OLLAMA_BASE_URL", default_var="http://ollama:11434")
OLLAMA_EMBED_MODEL = Variable.get("OLLAMA_EMBED_MODEL", default_var="nomic-embed-text")

CHUNK_SIZE = int(Variable.get("CHUNK_SIZE", default_var="500"))
CHUNK_OVERLAP = int(Variable.get("CHUNK_OVERLAP", default_var="50"))

# ── Default DAG args ──────────────────────────────────────────────────────────
default_args = {
    "owner": "rag-ops",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
}


# ─────────────────────────────────────────────────────────────────────────────
# Task functions
# ─────────────────────────────────────────────────────────────────────────────

def discover_unprocessed_files(**context) -> list[str]:
    """
    Scans MinIO for files in the uploads/ prefix that haven't been embedded yet.
    Returns a list of object keys to process.
    """
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )

    chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    collection = chroma_client.get_or_create_collection(CHROMA_COLLECTION)

    # Get all existing filenames in ChromaDB
    existing = set()
    try:
        results = collection.get(include=["metadatas"])
        for meta in results.get("metadatas", []):
            if meta and "filename" in meta:
                existing.add(meta["filename"])
    except Exception:
        pass

    # Find files in MinIO not yet processed
    unprocessed = []
    objects = client.list_objects(MINIO_BUCKET, prefix="uploads/", recursive=True)
    for obj in objects:
        if obj.object_name not in existing:
            unprocessed.append(obj.object_name)

    logger.info(f"🔍 Found {len(unprocessed)} unprocessed files")
    context["ti"].xcom_push(key="files_to_process", value=unprocessed)
    return unprocessed


def extract_file(object_key: str, **context) -> dict:
    """Download a file from MinIO and return its raw bytes + metadata."""
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )

    response = client.get_object(MINIO_BUCKET, object_key)
    file_bytes = response.read()
    response.close()
    response.release_conn()

    file_ext = object_key.split(".")[-1].lower()
    logger.info(f"📥 Extracted {object_key} ({len(file_bytes)} bytes)")

    return {
        "object_key": object_key,
        "file_bytes": file_bytes,
        "file_ext": file_ext,
        "file_size": len(file_bytes),
    }


def parse_and_chunk_text(file_bytes: bytes, file_ext: str, object_key: str) -> list[dict]:
    """
    Parse the file and split into overlapping chunks.
    Returns list of {text, page_number, chunk_index, chunk_id}.
    """
    raw_text = ""

    if file_ext == "pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                pages.append((i + 1, text))
        except Exception as e:
            logger.warning(f"pypdf failed, falling back to raw text: {e}")
            pages = [(1, file_bytes.decode("utf-8", errors="ignore"))]
    else:
        # Markdown / TXT
        pages = [(1, file_bytes.decode("utf-8", errors="ignore"))]

    chunks = []
    for page_num, page_text in pages:
        # Simple word-based chunking with overlap
        words = page_text.split()
        if not words:
            continue

        start = 0
        chunk_idx = 0
        while start < len(words):
            end = start + CHUNK_SIZE
            chunk_words = words[start:end]
            chunk_text = " ".join(chunk_words).strip()

            if len(chunk_text) < 50:
                start += CHUNK_SIZE - CHUNK_OVERLAP
                continue

            # Deterministic chunk ID based on content
            chunk_hash = hashlib.md5(f"{object_key}:{page_num}:{chunk_idx}".encode()).hexdigest()

            chunks.append({
                "chunk_id": f"chunk_{chunk_hash}",
                "text": chunk_text,
                "page_number": page_num,
                "chunk_index": chunk_idx,
                "filename": object_key,
                "word_count": len(chunk_words),
            })

            chunk_idx += 1
            start += CHUNK_SIZE - CHUNK_OVERLAP

    logger.info(f"✂️  Split {object_key} into {len(chunks)} chunks")
    return chunks


def embed_chunks(chunks: list[dict]) -> list[dict]:
    """Generate embeddings for each chunk using Ollama."""
    embedded = []
    for i, chunk in enumerate(chunks):
        try:
            response = httpx.post(
                f"{OLLAMA_BASE_URL}/api/embeddings",
                json={"model": OLLAMA_EMBED_MODEL, "prompt": chunk["text"]},
                timeout=60,
            )
            response.raise_for_status()
            embedding = response.json()["embedding"]
            chunk["embedding"] = embedding
            embedded.append(chunk)

            if (i + 1) % 10 == 0:
                logger.info(f"  Embedded {i + 1}/{len(chunks)} chunks...")
        except Exception as e:
            logger.error(f"❌ Failed to embed chunk {i}: {e}")

    logger.info(f"🔢 Embedded {len(embedded)}/{len(chunks)} chunks")
    return embedded


def load_into_chroma(embedded_chunks: list[dict]):
    """Upsert embedded chunks into ChromaDB."""
    if not embedded_chunks:
        logger.warning("No chunks to load into ChromaDB")
        return 0

    chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    collection = chroma_client.get_or_create_collection(
        CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    ids = [c["chunk_id"] for c in embedded_chunks]
    embeddings = [c["embedding"] for c in embedded_chunks]
    documents = [c["text"] for c in embedded_chunks]
    metadatas = [
        {
            "filename": c["filename"],
            "page_number": c["page_number"],
            "chunk_index": c["chunk_index"],
            "word_count": c["word_count"],
        }
        for c in embedded_chunks
    ]

    # Upsert in batches of 100
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i : i + batch_size],
            embeddings=embeddings[i : i + batch_size],
            documents=documents[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
        )

    total = collection.count()
    logger.info(f"✅ Loaded {len(ids)} vectors into ChromaDB. Total: {total}")
    return len(ids)


def process_single_file(object_key: str, **context):
    """Full ETL pipeline for a single file."""
    logger.info(f"🚀 Processing file: {object_key}")

    # Extract
    file_info = extract_file(object_key)

    # Transform
    chunks = parse_and_chunk_text(
        file_bytes=file_info["file_bytes"],
        file_ext=file_info["file_ext"],
        object_key=object_key,
    )

    if not chunks:
        logger.warning(f"⚠️ No chunks extracted from {object_key}")
        return {"object_key": object_key, "status": "skipped", "chunks": 0}

    # Embed
    embedded = embed_chunks(chunks)

    # Load
    loaded = load_into_chroma(embedded)

    logger.info(f"✅ Pipeline complete for {object_key}: {loaded} vectors loaded")
    return {"object_key": object_key, "status": "success", "chunks": loaded}


def run_ingestion_pipeline(**context):
    """Main task: processes all unprocessed files."""
    files = context["ti"].xcom_pull(key="files_to_process", task_ids="discover_files")
    if not files:
        logger.info("✅ No new files to process")
        return

    results = []
    for object_key in files:
        try:
            result = process_single_file(object_key, **context)
            results.append(result)
        except Exception as e:
            logger.error(f"❌ Failed to process {object_key}: {e}", exc_info=True)
            results.append({"object_key": object_key, "status": "failed", "error": str(e)})

    success = sum(1 for r in results if r["status"] == "success")
    logger.info(f"📊 Pipeline summary: {success}/{len(results)} files processed successfully")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# DAG Definition
# ─────────────────────────────────────────────────────────────────────────────

with DAG(
    dag_id="rag_ingestion_pipeline",
    description="Ingest new documents from MinIO, embed them, and load into ChromaDB",
    default_args=default_args,
    schedule_interval=timedelta(minutes=5),  # Poll every 5 minutes
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["rag", "ingestion", "nlp"],
) as dag:

    discover_task = PythonOperator(
        task_id="discover_files",
        python_callable=discover_unprocessed_files,
        doc_md="Scans MinIO for new files not yet embedded in ChromaDB.",
    )

    ingest_task = PythonOperator(
        task_id="ingest_pipeline",
        python_callable=run_ingestion_pipeline,
        doc_md="Runs ETL (Extract → Transform → Embed → Load) for each new file.",
    )

    discover_task >> ingest_task
