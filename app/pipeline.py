from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .clients.jellyfin import JellyfinClient
from .clients.radarr import RadarrClient
from .clients.sonarr import SonarrClient
from .config import AppConfig
from .overlay import BadgeGroup, apply_overlay
from .scanner import MediaInfo, probe_file
from .state import (
    clear_scan_errors,
    finish_scan_run,
    get_meta,
    get_session,
    set_meta,
    start_scan_run,
    upsert_media_state,
    upsert_scan_error,
)
from .tagger import build_tags

log = logging.getLogger(__name__)


class ScanProgress:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.running = False
        self.cancelled = False
        self.total = 0
        self.done = 0
        self.current_item = ""
        self.error: str | None = None
        self.log_lines: list[str] = []
        self._callbacks: list[Callable[[str], None]] = []

    def try_start(self) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.cancelled = False
            self.total = 0
            self.done = 0
            self.current_item = ""
            self.error = None
            return True

    def cancel(self) -> bool:
        with self._lock:
            if not self.running:
                return False
            self.cancelled = True
            return True

    def finish(self, error: str | None = None) -> None:
        with self._lock:
            self.running = False
            self.error = error

    def subscribe(self, cb: Callable[[str], None]) -> None:
        with self._lock:
            self._callbacks.append(cb)

    def unsubscribe(self, cb: Callable[[str], None]) -> None:
        with self._lock:
            try:
                self._callbacks.remove(cb)
            except ValueError:
                pass

    def emit(self, msg: str) -> None:
        with self._lock:
            self.log_lines.append(msg)
            if len(self.log_lines) > 200:
                self.log_lines = self.log_lines[-200:]
            cbs = list(self._callbacks)
        for cb in cbs:
            try:
                cb(msg)
            except Exception:  # noqa: S110
                pass


progress = ScanProgress()


_TAG_CONFIG_KEY = "tag_config_hash"


