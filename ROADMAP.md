# Metafin Roadmap

Planned features in rough priority order. Each item links to its tracking issue.

## In Progress / Near-term

| # | Feature | Issue |
|---|---------|-------|
| - | Audio language override (fix UND tracks via ffmpeg metadata) | [#21](https://github.com/bpoulliot/metafin/issues/21) |
| - | Media browser: name column, codec columns | [#10](https://github.com/bpoulliot/metafin/issues/10) |
| - | Scan history in web UI | [#9](https://github.com/bpoulliot/metafin/issues/9) |

## Approved

| # | Feature | Issue |
|---|---------|-------|
| 1 | Event-driven processing: webhook endpoint for Sonarr/Radarr/Jellyfin Download events | [#22](https://github.com/bpoulliot/metafin/issues/22) |
| 2 | README sample screenshots and overlay examples | [#23](https://github.com/bpoulliot/metafin/issues/23) |
| 3 | Extended ffprobe tags: video profile, bitrate tier, interlacing, frame rate | [#24](https://github.com/bpoulliot/metafin/issues/24) |
| 4 | Extended metadata tags from Jellyfin/\*arr: genres, original language, runtime bands, series status, ratings, custom formats | [#25](https://github.com/bpoulliot/metafin/issues/25) |
| 5 | Mobile-responsive UI: full breakpoint coverage | [#26](https://github.com/bpoulliot/metafin/issues/26) |
| 6 | pillow-simd acceleration | [#20](https://github.com/bpoulliot/metafin/issues/20) |
| 7 | HTTP connection pooling for Jellyfin/Sonarr/Radarr clients | [#19](https://github.com/bpoulliot/metafin/issues/19) |
| 8 | Backup/restore API (state.db) | [#18](https://github.com/bpoulliot/metafin/issues/18) |
| 9 | Prometheus metrics endpoint | [#17](https://github.com/bpoulliot/metafin/issues/17) |
| 10 | Database migrations via Alembic | [#15](https://github.com/bpoulliot/metafin/issues/15) |
| 11 | CSRF protection | [#14](https://github.com/bpoulliot/metafin/issues/14) |
| 12 | Subtitle language tagging | [#11](https://github.com/bpoulliot/metafin/issues/11) |

## Deferred / Out of Scope

| Feature | Reason |
|---------|--------|
| Outbound API rate limiting (Jellyfin/\*arr) | LAN services, no documented limits; natural scan serialization is sufficient |
| Whisper transcription integration | Out of scope; heavy model dependency; use Bazarr instead |
| Bare metal install guide | [#16](https://github.com/bpoulliot/metafin/issues/16) — low demand, Docker is primary path |
