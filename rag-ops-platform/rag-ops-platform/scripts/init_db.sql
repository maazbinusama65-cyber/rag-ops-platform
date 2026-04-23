-- RAG-Ops Platform — Database Initialization
-- This runs automatically on first PostgreSQL startup.

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- document_uploads: audit log for every uploaded file
CREATE TABLE IF NOT EXISTS document_uploads (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename        VARCHAR(512)    NOT NULL,
    original_filename VARCHAR(512)  NOT NULL,
    file_size_bytes INTEGER,
    content_type    VARCHAR(128),
    minio_object_key VARCHAR(1024)  NOT NULL,
    user_id         VARCHAR(256)    NOT NULL DEFAULT 'anonymous',
    upload_time     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    status          VARCHAR(32)     NOT NULL DEFAULT 'uploaded',
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_uploads_user_id    ON document_uploads(user_id);
CREATE INDEX IF NOT EXISTS idx_doc_uploads_status     ON document_uploads(status);
CREATE INDEX IF NOT EXISTS idx_doc_uploads_upload_time ON document_uploads(upload_time);

-- chat_logs: full compliance audit trail for every RAG query
CREATE TABLE IF NOT EXISTS chat_logs (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id            VARCHAR(256),
    user_id               VARCHAR(256)    NOT NULL DEFAULT 'anonymous',
    query                 TEXT            NOT NULL,
    answer                TEXT,
    retrieved_doc_ids     TEXT[],
    retrieved_doc_names   TEXT[],
    retrieval_latency_ms  FLOAT,
    generation_latency_ms FLOAT,
    total_latency_ms      FLOAT,
    model_used            VARCHAR(128),
    status                VARCHAR(32)     NOT NULL DEFAULT 'pending',
    error_message         TEXT,
    created_at            TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_logs_user_id    ON chat_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_logs_session_id ON chat_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_logs_status     ON chat_logs(status);
CREATE INDEX IF NOT EXISTS idx_chat_logs_created_at ON chat_logs(created_at);

-- Useful view: query stats per hour (used in Grafana business metrics panel)
CREATE OR REPLACE VIEW hourly_query_stats AS
SELECT
    DATE_TRUNC('hour', created_at) AS hour,
    COUNT(*)                        AS total_queries,
    COUNT(*) FILTER (WHERE status = 'success') AS successful,
    COUNT(*) FILTER (WHERE status = 'error')   AS failed,
    AVG(total_latency_ms)           AS avg_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95_latency_ms
FROM chat_logs
GROUP BY DATE_TRUNC('hour', created_at)
ORDER BY hour DESC;

COMMENT ON TABLE document_uploads IS 'Compliance audit log for all document uploads to MinIO.';
COMMENT ON TABLE chat_logs        IS 'Full compliance audit trail for all RAG queries — required for security review.';