def _tag_config_hash(cfg: AppConfig) -> str:
    dest = cfg.tags.destinations
    raw = (
        f"{cfg.tags.managed_prefix}|{cfg.tags.dual_audio_tag}|{cfg.tags.multi_audio_tag}"
        f"|video:{','.join(sorted(dest.video))}"
        f"|audio:{','.join(sorted(dest.audio))}"
        f"|subtitles:{','.join(sorted(dest.subtitles))}"
        f"|rating:{','.join(sorted(dest.rating))}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _clients_from_config(cfg: AppConfig) -> tuple[JellyfinClient, list[SonarrClient], list[RadarrClient]]:
    jf = JellyfinClient(cfg.jellyfin.url, cfg.jellyfin.api_key)
    sonarrs = [SonarrClient(inst.url, inst.api_key, inst.name) for inst in cfg.sonarr.instances]
    radarrs = [RadarrClient(inst.url, inst.api_key, inst.name) for inst in cfg.radarr.instances]
    return jf, sonarrs, radarrs


def _close_clients(jf: JellyfinClient, sonarrs: list[SonarrClient], radarrs: list[RadarrClient]) -> None:
    jf.close()
    for c in sonarrs:
        c.close()
    for c in radarrs:
        c.close()


def _process_one_item(
    jf: JellyfinClient,
    sonarrs: list[SonarrClient],
    radarrs: list[RadarrClient],
    session: object,
    cfg: AppConfig,
    item: dict,
    file_path: str,
    item_root: str,
    mtime: float,
    info: MediaInfo,
) -> bool:
    """Tag, overlay, and persist one media item. Returns True if an image was modified."""
    item_id = item.get("Id", "")
    name = item.get("Name", item_id)
    prefix = cfg.tags.managed_prefix

    jf_rating = item.get("OfficialRating") or ""
    arr_cert = _get_arr_certification(item, sonarrs, radarrs) if not jf_rating else ""
    content_rating = jf_rating or arr_cert or None

    jf_tags = build_tags(
        info.resolution,
        info.video_codec,
        info.hdr_type,
        info.audio_tracks,
        info.subtitle_tracks,
        content_rating,
        cfg.tags,
        destination="jellyfin",
    )
    sonarr_tags = build_tags(
        info.resolution,
        info.video_codec,
        info.hdr_type,
        info.audio_tracks,
        info.subtitle_tracks,
        content_rating,
        cfg.tags,
        destination="sonarr",
    )
    radarr_tags = build_tags(
        info.resolution,
        info.video_codec,
        info.hdr_type,
        info.audio_tracks,
        info.subtitle_tracks,
        content_rating,
        cfg.tags,
        destination="radarr",
    )

    try:
        jf.set_managed_tags(item_id, item, prefix, jf_tags, fallback_rating=arr_cert)
    except Exception as exc:
        log.warning("Jellyfin tag error for %s: %s", name, exc)

    sonarr_id = _find_arr_id(item, "Sonarr")
    if sonarr_id and sonarrs:
        for client in sonarrs:
            try:
                client.set_managed_tags(sonarr_id, prefix, sonarr_tags)
            except Exception as exc:
                log.debug("Sonarr tag error [%s] %s: %s", client.name, name, exc)

    radarr_id = _find_arr_id(item, "Radarr")
    if radarr_id and radarrs:
        for client in radarrs:
            try:
                client.set_managed_tags(radarr_id, prefix, radarr_tags)
            except Exception as exc:
                log.debug("Radarr tag error [%s] %s: %s", client.name, name, exc)

    item_folder = Path(item_root) if item_root else Path(file_path).parent
    if not item_folder.is_dir():
        item_folder = Path(file_path).parent

    groups, rating_group = _make_badge_groups(info, content_rating, cfg)
    modified_path = None
    image_modified = False
    if groups or rating_group:
        try:
            modified_path = apply_overlay(item_folder, groups, rating_group, cfg.image)
            if modified_path:
                image_modified = True
                jf.refresh_item(item_id)
        except Exception as exc:
            log.warning("Overlay error for %s: %s", name, exc)

    upsert_media_state(
        session,
        item_id=f"jellyfin:{item_id}",
        source="jellyfin",
        file_path=file_path,
        resolution=info.resolution,
        languages=info.languages,
        tags_applied=jf_tags,
        image_path=str(modified_path) if modified_path else None,
        file_mtime=mtime,
        video_codec=info.video_codec,
        hdr_type=info.hdr_type,
        audio_tracks=[{"lang": t.lang, "codec": t.codec} for t in info.audio_tracks],
        subtitle_tracks=[{"lang": t.lang, "format": t.format, "embedded": t.embedded} for t in info.subtitle_tracks],
        content_rating=content_rating,
    )

    return image_modified


def _get_file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _passes_path_filter(file_path: str, filters: list[str]) -> bool:
    if not filters:
        return True
    return any(file_path.startswith(f) for f in filters)


def _get_arr_certification(
    item: dict,
    sonarrs: list[SonarrClient],
    radarrs: list[RadarrClient],
) -> str | None:
    """Fetch certification from Sonarr/Radarr as fallback for content rating."""
    provider_ids = item.get("ProviderIds") or {}

    sonarr_id_raw = provider_ids.get("Sonarr")
    if sonarr_id_raw and sonarrs:
        try:
            sid = int(sonarr_id_raw)
        except (ValueError, TypeError):
            sid = None
        if sid:
            for client in sonarrs:
                try:
                    data = client._get(f"/series/{sid}")
                    cert = (data.get("certification") or "").strip()
                    if cert:
                        return cert
                except Exception:  # noqa: S110
                    pass

    radarr_id_raw = provider_ids.get("Radarr")
    if radarr_id_raw and radarrs:
        try:
            rid = int(radarr_id_raw)
        except (ValueError, TypeError):
            rid = None
        if rid:
            for client in radarrs:
                try:
                    data = client._get(f"/movie/{rid}")
                    cert = (data.get("certification") or "").strip()
                    if cert:
                        return cert
                except Exception:  # noqa: S110
                    pass

    return None


def _make_badge_groups(
    info: MediaInfo,
    content_rating: str | None,
    cfg: AppConfig,
) -> tuple[list[BadgeGroup], BadgeGroup | None]:
    """Build BadgeGroup list and optional rating group from MediaInfo + image config."""
    img_cfg = cfg.image
    dest = cfg.tags.destinations

    groups: list[BadgeGroup] = []

    # Video group (shown if "poster" is in video destinations and show flag is on)
    if img_cfg.show_video_badges and "poster" in dest.video:
        video_labels: list[str] = []
        if info.resolution and info.resolution != "unknown":
            video_labels.append(info.resolution)
        if info.video_codec:
            video_labels.append(info.video_codec)
        if info.hdr_type:
            video_labels.append(info.hdr_type)
        if video_labels:
            groups.append(BadgeGroup(video_labels, img_cfg.video_badge_color, img_cfg.badge_text_color))

    # Audio group — codec-first, languages grouped under each codec
    # e.g. [DTS-HD EN JA] [AC-3 DE] instead of [EN DTS-HD] [JA DTS-HD] [DE AC-3]
    if img_cfg.show_audio_badges and "poster" in dest.audio:
        codec_langs: dict[str, list[str]] = {}
        for t in info.audio_tracks:
            langs = codec_langs.setdefault(t.codec, [])
            if t.lang and t.lang != "UND":
                langs.append(t.lang)
        audio_labels = [f"{codec} {' '.join(langs)}" if langs else codec for codec, langs in codec_langs.items()]
        if audio_labels:
            groups.append(BadgeGroup(audio_labels, img_cfg.audio_badge_color, img_cfg.badge_text_color))

    # Subtitle group — format-first, languages grouped under each format
    # e.g. [PGS EN JA IT] [SRT EN] instead of [EN PGS] [JA PGS] [IT PGS] [EN SRT]
    if img_cfg.show_sub_badges and "poster" in dest.subtitles:
        fmt_langs: dict[str, list[str]] = {}
        seen_lang_fmt: set[tuple[str, str]] = set()
        for t in info.subtitle_tracks:
            key = (t.lang, t.format)
            if key in seen_lang_fmt:
                continue
            seen_lang_fmt.add(key)
            langs = fmt_langs.setdefault(t.format, [])
            if t.lang and t.lang != "UND":
                langs.append(t.lang)
        sub_labels = [f"{fmt} {' '.join(langs)}" if langs else fmt for fmt, langs in fmt_langs.items()]
        if sub_labels:
            groups.append(BadgeGroup(sub_labels, img_cfg.sub_badge_color, img_cfg.badge_text_color))

    # Rating badge (top-right, independent)
    rating_group: BadgeGroup | None = None
    if img_cfg.show_rating_badge and content_rating and "poster" in dest.rating:
        rating_group = BadgeGroup([f"Rated {content_rating}"], img_cfg.rating_badge_color, img_cfg.badge_text_color)

    return groups, rating_group


def _run_scan(cfg: AppConfig, incremental: bool) -> None:
    scan_type = "incremental" if incremental else "full"
    progress.emit(f"[metafin] Starting {scan_type} scan…")

    jf, sonarrs, radarrs = _clients_from_config(cfg)

    if not sonarrs:
        progress.emit("[metafin] No Sonarr instances configured — skipping Sonarr tagging")
    if not radarrs:
        progress.emit("[metafin] No Radarr instances configured — skipping Radarr tagging")

    session = get_session()
    run = start_scan_run(session, scan_type)

    current_hash = _tag_config_hash(cfg)
    stored_hash = get_meta(session, _TAG_CONFIG_KEY)
    tag_config_changed = stored_hash != current_hash
    if tag_config_changed and incremental:
        progress.emit("[metafin] Tag config changed — forcing full re-tag of all items")
        incremental = False

    if not incremental:
        clear_scan_errors(session)

    try:
        items = jf.get_items(cfg.jellyfin.library_ids or None)
    except Exception as exc:
        msg = f"[metafin] FATAL: Could not fetch Jellyfin items: {exc}"
        progress.emit(msg)
        log.error(msg)
        session.close()
        _close_clients(jf, sonarrs, radarrs)
        progress.finish(error=str(exc))
        return

    path_filters = cfg.scan.path_filters
    if path_filters:
        before = len(items)
        items = [
            i
            for i in items
            if _passes_path_filter(
                (i.get("MediaSources") or [{}])[0].get("Path", i.get("Path", "")),
                path_filters,
            )
        ]
        progress.emit(f"[metafin] Path filter: {before} → {len(items)} items")

    progress.total = len(items)
    progress.emit(f"[metafin] {len(items)} items to process")

    tagged = 0
    images_modified = 0

    # Preload Sonarr/Radarr series and movie catalogues in parallel so Phase 3
    # can use dict lookups instead of per-item API GETs.
    if sonarrs or radarrs:
        progress.emit("[metafin] Preloading Sonarr/Radarr catalogues…")
        workers = max(1, len(sonarrs) + len(radarrs))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(c.preload): c for c in sonarrs + radarrs}  # type: ignore[arg-type]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    log.warning("Preload failed for %s: %s", futures[future].name, exc)

    # Phase 1a: pre-resolve episode paths for ALL series in parallel.
    # We always resolve regardless of whether the series folder exists locally — the folder
    # may have moved (e.g. mount restructure) while Jellyfin still knows the episode paths.
    series_ids_needing_path: list[str] = [item.get("Id", "") for item in items if item.get("Type") == "Series"]

    resolved_episode_paths: dict[str, str] = {}
    if series_ids_needing_path:
        progress.emit(f"[metafin] Resolving episode paths for {len(series_ids_needing_path)} series…")
        workers = min(cfg.scan.max_workers, len(series_ids_needing_path))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_sid = {pool.submit(_get_first_episode_path, jf, sid): sid for sid in series_ids_needing_path}
            for future in as_completed(future_to_sid):
                sid = future_to_sid[future]
                try:
                    resolved_episode_paths[sid] = future.result() or ""
                except Exception as exc:
                    log.debug("Episode path resolution error for %s: %s", sid, exc)
                    resolved_episode_paths[sid] = ""

    # Phase 1b: filter already-current items (sequential — SQLite reads)
    log.info("Phase 1b: checking %d items (mtime filter, network stat calls)…", len(items))
    progress.emit(f"[metafin] Phase 1b: checking {len(items)} items…")
    to_probe: list[tuple[dict, str, str, float]] = []  # (item, file_path, item_root, mtime)
    _checked = 0
    for item in items:
        _checked += 1
        if _checked % 1000 == 0:
            progress.emit(f"[metafin] Checked {_checked}/{len(items)} items…")
        if progress.cancelled:
            progress.emit("[metafin] Scan cancelled by user")
            break

        item_id = item.get("Id", "")
        name = item.get("Name", item_id)

        media_sources = item.get("MediaSources") or []
        file_path = media_sources[0].get("Path", "") if media_sources else ""
        if not file_path:
            file_path = item.get("Path", "")

        item_root = item.get("Path", "")
        if item.get("Type") == "Series":
            resolved = resolved_episode_paths.get(item_id, "")
            if resolved:
                item_root = file_path if (file_path and Path(file_path).is_dir()) else ""
                file_path = resolved

        if not file_path or not Path(file_path).exists():
            error_type = "no_path" if not file_path else "no_file"
            msg = f"skip ({error_type}): {name} | path tried: {file_path or '(empty)'}"
            progress.emit(f"  {msg}")
            log.warning(msg)
            upsert_scan_error(session, item_id, name, file_path or "", error_type)
            progress.done += 1
            continue

        mtime = _get_file_mtime(file_path)

        if incremental:
            from . import state as _state

            existing = session.get(_state.MediaState, f"jellyfin:{item_id}")
            if existing and existing.file_mtime == mtime:
                progress.done += 1
                continue

        to_probe.append((item, file_path, item_root, mtime))

    # Phase 2: parallel ffprobe — pure I/O, no shared state writes
    # Each to_probe item contributes 0.5 in Phase 2 and 0.5 in Phase 3,
    # so total stays at len(items) and the label always shows real item counts.
    log.info("Phase 1b complete: %d items queued for probe", len(to_probe))
    max_workers = min(cfg.scan.max_workers, max(1, len(to_probe)))
    probe_results: dict[str, MediaInfo | None] = {}
    if to_probe:
        total_probe = len(to_probe)
        log.info("Phase 2: probing %d files with %d workers…", total_probe, max_workers)
        progress.emit(f"[metafin] Probing {total_probe} files with {max_workers} workers…")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_path = {pool.submit(probe_file, fp): fp for _, fp, _, _ in to_probe}
            probed = 0
            for future in as_completed(future_to_path):
                if progress.cancelled:
                    progress.emit("[metafin] Scan cancelled by user")
                    break
                fp = future_to_path[future]
                try:
                    probe_results[fp] = future.result()
                except Exception as exc:
                    log.warning("probe_file error for %s: %s", fp, exc)
                    probe_results[fp] = None
                probed += 1
                progress.done += 0.5
                if probed % 100 == 0 or probed == total_probe:
                    progress.emit(f"[metafin] Probed {probed}/{total_probe} files…")

    # Phase 3: tag, overlay, and persist results (sequential — SQLite writes, API calls)
    log.info("Phase 3: tagging %d items…", len(to_probe))
    try:
        for item, file_path, item_root, mtime in to_probe:
            if progress.cancelled:
                progress.emit("[metafin] Scan cancelled by user")
                break

            item_id = item.get("Id", "")
            name = item.get("Name", item_id)
            progress.current_item = name

            info = probe_results.get(file_path)
            if info is None:
                progress.emit(f"  ffprobe failed: {name} | path: {file_path}")
                upsert_scan_error(session, item_id, name, file_path, "probe_failed")
                progress.done += 0.5
                continue

            progress.emit(f"  scanning: {name}")

            try:
                image_modified = _process_one_item(
                    jf, sonarrs, radarrs, session, cfg, item, file_path, item_root, mtime, info
                )
            except Exception as exc:
                log.error("Unhandled error processing %s: %s", name, exc, exc_info=True)
                upsert_scan_error(session, item_id, name, file_path, f"process_error: {exc}")
                progress.done += 0.5
                continue

            tagged += 1
            images_modified += image_modified

            progress.emit(
                f"  done: {name} | {info.resolution} | {info.video_codec or '-'} | {info.hdr_type or '-'}"
                f" | audio: {len(info.audio_tracks)} | subs: {len(info.subtitle_tracks)}"
            )
            progress.done += 0.5
    finally:
        set_meta(session, _TAG_CONFIG_KEY, current_hash)
        finish_scan_run(session, run, scanned=len(items), tagged=tagged, images=images_modified)
        session.close()
        _close_clients(jf, sonarrs, radarrs)
        progress.finish()
        progress.emit(f"[metafin] Scan complete — scanned={len(items)}, tagged={tagged}, images={images_modified}")


