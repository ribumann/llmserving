#!/bin/sh
# Applies pending Alembic migrations before serving traffic, using the same
# DATABASE_URL/settings the app itself resolves (src/config.py) - the app's own
# outbound connectivity/firewall allow-listing already works, so this avoids
# needing separate DB network access for deploy-time migrations. Without this,
# ORM model changes silently drift from the deployed schema until someone
# remembers to run `alembic upgrade head` by hand (see migrations/versions/
# 20260821_0002_add_environment_id_to_configs.py for a bug this caused).
set -e
echo "Applying database migrations (alembic upgrade head)..."
alembic upgrade head

# Seed reference-data catalogs on every startup. Each seed script uses
# session.merge() keyed by a stable id, so this is an idempotent upsert (safe to
# re-run) rather than a one-time setup step - without it, a freshly provisioned
# database has no model catalog, benchmark definitions, golden datasets, or
# performance workloads to select in the UI until someone remembers to run the
# seed scripts by hand.
echo "Seeding reference-data catalogs..."
seed-model-catalog
seed-benchmarks
seed-golden-datasets
seed-performance-workloads

echo "Seeding complete. Starting server."
exec uvicorn src.api.app:app --host 0.0.0.0 --port 8000
