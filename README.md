# RAG-Ops Platform 🚀

> **Self-Hosted Enterprise Knowledge Assistant** — A production-grade, Local-First RAG (Retrieval-Augmented Generation) platform deployed on Kubernetes. Built for DevOps/SRE teams to query private internal runbooks and incident reports with full compliance audit logging.

[![CI/CD](https://github.com/YOUR_USERNAME/rag-ops-platform/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/YOUR_USERNAME/rag-ops-platform/actions)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Kubernetes (K3d)                                 │
│                                                                           │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐               │
│  │  FastAPI     │    │   Airflow    │    │  Prometheus  │               │
│  │  Gateway     │    │  Scheduler   │    │  + Grafana   │               │
│  │  :8000       │    │   :8080      │    │  :9090/:3000 │               │
│  └──────┬───────┘    └──────┬───────┘    └──────────────┘               │
│         │                   │                                             │
│  ┌──────▼───────┐    ┌──────▼───────┐    ┌──────────────┐               │
│  │  ChromaDB    │    │    MinIO     │    │  PostgreSQL  │               │
│  │  (Vectors)   │    │  (Raw Files) │    │  (Audit Logs)│               │
│  └──────────────┘    └──────────────┘    └──────────────┘               │
│                                                                           │
│  ┌──────────────────────────────────────────────────────┐               │
│  │                   Ollama (LLM)                        │               │
│  │          mistral (generation) + nomic-embed-text      │               │
│  └──────────────────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User Query
    │
    ▼
FastAPI /chat
    ├─► Log query to PostgreSQL (chat_logs)
    ├─► Embed query via Ollama (nomic-embed-text)
    ├─► Similarity search in ChromaDB → top-K chunks
    ├─► Generate answer via Ollama (mistral) + context
    └─► Update PostgreSQL log (answer + latencies + doc IDs)

Document Upload
    │
    ▼
FastAPI /upload
    ├─► Store raw file in MinIO (runbooks bucket)
    └─► Log upload event in PostgreSQL (document_uploads)
         │
         ▼ (every 5 minutes)
    Airflow DAG
         ├─► Discover new files in MinIO
         ├─► Extract + parse text (PDF/MD/TXT)
         ├─► Chunk into 500-token windows (50-token overlap)
         ├─► Embed each chunk via Ollama
         └─► Upsert vectors into ChromaDB
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Infrastructure | K3d (K3s in Docker) | Local Kubernetes cluster |
| API Gateway | FastAPI + Uvicorn | REST API, streaming, Prometheus metrics |
| LLM | Ollama (mistral) | Answer generation |
| Embeddings | Ollama (nomic-embed-text) | Vector embedding |
| Vector Store | ChromaDB | Semantic similarity search |
| Object Storage | MinIO | Raw file storage (PDF/MD/TXT) |
| Relational DB | PostgreSQL 16 | Compliance audit logging |
| Orchestration | Apache Airflow | ETL ingestion pipeline |
| Observability | Prometheus + Grafana | Metrics, dashboards, alerting |
| CI/CD | GitHub Actions | Lint → Build → Push → Deploy |

---

## Project Structure

```
rag-ops-platform/
├── app/                          # FastAPI application
│   ├── main.py                   # App entrypoint, lifespan, middleware
│   ├── api/
│   │   └── routes/
│   │       ├── chat.py           # POST /api/v1/chat (RAG query)
│   │       ├── documents.py      # POST /api/v1/upload
│   │       └── health.py         # GET /health, /health/ready
│   ├── core/
│   │   ├── config.py             # Pydantic settings (env vars)
│   │   ├── database.py           # Async SQLAlchemy engine
│   │   ├── logging.py            # Structured logging
│   │   └── metrics.py            # Prometheus metric definitions
│   ├── models/
│   │   └── audit.py              # SQLAlchemy ORM: document_uploads, chat_logs
│   └── services/
│       ├── chroma_service.py     # ChromaDB client (upsert, search)
│       ├── minio_service.py      # MinIO client (upload, download, list)
│       └── ollama_service.py     # Ollama client (embed, generate, stream)
│
├── pipeline/
│   └── dags/
│       └── rag_ingestion_pipeline.py  # Airflow DAG: MinIO → Chunk → Embed → Chroma
│
├── k8s/
│   ├── base/
│   │   ├── namespace.yaml        # Namespace + ConfigMap + Secrets
│   │   ├── postgres.yaml         # PostgreSQL Deployment + PVC + Service
│   │   ├── ollama.yaml           # Ollama Deployment + PVC + Service
│   │   └── api.yaml              # FastAPI Deployment + HPA + Services
│   ├── storage/
│   │   ├── minio.yaml            # MinIO Deployment + PVC + Services
│   │   └── chromadb.yaml         # ChromaDB StatefulSet + PVC + Service
│   └── monitoring/
│       └── monitoring-stack.yaml # Prometheus + Grafana + RBAC
│
├── monitoring/
│   ├── prometheus/
│   │   ├── prometheus.yml        # Scrape config
│   │   └── alerts.yml            # Alerting rules
│   └── grafana/
│       ├── provisioning/         # Auto-provisioned datasources + dashboards
│       └── dashboards/
│           └── rag-ops-dashboard.json  # Pre-built Grafana dashboard
│
├── scripts/
│   ├── k3d-setup.sh              # Cluster lifecycle management
│   └── init_db.sql               # PostgreSQL schema initialization
│
├── tests/
│   ├── conftest.py
│   └── test_api.py               # API endpoint tests
│
├── .github/
│   └── workflows/
│       └── ci-cd.yml             # GitHub Actions pipeline
│
├── docker-compose.yml            # Full local dev stack (no K8s needed)
├── Dockerfile                    # Multi-stage production image
├── requirements.txt
├── pyproject.toml                # Ruff + Black + pytest config
└── README.md
```

---

## Quick Start

### Option A — Docker Compose (Fastest, no K8s needed)

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/rag-ops-platform.git
cd rag-ops-platform

# 2. Start the full stack
docker compose up -d

# 3. Wait for model downloads (~5-10 min on first run)
docker compose logs -f ollama-init

# 4. Test the API
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
```

### Option B — Kubernetes with K3d (Full production setup)

#### Prerequisites

```bash
# Install K3d
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash

# Verify
k3d version
kubectl version --client
```

#### Deploy

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/rag-ops-platform.git
cd rag-ops-platform

# 2. Spin up the cluster + deploy everything
chmod +x scripts/k3d-setup.sh
./scripts/k3d-setup.sh up

# 3. Check status
./scripts/k3d-setup.sh status
```

This will:
- Create a K3d cluster with 1 server node + 2 agent nodes
- Apply all Kubernetes manifests in order
- Wait for all deployments to be ready
- Print the access URLs

---

## Service Access URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| RAG API | http://localhost:8000 | — |
| API Docs (Swagger) | http://localhost:8000/docs | — |
| API Docs (Redoc) | http://localhost:8000/redoc | — |
| MinIO Console | http://localhost:9001 | `minioadmin` / `minioadmin` |
| Airflow | http://localhost:8080 | `admin` / `admin` |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3000 | `admin` / `admin` |

---

## API Usage

### Upload a Document

```bash
# Upload a PDF runbook
curl -X POST http://localhost:8000/api/v1/upload \
  -H "X-User-Id: sre-team" \
  -F "file=@runbooks/database-latency-runbook.pdf"

# Upload a Markdown file
curl -X POST http://localhost:8000/api/v1/upload \
  -H "X-User-Id: platform-team" \
  -F "file=@runbooks/k8s-incident-response.md"
```

**Response:**
```json
{
  "message": "Document uploaded successfully. Pipeline will process it shortly.",
  "upload_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "object_key": "uploads/2024/01/15/abc123.pdf",
  "filename": "database-latency-runbook.pdf",
  "file_size_bytes": 45678,
  "status": "uploaded"
}
```

### Query the Knowledge Base

```bash
# Standard query
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-User-Id: on-call-engineer" \
  -d '{
    "query": "Production database latency spike — what are the first 3 steps in the runbook?",
    "top_k": 5
  }'
```

**Response:**
```json
{
  "log_id": "7b2c9d4e-...",
  "query": "Production database latency spike...",
  "answer": "According to the runbook, the first 3 steps are:\n1. Check pg_stat_activity...",
  "retrieved_documents": [
    {
      "id": "chunk_abc123",
      "filename": "uploads/2024/01/15/abc123.pdf",
      "page": 2,
      "chunk": 3,
      "relevance_score": 0.9421,
      "preview": "Database Latency Runbook: When latency exceeds 200ms..."
    }
  ],
  "retrieval_latency_ms": 45.2,
  "generation_latency_ms": 3821.7,
  "total_latency_ms": 3871.4,
  "model_used": "mistral"
}
```

### Streaming Response (SSE)

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How do I restart the payment service pod?",
    "stream": true
  }'
```

Server-Sent Events stream:
```
data: {"type": "metadata", "log_id": "...", "retrieved_documents": [...]}
data: {"type": "token", "content": "To"}
data: {"type": "token", "content": " restart"}
data: {"type": "token", "content": " the"}
...
data: {"type": "done", "generation_latency_ms": 4200, "total_latency_ms": 4350}
```

### List Documents

```bash
curl http://localhost:8000/api/v1/documents
```

---

## Compliance & Audit Logging

Every interaction is logged to PostgreSQL for compliance. Connect with DBeaver or psql:

```bash
# Connect via psql (Docker Compose)
psql -h localhost -U ragops -d ragops

# View recent queries
SELECT id, user_id, query, status, total_latency_ms, created_at
FROM chat_logs
ORDER BY created_at DESC
LIMIT 20;

# Compliance: which docs were retrieved for a given query?
SELECT id, query, retrieved_doc_names, answer, created_at
FROM chat_logs
WHERE user_id = 'on-call-engineer'
ORDER BY created_at DESC;

# Business metrics: queries per hour
SELECT * FROM hourly_query_stats LIMIT 24;

# Document upload audit trail
SELECT filename, user_id, upload_time, status
FROM document_uploads
ORDER BY upload_time DESC;
```

---

## Observability

### Prometheus Metrics

The API exposes these custom metrics at `/metrics`:

| Metric | Type | Description |
|--------|------|-------------|
| `rag_retrieval_latency_seconds` | Histogram | ChromaDB similarity search duration |
| `llm_generation_latency_seconds` | Histogram | Ollama answer generation duration |
| `rag_queries_total` | Counter | Total queries, labelled by `status` |
| `rag_documents_uploaded_total` | Counter | Total uploads, labelled by `file_type` |
| `chroma_vectors_total` | Gauge | Current number of vectors in ChromaDB |
| `rag_active_requests` | Gauge | In-flight requests at any moment |

### Grafana Dashboard

The pre-built dashboard (auto-provisioned) includes:

- **Total Queries** — all-time count
- **Queries Per Hour** — business metric
- **Error Rate %** — with alert threshold at 10%
- **Vectors in ChromaDB** — knowledge base size
- **Retrieval Latency (p50/p95)** — ChromaDB performance
- **LLM Generation Latency (p50/p95)** — Ollama performance
- **Query Rate (req/min)** — traffic over time
- **Active Requests** — concurrency

---

## Airflow Pipeline

The `rag_ingestion_pipeline` DAG runs every **5 minutes** and:

1. **Discovers** new files in MinIO not yet embedded in ChromaDB
2. **Extracts** raw bytes from MinIO
3. **Transforms** text into 500-token chunks with 50-token overlap
4. **Embeds** each chunk using `nomic-embed-text` via Ollama
5. **Loads** vectors into ChromaDB with metadata (filename, page, chunk index)

Access the Airflow UI at http://localhost:8080 (admin/admin) to:
- Monitor DAG runs
- Inspect task logs
- Manually trigger a run after uploading files

---

## CI/CD Pipeline

Every push to `main` triggers:

```
Push to main
    │
    ├─► Lint (Ruff) + Format check (Black)
    ├─► Type check (mypy)
    ├─► Run tests (pytest)
    │
    ├─► Build multi-arch Docker image (linux/amd64 + linux/arm64)
    ├─► Push to Docker Hub with SHA tag + latest
    │
    └─► Update K8s deployment (kubectl set image)
        └─► Wait for rollout to complete
```

### GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `DOCKERHUB_USERNAME` | Your Docker Hub username |
| `DOCKERHUB_TOKEN` | Docker Hub access token |
| `KUBECONFIG` | Base64-encoded kubeconfig for your cluster |

---

## Configuration Reference

All settings are controlled via environment variables (`.env` file or K8s ConfigMap/Secrets):

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `mistral` | LLM for generation |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `CHUNK_SIZE` | `500` | Tokens per chunk |
| `CHUNK_OVERLAP` | `50` | Overlap between chunks |
| `TOP_K_RESULTS` | `5` | Context documents per query |
| `POSTGRES_PASSWORD` | — | **Set in secrets** |
| `MINIO_SECRET_KEY` | — | **Set in secrets** |

Copy `.env.example` to `.env` for local development:

```bash
cp .env.example .env
# Edit values as needed
docker compose up -d
```

---

## Local Development

```bash
# Install Python dependencies
pip install -r requirements.txt

# Run only infrastructure (no app)
docker compose up postgres minio chromadb ollama -d

# Run FastAPI with hot reload
uvicorn app.main:app --reload --port 8000

# Run tests
pytest tests/ -v

# Lint
ruff check app/ pipeline/
black --check app/ pipeline/
```

---

## Cluster Management

```bash
# Start everything
./scripts/k3d-setup.sh up

# Check all pods
./scripts/k3d-setup.sh status

# Redeploy (keep cluster, re-apply manifests)
./scripts/k3d-setup.sh redeploy

# Tear down cluster completely
./scripts/k3d-setup.sh down
```

---

## Troubleshooting

**Ollama is slow / times out**
- Ollama runs LLMs on CPU by default. For better performance, uncomment the GPU section in `k8s/base/ollama.yaml` or `docker-compose.yml`.
- For CPU-only, consider using `tinyllama` instead of `mistral`: set `OLLAMA_MODEL=tinyllama`.

**No documents found after upload**
- The Airflow pipeline runs every 5 minutes. Trigger it manually from the Airflow UI.
- Check Airflow scheduler logs: `kubectl logs -l component=scheduler -n ragops`

**ChromaDB connection refused**
- Check ChromaDB pod: `kubectl get pod -l app=chromadb -n ragops`
- Verify the PVC is bound: `kubectl get pvc -n ragops`

**PostgreSQL connection fails**
- Verify credentials match between `ragops-config` ConfigMap and `ragops-secrets` Secret.
- Check: `kubectl exec -it deployment/postgres -n ragops -- psql -U ragops -d ragops -c '\dt'`

---

## Production Hardening Checklist

Before deploying to a real cluster:

- [ ] Change all default passwords in `k8s/base/namespace.yaml` secrets
- [ ] Use Kubernetes Secrets managed by Vault or AWS Secrets Manager
- [ ] Enable MinIO TLS (`MINIO_SECURE=true`)
- [ ] Set up PostgreSQL with a managed service (RDS, Cloud SQL)
- [ ] Configure Ollama GPU node affinity for production inference
- [ ] Set `ALLOWED_ORIGINS` to specific domains (not `*`)
- [ ] Enable Grafana authentication (LDAP/OAuth)
- [ ] Set up Prometheus alertmanager with PagerDuty/Slack integration
- [ ] Configure resource quotas on the `ragops` namespace
- [ ] Enable pod security policies / OPA Gatekeeper
- [ ] Set up regular ChromaDB and PostgreSQL backups

---

## License

MIT — See [LICENSE](LICENSE) for details.

---

*Built as a portfolio project demonstrating MLOps, DevOps, and full-stack AI engineering skills.*