def _get_first_episode_path(jf: JellyfinClient, series_id: str) -> str | None:
    try:
        data = jf._get(
            "/Items",
            ParentId=series_id,
            Recursive="true",
            IncludeItemTypes="Episode",
            Fields="Path,MediaSources",
            SortBy="SortName",
            SortOrder="Ascending",
            Limit=1,
        )
        eps = data.get("Items", [])
        if not eps:
            return None
        ep = eps[0]
        sources = ep.get("MediaSources") or []
        path = sources[0].get("Path", "") if sources else ""
        return path or ep.get("Path", "") or None
    except Exception as exc:
        log.debug("Could not resolve episode path for series %s: %s", series_id, exc)
        return None


def _find_arr_id(item: dict, provider: str) -> int | None:
    provider_ids: dict = item.get("ProviderIds") or {}
    raw = provider_ids.get(provider)
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return None


def run_full_scan(cfg: AppConfig) -> None:
    if not progress.try_start():
        log.warning("Scan already in progress, skipping")
        return
    _run_scan(cfg, incremental=False)


def run_incremental_scan(cfg: AppConfig) -> None:
    if not progress.try_start():
        log.warning("Scan already in progress, skipping")
        return
    _run_scan(cfg, incremental=True)


def _resolve_webhook_jf_item(jf: JellyfinClient, source: str, payload: dict) -> dict | None:
    """Resolve the Jellyfin item dict from an inbound webhook payload."""
    if source == "jellyfin":
        item_id = payload.get("ItemId") or payload.get("item_id")
        if not item_id:
            return None
        return jf.get_item_by_id(item_id) or None

    if source == "sonarr":
        series = payload.get("series") or {}
        tvdb_id = series.get("tvdbId")
        if tvdb_id:
            return jf.find_item_by_provider_id("Tvdb", str(tvdb_id))
        return None

    if source == "radarr":
        movie = payload.get("movie") or {}
        tmdb_id = movie.get("tmdbId")
        if tmdb_id:
            return jf.find_item_by_provider_id("Tmdb", str(tmdb_id))
        return None

    return None


