#!/bin/bash
set -e

# 1. Wait for Postgres to be ready
echo "Waiting for postgres..."
while ! nc -z postgres 5432; do
  sleep 0.1
done
echo "PostgreSQL started"

# 2. Run migrations
echo "Running database migrations..."
alembic upgrade head

# 3. Start the application
echo "Starting API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000