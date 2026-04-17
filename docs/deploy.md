# Deployment Guide

Phishpicker runs on your QNAP NAS via Docker Compose. The Mac mini runs ingestion
hourly and ships the result. This is a one-time setup guide.

---

## NAS directory layout

```
/volume/phishpicker/
  app/          ← git clone lives here; docker compose runs from here
  data/         ← SQLite DBs + future model artifacts; bind-mounted into containers
  bin/          ← deploy-wrapper.sh (SSH command restriction, see step 5)
```

The Docker Compose user must own both `app/` and `data/`. The `.env` file lives
next to `docker-compose.yml` in `app/` — it is gitignored and must be created
manually after cloning (step 2).

---

## 1. First deploy

```bash
ssh nas-ssh 'mkdir -p /volume/phishpicker/data /volume/phishpicker/bin'
ssh nas-ssh 'git clone <repo-url> /volume/phishpicker/app'

# Create .env on the NAS (not in git).
ssh nas-ssh 'cat > /volume/phishpicker/app/.env' <<EOF
PHISHNET_API_KEY=<paste from mac mini .env>
PHISHPICKER_ADMIN_TOKEN=<paste from mac mini .env — same token>
EOF
ssh nas-ssh 'chmod 600 /volume/phishpicker/app/.env'

# Build images and start.
ssh nas-ssh 'cd /volume/phishpicker/app && docker compose up -d --build'
```

Verify: `curl http://127.0.0.1:3000/` from the NAS should return the app HTML.

---

## 2. Auth — pick ONE architecture

The two options do not compose cleanly. Choose before setting up the tunnel.

### Option A — Cloudflare Access (recommended, simpler)

Cloudflare's Zero Trust product sits in front of the tunnel and gates the
hostname. No Authentik involved.

1. In the Cloudflare dashboard → Zero Trust → Access → Applications →
   **Add a self-hosted app** for `phishpicker.<your-domain>`.
2. Policy: allow your email address only.
3. Tunnel service points directly at `http://127.0.0.1:3000` on the NAS.

### Option B — Authentik in front of the web container

Use this only if you already run Authentik and want SSO with your other apps.

1. Deploy an Authentik outpost container on the same Docker network as the NAS stack.
2. Configure a Forward Auth provider in Authentik.
3. Tunnel points at the outpost's HTTP endpoint (e.g., `http://authentik-proxy:9000`),
   not at `web:3000` directly. The outpost proxies authenticated requests to `web:3000`.

> **Do NOT** point the tunnel at `web:3000` AND expect Authentik to gate it —
> the Cloudflare tunnel bypasses Authentik entirely.

---

## 3. Cloudflare tunnel config

Add a public hostname in the tunnel dashboard:

| Field | Value |
|---|---|
| Subdomain | `phishpicker` |
| Domain | `<your-domain>` |
| Service | `http://127.0.0.1:3000` (Option A) or Authentik outpost URL (Option B) |

---

## 4. SSH key: Mac mini → NAS

Create a dedicated key pair on the Mac mini (do not reuse an existing key):

```bash
# on Mac mini
ssh-keygen -t ed25519 -f ~/.ssh/phishpicker_ship -C 'phishpicker ship'
```

Add to `~/.ssh/config` on the Mac mini:

```
Host nas-ssh
  HostName nas-ssh.murphy52.xyz
  User <nas-user>
  IdentityFile ~/.ssh/phishpicker_ship
  ProxyCommand cloudflared access ssh --hostname %h
```

On the NAS, **restrict** the authorized key to a deploy-wrapper script so a
compromised Mac mini cannot pivot to a shell. In `~/.ssh/authorized_keys`:

```
command="/volume/phishpicker/bin/deploy-wrapper.sh",no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... phishpicker ship
```

Create `/volume/phishpicker/bin/deploy-wrapper.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
# Whitelist the exact commands the ship script issues over SSH.
case "$SSH_ORIGINAL_COMMAND" in
  "scp -t /volume/phishpicker/data/phishpicker.db.new")
    exec $SSH_ORIGINAL_COMMAND ;;
  "set -e"*)
    # The multi-command block: rm WAL, mv, docker compose exec curl.
    eval "$SSH_ORIGINAL_COMMAND" ;;
  *)
    echo "command not allowed: $SSH_ORIGINAL_COMMAND" >&2
    exit 1 ;;
esac
```

```bash
chmod 700 /volume/phishpicker/bin/deploy-wrapper.sh
```

---

## 5. Scheduled ingestion on Mac mini

Use **launchd**, not cron — modern macOS cron is deprecated and needs Full Disk
Access grants.

Create `~/Library/LaunchAgents/com.phishpicker.ship.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.phishpicker.ship</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/Administrator/phishpicker/scripts/ingest_and_ship.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/Administrator/Library/Logs/phishpicker-ingest.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/Administrator/Library/Logs/phishpicker-ingest.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
  </dict>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.phishpicker.ship.plist
```

Logs land in `~/Library/Logs/` (user-writable, no root needed). The ship script
sends a push notification on failure via `~/bin/notify` — check your phone if
ingestion stops.

---

## 6. Updating the app

```bash
ssh nas-ssh 'cd /volume/phishpicker/app && git pull && docker compose up -d --build'
```

The `data/` volume is not touched by `up --build`.

---

## 7. First data load

After deploying, trigger a manual ingest from the Mac mini:

```bash
cd ~/phishpicker/api
uv run phishpicker ingest
```

Then run the ship script once manually to push data to the NAS:

```bash
bash ~/phishpicker/scripts/ingest_and_ship.sh
```

Verify: `curl http://127.0.0.1:3000/` → footer should show non-zero show count.
