#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Seeding database with initial data..."
python -m seeds.seed_from_sql

echo "Starting Uvicorn server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
