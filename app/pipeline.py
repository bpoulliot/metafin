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
        rating_group = BadgeGroup([content_rating], img_cfg.rating_badge_color, img_cfg.badge_text_color)

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
    prefix = cfg.tags.managed_prefix

    # Phase 1a: pre-resolve episode paths for all series in parallel (I/O-bound network calls)
    series_ids_needing_path: list[str] = []
    for item in items:
        if item.get("Type") != "Series":
            continue
        media_sources = item.get("MediaSources") or []
        fp = media_sources[0].get("Path", "") if media_sources else item.get("Path", "")
        if fp and Path(fp).is_dir():
            series_ids_needing_path.append(item.get("Id", ""))

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
    to_probe: list[tuple[dict, str, str, float]] = []  # (item, file_path, item_root, mtime)
    for item in items:
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
        if item.get("Type") == "Series" and file_path and Path(file_path).is_dir():
            item_root = file_path
            file_path = resolved_episode_paths.get(item_id, "")

        if not file_path or not Path(file_path).exists():
            msg = f"skip (no file): {name} | path tried: {file_path or '(empty)'}"
            progress.emit(f"  {msg}")
            log.warning(msg)
            if file_path:  # only record when a path was returned but doesn't exist
                upsert_scan_error(session, item_id, name, file_path, "no_file")
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
    # progress.done is incremented here as each future completes so the UI stays live
    max_workers = min(cfg.scan.max_workers, max(1, len(to_probe)))
    probe_results: dict[str, MediaInfo | None] = {}
    if to_probe:
        progress.emit(f"[metafin] Probing {len(to_probe)} files with {max_workers} workers…")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_path = {pool.submit(probe_file, fp): fp for _, fp, _, _ in to_probe}
            for future in as_completed(future_to_path):
                fp = future_to_path[future]
                try:
                    probe_results[fp] = future.result()
                except Exception as exc:
                    log.warning("probe_file error for %s: %s", fp, exc)
                    probe_results[fp] = None
                progress.done += 1

    # Phase 3: tag, overlay, and persist results (sequential — SQLite writes, API calls)
    # progress.done was already advanced in Phase 2; reset current_item only
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
            continue

        progress.emit(f"  scanning: {name}")

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
            fresh = jf.get_item_by_id(item_id) or item
            jf.set_managed_tags(item_id, fresh, prefix, jf_tags, fallback_rating=arr_cert)
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

        tagged += 1

        item_folder = Path(item_root) if item_root else Path(file_path).parent
        if not item_folder.is_dir():
            item_folder = Path(file_path).parent

        groups, rating_group = _make_badge_groups(info, content_rating, cfg)
        modified_path = None
        if groups or rating_group:
            try:
                modified_path = apply_overlay(item_folder, groups, rating_group, cfg.image)
                if modified_path:
                    images_modified += 1
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
            subtitle_tracks=[
                {"lang": t.lang, "format": t.format, "embedded": t.embedded} for t in info.subtitle_tracks
            ],
            content_rating=content_rating,
        )

        progress.emit(
            f"  done: {name} | {info.resolution} | {info.video_codec or '-'} | {info.hdr_type or '-'}"
            f" | audio: {len(info.audio_tracks)} | subs: {len(info.subtitle_tracks)}"
            f" | tags: {jf_tags}"
        )

    set_meta(session, _TAG_CONFIG_KEY, current_hash)
    finish_scan_run(session, run, scanned=len(items), tagged=tagged, images=images_modified)
    session.close()
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
