# scripts/

## ingest_and_ship.sh

Runs on the Mac mini. Pulls new shows from phish.net, produces a WAL-safe
SQLite snapshot via `VACUUM INTO`, SCPs it to the NAS, atomically renames it
into place, and pings `/internal/reload` inside the API container.

**Prerequisites:**

- `uv` installed and `phishpicker` package set up in `api/`
- `sqlite3` CLI available
- `ssh nas-ssh` configured in `~/.ssh/config` (see deploy docs)
- Repo-root `.env` containing `PHISHPICKER_ADMIN_TOKEN=...`

**Environment variables (with defaults):**

| Variable | Default | Description |
|---|---|---|
| `REPO_DIR` | `~/phishpicker` | Local clone of this repo |
| `NAS_DATA_DIR` | `/volume/phishpicker/data` | Data volume path on the NAS |
| `NAS_APP_DIR` | `/volume/phishpicker/app` | App deploy path on the NAS |
| `NAS_HOST` | `nas-ssh` | SSH alias for the NAS |

**Manual run:**

```bash
bash scripts/ingest_and_ship.sh
```

**Scheduled run (launchd example):**

Create `~/Library/LaunchAgents/com.phishpicker.ingest.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.phishpicker.ingest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/Administrator/phishpicker/scripts/ingest_and_ship.sh</string>
  </array>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>StandardOutPath</key>
  <string>/tmp/phishpicker-ingest.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/phishpicker-ingest.err</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
  </dict>
</dict>
</plist>
```

Load: `launchctl load ~/Library/LaunchAgents/com.phishpicker.ingest.plist`
