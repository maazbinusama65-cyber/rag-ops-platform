"""
Custom Prometheus metrics for the RAG-Ops Platform.
"""

from prometheus_client import Counter, Gauge, Histogram

# ─── Retrieval Metrics ─────────────────────────────────────────────────────────
rag_retrieval_latency = Histogram(
    "rag_retrieval_latency_seconds",
    "Time spent performing similarity search in ChromaDB",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

llm_generation_latency = Histogram(
    "llm_generation_latency_seconds",
    "Time spent generating a response from Ollama",
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

# ─── Business Metrics ─────────────────────────────────────────────────────────
queries_total = Counter(
    "rag_queries_total",
    "Total number of chat queries processed",
    ["status"],  # success / error
)

documents_uploaded_total = Counter(
    "rag_documents_uploaded_total",
    "Total number of documents uploaded",
    ["file_type"],
)

# ─── Vector Store Metrics ─────────────────────────────────────────────────────
chroma_vectors_total = Gauge(
    "chroma_vectors_total",
    "Current number of vectors stored in ChromaDB",
)

# ─── System Metrics ───────────────────────────────────────────────────────────
active_requests = Gauge(
    "rag_active_requests",
    "Number of currently active requests",
)
