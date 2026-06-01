# Xenotag Roadmap

Items are scored **Value** (1–5: user/correctness impact) and **Complexity** (1–5: implementation effort).
Easy wins = high value, low complexity. Categories: **U** = user-facing behavior, **I** = infrastructure, **P** = polish/UX.

---

## In Progress

| ID | Feature | Issue |
|----|---------|-------|
| P1 | Audio language override (fix UND tracks via ffmpeg metadata) | [#21](https://github.com/bpoulliot/xenotag/issues/21) |
| P2 | Media browser: name column, codec columns | [#10](https://github.com/bpoulliot/xenotag/issues/10) |
| P3 | Scan history in web UI | [#9](https://github.com/bpoulliot/xenotag/issues/9) |

---

## Near-term

### U — User-facing

| ID | Feature | Value | Complexity | Issue |
|----|---------|:-----:|:----------:|-------|
| U1 | Tag migration: clean up legacy `mf-*` tags on upgrade from Metafin; `tags.legacy_prefixes` config option | 5 | 2 | [#35](https://github.com/bpoulliot/xenotag/issues/35) |
| U2 | Tag lifecycle: remove stale `xt-*` tags when items are deleted from Jellyfin; handle mtime-preserving re-encodes | 5 | 3 | [#36](https://github.com/bpoulliot/xenotag/issues/36) |
| U3 | Webhook / event-driven processing: per-item rescan on Sonarr/Radarr/Jellyfin Download events | 5 | 2 | [#22](https://github.com/bpoulliot/xenotag/issues/22) |
| U4 | Subtitle language tagging: write `xt-sub-*` tags to Jellyfin/Sonarr/Radarr (ffprobe extraction already exists) | 4 | 2 | [#11](https://github.com/bpoulliot/xenotag/issues/11) |

### I — Infrastructure

| ID | Feature | Value | Complexity | Issue |
|----|---------|:-----:|:----------:|-------|
| I1 | CSRF protection: form token validation on login and settings forms | 4 | 1 | [#14](https://github.com/bpoulliot/xenotag/issues/14) |
| I2 | Backup/restore API: download/upload state.db; prevents full rescan after container upgrades | 4 | 2 | [#18](https://github.com/bpoulliot/xenotag/issues/18) |
| I3 | Alembic DB migrations: structured schema versioning; required before any further schema changes | 5 | 3 | [#15](https://github.com/bpoulliot/xenotag/issues/15) |
| I4 | HTTP connection pooling for Jellyfin/Sonarr/Radarr clients | 3 | 1 | [#19](https://github.com/bpoulliot/xenotag/issues/19) |
| I5 | Prometheus metrics endpoint | 3 | 2 | [#17](https://github.com/bpoulliot/xenotag/issues/17) |
| I6 | ntfy push notifications: configurable server URL, token, and topic in settings UI; notify on scan complete, scan error, and batch tag events | 3 | 2 | — |

---

## Far-term

### U — User-facing

| ID | Feature | Value | Complexity | Issue |
|----|---------|:-----:|:----------:|-------|
| U5 | Extended ffprobe tags: video profile, bitrate tier, interlacing, frame rate | 4 | 3 | [#24](https://github.com/bpoulliot/xenotag/issues/24) |
| U6 | Extended metadata tags from Jellyfin/\*arr: genres, original language, runtime bands, series status, ratings, custom formats | 4 | 5 | [#25](https://github.com/bpoulliot/xenotag/issues/25) |

### P — Polish

| ID | Feature | Value | Complexity | Issue |
|----|---------|:-----:|:----------:|-------|
| P4 | Mobile-responsive UI: full breakpoint coverage | 3 | 2 | [#26](https://github.com/bpoulliot/xenotag/issues/26) |
| P5 | README sample screenshots and overlay examples | 2 | 1 | [#23](https://github.com/bpoulliot/xenotag/issues/23) |

### I — Infrastructure

| ID | Feature | Value | Complexity | Issue |
|----|---------|:-----:|:----------:|-------|
| I6 | pillow-simd acceleration (marginal gain; ffprobe is the bottleneck, not PIL) | 2 | 3 | [#20](https://github.com/bpoulliot/xenotag/issues/20) |

---

## Deferred / Out of Scope

| Feature | Reason |
|---------|--------|
| Outbound API rate limiting (Jellyfin/\*arr) | LAN services, no documented limits; natural scan serialization is sufficient |
| Whisper transcription integration | Out of scope; heavy model dependency; use Bazarr instead |
| Bare metal install guide | [#16](https://github.com/bpoulliot/xenotag/issues/16) — low demand, Docker is the primary path |
