# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels -r requirements.txt

# ── Production stage ──────────────────────────────────────────────────────────
FROM python:3.11-slim

# Security: run as non-root
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages from wheels
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Copy and prepare the entrypoint script
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Use the entrypoint script to start the container
ENTRYPOINT ["./entrypoint.sh"]
# Ownership
RUN chown -R appuser:appuser /app
USER appuser

