#!/usr/bin/env bash
# Deploy code + model to the NAS atomically.
#
# The prior ship_v7_to_nas.sh shipped the model file but not the code,
# which caused a silent FEATURE_COLUMNS schema mismatch → fallback to the
# heuristic scorer. This script fixes that: it fetches/resets the NAS's
# git clone to origin/main, rebuilds the API image, ships the model, and
# verifies the new scorer loaded as lightgbm (not heuristic) before
# returning success.
#
# Usage:
#   bash scripts/deploy_to_nas.sh
#
# Environment overrides:
#   NAS_HOST   default Murphy52@storage.local (use nas-ssh for Cloudflare)
#   NAS_APP    default /home/Murphy52/docker/apps/phishpicker
#   MODEL_DIR  default /tmp/v7  — must contain model.lgb + model.meta.json + metrics.json
#
# Rollback:
#   The script prints a rollback one-liner on any verification failure.
#   Backups are stored on the NAS as:
#     data/*.v5-backup      — sticky, created the first time we shipped v7
#     data/*.prev-backup    — overwritten each deploy, "undo last deploy"
#   And the prior git HEAD is printed at the top of each run.

set -euo pipefail

NAS_HOST="${NAS_HOST:-Murphy52@storage.local}"
NAS_APP="${NAS_APP:-/home/Murphy52/docker/apps/phishpicker}"
MODEL_DIR="${MODEL_DIR:-/tmp/v7}"

bold=$(tput bold 2>/dev/null || true); reset=$(tput sgr0 2>/dev/null || true)
step() { echo -e "\n${bold}[$1]${reset} $2"; }

# ---------- Pre-flight ----------

step "0a" "Local repo: check for uncommitted changes"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: uncommitted or staged changes. Commit or stash first."
  exit 1
fi

step "0b" "Local HEAD matches origin/main"
git fetch origin main --quiet
local_head=$(git rev-parse HEAD)
remote_head=$(git rev-parse origin/main)
if [[ "$local_head" != "$remote_head" ]]; then
  echo "ERROR: local HEAD $local_head != origin/main $remote_head"
  echo "       Push or pull first — NAS will pull from origin."
  exit 1
fi
echo "  commit: $local_head"

step "0c" "Model artifacts present at $MODEL_DIR"
for f in model.lgb model.meta.json metrics.json; do
  [[ -f "$MODEL_DIR/$f" ]] || { echo "ERROR: missing $MODEL_DIR/$f"; exit 1; }
done

step "0d" "NAS reachable at $NAS_HOST"
if ! ssh -o ConnectTimeout=10 "$NAS_HOST" 'echo ok' >/dev/null 2>&1; then
  echo "ERROR: cannot ssh $NAS_HOST (banner-exchange timeout = window closed)"
  exit 2
fi

step "0e" "NAS pre-deploy state (for rollback)"
PREV_GIT=$(ssh "$NAS_HOST" "cd '$NAS_APP' && git rev-parse HEAD")
echo "  NAS HEAD before deploy: $PREV_GIT"

# ---------- Deploy ----------

step "1" "Snapshot current model as *.prev-backup (for undo-last-deploy)"
ssh "$NAS_HOST" "
  set -e
  cd '$NAS_APP/data'
  for f in model.lgb model.meta.json metrics.json; do
    cp \"\$f\" \"\$f.prev-backup\"
  done
  ls -la *.prev-backup
"

step "2" "Fetch + reset NAS code to $local_head"
ssh "$NAS_HOST" "
  set -e
  cd '$NAS_APP'
  git fetch origin main
  git reset --hard origin/main
  echo '  NAS HEAD now:'
  git log -1 --oneline
"

step "3" "Build API image with new code (this is the slow step)"
ssh "$NAS_HOST" "cd '$NAS_APP' && docker compose build api 2>&1 | tail -20"

step "4" "Upload new model artifacts as *.new"
scp -O "$MODEL_DIR/model.lgb"        "$NAS_HOST:$NAS_APP/data/model.lgb.new"
scp -O "$MODEL_DIR/model.meta.json"  "$NAS_HOST:$NAS_APP/data/model.meta.json.new"
scp -O "$MODEL_DIR/metrics.json"     "$NAS_HOST:$NAS_APP/data/metrics.json.new"

step "5" "Atomic rename into place"
ssh "$NAS_HOST" "
  set -e
  cd '$NAS_APP/data'
  mv model.lgb.new        model.lgb
  mv model.meta.json.new  model.meta.json
  mv metrics.json.new     metrics.json
"

step "6" "Recreate API container with new image"
ssh "$NAS_HOST" "cd '$NAS_APP' && docker compose up -d api 2>&1 | tail -10"

step "7" "Wait for healthcheck and verify scorer=lightgbm"
for i in $(seq 1 18); do
  sleep 5
  meta=$(ssh "$NAS_HOST" "curl -s http://127.0.0.1:3400/api/meta" 2>/dev/null || true)
  if [[ "$meta" == *'"scorer":"lightgbm"'* ]]; then
    echo
    echo "${bold}✓ deployed${reset}"
    echo "  $(echo "$meta" | head -c 200)"
    echo
    echo "Rollback (last deploy):"
    echo "  ssh $NAS_HOST \"cd '$NAS_APP' && git reset --hard $PREV_GIT && cd data && cp model.lgb.prev-backup model.lgb && cp model.meta.json.prev-backup model.meta.json && cp metrics.json.prev-backup metrics.json && cd .. && docker compose build api && docker compose up -d api\""
    exit 0
  fi
  echo "  waiting… ($i/18) last meta: $(echo "$meta" | head -c 100)"
done

echo
echo "${bold}⚠ verification failed${reset} — API up but scorer is not lightgbm after 90s."
echo "Rollback command:"
echo "  ssh $NAS_HOST \"cd '$NAS_APP' && git reset --hard $PREV_GIT && cd data && cp model.lgb.prev-backup model.lgb && cp model.meta.json.prev-backup model.meta.json && cp metrics.json.prev-backup metrics.json && cd .. && docker compose build api && docker compose up -d api\""
exit 3
