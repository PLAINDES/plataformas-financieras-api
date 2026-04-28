#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Seeding database with initial data..."
python -m seeds.seed_from_sql
exec "$@"