def handle_webhook(cfg: AppConfig, source: str, payload: dict) -> None:
    """Background task: resolve, probe, tag, and overlay a single item from a webhook event."""
    jf, sonarrs, radarrs = _clients_from_config(cfg)
    try:
        item = _resolve_webhook_jf_item(jf, source, payload)
        if not item:
            log.info("Webhook %s: could not resolve Jellyfin item from payload", source)
            return

        item_id = item.get("Id", "")
        name = item.get("Name", item_id)

        media_sources = item.get("MediaSources") or []
        file_path = media_sources[0].get("Path", "") if media_sources else item.get("Path", "")
        item_root = item.get("Path", "")

        if item.get("Type") == "Series" and file_path and Path(file_path).is_dir():
            item_root = file_path
            file_path = _get_first_episode_path(jf, item_id) or ""

        if not file_path or not Path(file_path).exists():
            log.warning("Webhook %s: no accessible file for %s", source, name)
            return

        mtime = _get_file_mtime(file_path)
        info = probe_file(file_path)
        if not info:
            log.warning("Webhook %s: ffprobe failed for %s", source, name)
            return

        session = get_session()
        image_modified = _process_one_item(jf, sonarrs, radarrs, session, cfg, item, file_path, item_root, mtime, info)
        session.close()
        log.info("Webhook %s: processed %s | image_modified=%s", source, name, image_modified)
    except Exception as exc:
        log.error("Webhook %s handler error: %s", source, exc)
    finally:
        _close_clients(jf, sonarrs, radarrs)
