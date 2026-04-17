#!/usr/bin/env bash
set -euo pipefail

# Runs on the Mac mini (cron / launchd). Pulls from phish.net, ships a WAL-safe
# SQLite snapshot to the NAS, and triggers the API to acknowledge the swap.
#
# Ship protocol (avoids WAL/SHM sidecar-file race):
#   1. `VACUUM INTO` produces a single-file snapshot with no WAL dependency.
#   2. The script explicitly deletes any stale *.db-wal / *.db-shm on the NAS.
#   3. The reload endpoint is a no-op for SQLite (per-request connections pick up
#      the renamed file on their own), but it acts as an explicit readiness
#      handshake and future hook for model reloads.

REPO_DIR="${REPO_DIR:-$HOME/phishpicker}"
NAS_DATA_DIR="${NAS_DATA_DIR:-/volume/phishpicker/data}"
NAS_APP_DIR="${NAS_APP_DIR:-/volume/phishpicker/app}"
NAS_HOST="${NAS_HOST:-nas-ssh}"

cd "$REPO_DIR/api"
uv run phishpicker ingest

SRC_DB="$REPO_DIR/data/phishpicker.db"
SNAP="$REPO_DIR/data/phishpicker.snapshot.db"

# Produce a clean single-file snapshot even with an open writer on the source.
rm -f "$SNAP"
sqlite3 "$SRC_DB" "VACUUM INTO '$SNAP';"

# Ship to NAS.
STAGING="$NAS_DATA_DIR/phishpicker.db.new"
FINAL="$NAS_DATA_DIR/phishpicker.db"
scp "$SNAP" "$NAS_HOST:$STAGING"

# Load admin token from repo-root .env. DO NOT echo it.
# shellcheck disable=SC2046
export $(grep -E '^PHISHPICKER_ADMIN_TOKEN=' "$REPO_DIR/.env" | xargs)

ssh "$NAS_HOST" "set -e
    rm -f '$FINAL-wal' '$FINAL-shm'
    mv '$STAGING' '$FINAL'
    docker compose -f '$NAS_APP_DIR/docker-compose.yml' exec -T api \
        curl -fsS -H 'X-Admin-Token: $PHISHPICKER_ADMIN_TOKEN' \
             -X POST http://127.0.0.1:8000/internal/reload"

echo "shipped: $(date -u +%FT%TZ)"
