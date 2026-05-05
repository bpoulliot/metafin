# Metafin

[![CI](https://github.com/bpoulliot/metafin/actions/workflows/ci.yml/badge.svg)](https://github.com/bpoulliot/metafin/actions/workflows/ci.yml)
[![CodeQL](https://github.com/bpoulliot/metafin/actions/workflows/codeql.yml/badge.svg)](https://github.com/bpoulliot/metafin/actions/workflows/codeql.yml)
[![Docker](https://img.shields.io/badge/ghcr.io-bpoulliot%2Fmetafin-blue)](https://github.com/bpoulliot/metafin/pkgs/container/metafin)

Metafin scans your Jellyfin library, extracts resolution and audio language metadata from media files, and writes that metadata back as tags in Jellyfin (and optionally Sonarr/Radarr). It also overlays badge pills directly onto poster images so your library art shows resolution and language at a glance.

---

> **Mount Point Requirement**
>
> Every volume path mounted into the Metafin container **must be identical** to the path
> Jellyfin uses inside its own container. If Jellyfin sees movies at `/data/movies`, Metafin
> must also mount and access them at `/data/movies`. Mismatched paths cause all file-level
> lookups to fail silently — media will be scanned but poster images will not be updated and
> `ffprobe` will be unable to read files. This applies to every media mount in every container.

---

## Features

- Extracts resolution (1080p, 4K, etc.), video codec, HDR type, and audio language codes via `ffprobe`
- Writes `mf-*` prefixed tags to Jellyfin, Sonarr, and Radarr
- Overlays badge pills (video, audio, subtitle, rating) onto poster/folder images
- Parallel `ffprobe` scanning — configurable worker count (`scan.max_workers`, default 4)
- Incremental scanning — only re-scans files changed since last run
- Scheduled scans via cron expression
- Web UI: dashboard, media browser, live scan log stream, badge preview, settings

---

## Quick Start (Docker)

**1. Pull from GitHub Container Registry:**

```bash
docker pull ghcr.io/bpoulliot/metafin:latest
```

Or build locally:

```bash
git clone https://github.com/bpoulliot/metafin.git
cd metafin
docker compose up -d
```

**2. Copy the example config:**

```bash
cp config.example.yml config/config.yml
cp .env.example .env
```

**3. Edit `config/config.yml`:**

- Set `jellyfin.url` and `jellyfin.api_key`
- Add Sonarr/Radarr instances if desired (optional)
- Leave `auth.password_hash` empty — credentials are auto-generated on first boot and printed to container logs

**4. Edit `docker-compose.yml`:**

Uncomment and set the media volume mounts to match your library layout. Paths must be **identical** to what Jellyfin uses inside its container so that file paths returned by the API are accessible to Metafin.

```yaml
volumes:
  - ./config:/config
  - /data/movies:/data/movies:rw
  - /data/tv:/data/tv:rw
```

**5. Start:**

```bash
docker compose up -d
```

Open `http://localhost:7755`. On first boot, auto-generated credentials are printed to the container log.

---

## Configuration Reference

All settings live in `/config/config.yml` (mapped from your `CONFIG_DIR`).

| Key | Type | Default | Description |
|---|---|---|---|
| `jellyfin.url` | string | `http://jellyfin:8096` | Jellyfin base URL |
| `jellyfin.api_key` | string | `""` | Jellyfin API key (Dashboard → API Keys) |
| `jellyfin.library_ids` | list | `[]` | Library IDs to scan; empty = all |
| `sonarr.instances` | list | `[]` | Optional Sonarr instances (name, url, api_key) |
| `radarr.instances` | list | `[]` | Optional Radarr instances (name, url, api_key) |
| `scan.schedule` | string | `"0 3 * * *"` | Cron expression for automatic scans; empty = manual only |
| `scan.incremental` | bool | `true` | Skip files unchanged since last scan |
| `scan.path_filters` | list | `[]` | Only scan paths matching these prefixes; empty = all |
| `scan.max_workers` | int | `4` | Parallel `ffprobe` workers; lower for slow/spinning disks |
| `tags.managed_prefix` | string | `"mf-"` | Prefix for all tags written by Metafin |
| `tags.dual_audio_tag` | string | `"dual-audio"` | Tag applied when exactly 2 audio languages found |
| `tags.multi_audio_tag` | string | `"re-encode"` | Tag applied when 3+ audio languages found |
| `image.targets` | list | `[poster.jpg, ...]` | Poster filenames to look for in each item folder |
| `image.backup_suffix` | string | `".orig"` | Suffix for original poster backups |
| `image.badge_position` | string | `"bottom-left"` | Position for the main badge group (resolution, audio, subtitle): bottom-left/right, top-left/right. The rating badge is always rendered top-left independently. |
| `image.badge_opacity` | float | `0.65` | Badge fill opacity (0.0–1.0) |
| `image.font_size` | int | `20` | Badge font size in pixels |
| `auth.username` | string | `"admin"` | Login username |
| `auth.password_hash` | string | `""` | bcrypt hash; empty = auto-generated on first boot |
| `log_level` | string | `"INFO"` | Logging verbosity: DEBUG, INFO, WARNING, ERROR |

---

## Badge Preview

The Settings page includes a live badge preview that renders overlays using your current color, opacity, font size, and position settings. You can preview against synthetic test posters or pull real poster images from your Jellyfin library.

---

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | No | `{"status":"ok"}` — service info when unauthenticated; full upstream connectivity status when authenticated |
| GET | `/stats` | Yes | Scan statistics and next scheduled run time |
| POST | `/scan/full` | Yes | Trigger a full library scan |
| POST | `/scan/incremental` | Yes | Trigger an incremental scan |
| POST | `/scan/cancel` | Yes | Cancel a running scan |
| GET | `/scan/status` | Yes | Current scan progress |
| GET | `/scan/stream` | Yes | Server-sent events stream of scan log |
| GET | `/media` | Yes | Paginated media browser (filter by resolution, language) |
| GET | `/api/settings` | Yes | Structured settings (password_hash redacted) |
| PUT | `/api/settings` | Yes | Save settings |
| POST | `/api/auth/change-password` | Yes | Change login password |
| GET | `/config` | Yes | Raw YAML config |
| PUT | `/config` | Yes | Save raw YAML config |
| GET | `/api/jellyfin/libraries` | Yes | List Jellyfin libraries |
| GET | `/api/sonarr/{name}/rootfolders` | Yes | List Sonarr root folders |
| GET | `/api/radarr/{name}/rootfolders` | Yes | List Radarr root folders |
| GET | `/api/preview/sample-posters` | Yes | Get poster sources for preview grid |
| GET | `/preview/image` | Yes | Render a preview badge overlay image |

---

## Authentication

- Default credentials are auto-generated on first boot and printed to the container log
- Set `METAFIN_USERNAME` / `METAFIN_PASSWORD` environment variables before first boot to use specific credentials instead
- Change password anytime in Settings → Change Password
- Sessions are signed HMAC tokens stored in a browser cookie — they survive container restarts
- Changing your password immediately invalidates all existing sessions

---

## Security

- **Session cookies**: HttpOnly, SameSite=lax, 30-day expiry, `Secure` flag on by default. Set `SECURE_COOKIES=false` in `.env` only when running over plain HTTP (local dev without a reverse proxy).
- **Rate limiting**: The login endpoint is limited to 10 attempts per minute per IP to mitigate brute-force attacks.
- **Password hashing**: bcrypt with 12 rounds. Minimum password length is 12 characters.
- **Security headers**: `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, and `X-XSS-Protection` are set on every response.
- **Session invalidation**: Changing your password immediately invalidates all sessions signed with the old credential. To force-invalidate all sessions without a password change, rotate `auth.secret_key` in `config.yml`.
- **CSRF**: Not yet implemented. `SameSite=lax` provides partial mitigation; CSRF tokens are planned for a future release.

---

## GitHub Actions (CI/CD)

Every push and pull request runs:

| Check | Tool |
|---|---|
| Python lint + format | ruff + black |
| Python SAST | bandit |
| Dependency CVE audit | pip-audit |
| Dockerfile lint | hadolint |
| Container CVE scan | Trivy |
| Deep Python SAST | CodeQL (weekly + on push/PR to main) |
| PR dependency risk | dependency-review (PRs only) |

Publishing to `ghcr.io/bpoulliot/metafin` happens automatically on semver tags (`v*.*.*`) with SBOM and provenance attestation included.

---

## Integration with Existing *arr Stacks

If you already have a Docker Compose stack with Jellyfin, Sonarr, and Radarr, attach Metafin to the same network:

```yaml
# In docker-compose.yml
networks:
  metafin-net:
    driver: bridge
  your_existing_network:   # attach to existing network so services are reachable
    external: true
```

Add `your_existing_network` to the Metafin service's `networks` list, then use container names as hostnames in `config.yml` (e.g. `http://jellyfin:8096`).

---

## Development Setup

```bash
# Start the full dev stack (Jellyfin + Sonarr + Radarr + Metafin with hot-reload)
docker compose -f docker-compose.dev.yml up -d

# Dev UI is at http://localhost:7755
# Default dev credentials: admin / metafin
```

The dev compose mounts the `app/` directory directly so code changes are picked up on the next request (uvicorn `--reload` is set in dev mode).

---

## Planned Features

- **Scan history** — per-scan record with total runtime, items scanned, items skipped, images modified, and error counts; browsable in the web UI
- **Media browser improvements** — series/movie name in the item column, audio and video codec columns (when enabled)
- **Subtitle language tagging** — detect subtitle stream languages and surface them as `mf-sub-EN` tags and badge rows on posters
- **Subtitle cleanup** — remove subtitle files/streams not matching a configured keep-list
- **Jellyfin plugin** — native Jellyfin sidebar iframe integration via a C# `BasePlugin`
- **CSRF protection** — token-based CSRF for multi-user deployments
- **Database migrations** — Alembic-based schema versioning for safe upgrades
- **Bare metal install** — installation path without Docker (requires Python 3.12, ffmpeg, DejaVu fonts)
- **Prometheus metrics** — `/metrics` endpoint for scan throughput, item counts, error rates
- **Backup/restore API** — `GET /api/backup` for state.db download; `POST /api/restore` to upload and replace
- **HTTP connection pooling** — reuse `httpx.Client` across requests for lower Jellyfin/Sonarr/Radarr API latency
- **`pillow-simd` acceleration** — drop-in Pillow replacement for 2-4× faster badge overlay rendering (requires build toolchain in Docker image)

---

## Contributing

Pull requests welcome. Please open an issue first for significant changes.

---

## License

[MIT](LICENSE)
