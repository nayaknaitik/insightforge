#!/usr/bin/env bash
# Starts everything: Postgres check, backend API, frontend.
# First run also installs dependencies.
set -euo pipefail
cd "$(dirname "$0")"

DB=${PGDATABASE:-insightforge}

echo "→ checking Postgres"
if ! pg_isready -q; then
  echo "Postgres is not running. Start it with:  brew services start postgresql@16"
  exit 1
fi
psql -lqt | cut -d '|' -f1 | grep -qw "$DB" || { echo "→ creating database $DB"; createdb "$DB"; }

if [ ! -d backend/.venv ]; then
  echo "→ installing backend dependencies (first run only)"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q --upgrade pip
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi
[ -f backend/.env ] || cp backend/.env.example backend/.env

if [ ! -d frontend/node_modules ]; then
  echo "→ installing frontend dependencies (first run only)"
  (cd frontend && npm install)
fi

echo "→ starting API on http://127.0.0.1:8077"
backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8077 &
API=$!
trap 'kill $API 2>/dev/null || true' EXIT

echo "→ starting web app on http://localhost:5177"
(cd frontend && npm run dev)
