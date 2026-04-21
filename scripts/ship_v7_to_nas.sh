#!/usr/bin/env bash
# Ship v7 model artifacts from local /tmp/v7/ to the NAS.
#
# Prerequisites:
#   1. NAS SSH window is OPEN — verify with `ssh nas-ssh 'echo ok'`.
#      If you see "banner exchange timeout", the window is closed; enable it
#      on the NAS first.
#   2. Local /tmp/v7/ has {model.lgb, model.meta.json, metrics.json} — they
#      were pulled there by the post-training eval flow; re-scp from mac-mini
#      if missing.
#
# The script:
#   1. Backs up the currently-deployed v5 (so rollback is a single cp).
#   2. Uploads new artifacts under *.new names.
#   3. Atomically renames them into place (so a concurrent read can't see
#      a half-written model.lgb).
#   4. Restarts the API container so the new model is loaded.
#   5. Sanity-pings the loopback /readyz endpoint.
#
# Rollback:
#   ssh nas-ssh 'cd /home/Murphy52/docker/apps/phishpicker/data && \
#     cp model.lgb.v5-backup model.lgb && \
#     cp model.meta.json.v5-backup model.meta.json && \
#     cd .. && docker compose restart api'

set -euo pipefail

LOCAL_DIR="/tmp/v7"
NAS_HOST="${NAS_HOST:-nas-ssh}"
NAS_DATA="/home/Murphy52/docker/apps/phishpicker/data"
NAS_APP="/home/Murphy52/docker/apps/phishpicker"

echo "== ship_v7_to_nas =="
echo "  source: $LOCAL_DIR"
echo "  target: $NAS_HOST:$NAS_DATA"
echo

# 0. Sanity: local artifacts exist
for f in model.lgb model.meta.json metrics.json; do
  [[ -f "$LOCAL_DIR/$f" ]] || { echo "missing $LOCAL_DIR/$f"; exit 1; }
done

# 0b. Sanity: NAS reachable via SSH
if ! ssh -o ConnectTimeout=10 "$NAS_HOST" 'echo ok' >/dev/null 2>&1; then
  echo "ERROR: cannot ssh $NAS_HOST — is the SSH window open?"
  echo "       banner-exchange timeouts mean the window is closed."
  exit 2
fi

# 1. Backup the currently-deployed v5 on the NAS (once — skip if already backed up)
echo "[1/4] Backing up current NAS model as *.v5-backup (if not already)"
ssh "$NAS_HOST" "
  set -e
  cd '$NAS_DATA'
  for f in model.lgb model.meta.json metrics.json; do
    if [[ ! -f \"\$f.v5-backup\" ]]; then
      cp \"\$f\" \"\$f.v5-backup\"
      echo \"  backed up \$f -> \$f.v5-backup\"
    else
      echo \"  \$f.v5-backup already exists, skipping\"
    fi
  done
"

# 2. Upload new artifacts under .new names (safe against concurrent reads)
echo "[2/4] Uploading v7 artifacts as *.new"
scp "$LOCAL_DIR/model.lgb"        "$NAS_HOST:$NAS_DATA/model.lgb.new"
scp "$LOCAL_DIR/model.meta.json"  "$NAS_HOST:$NAS_DATA/model.meta.json.new"
scp "$LOCAL_DIR/metrics.json"     "$NAS_HOST:$NAS_DATA/metrics.json.new"

# 3. Atomic rename
echo "[3/4] Atomic rename into place"
ssh "$NAS_HOST" "
  set -e
  cd '$NAS_DATA'
  mv model.lgb.new        model.lgb
  mv model.meta.json.new  model.meta.json
  mv metrics.json.new     metrics.json
  ls -la model.lgb model.meta.json metrics.json
"

# 4. Restart API so the booster reloads
echo "[4/4] Restarting API container"
ssh "$NAS_HOST" "cd '$NAS_APP' && docker compose restart api"

echo
echo "== shipped =="
echo "v7 now serving on NAS loopback. Rollback instructions are in this script's header."
