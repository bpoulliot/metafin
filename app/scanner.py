from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# ISO 639-2 (3-letter) → ISO 639-1 (2-letter uppercase)
LANG_MAP: dict[str, str] = {
    "eng": "EN",
    "jpn": "JA",
    "fre": "FR",
    "fra": "FR",
    "ger": "DE",
    "deu": "DE",
    "spa": "ES",
    "ita": "IT",
    "por": "PT",
    "rus": "RU",
    "chi": "ZH",
    "zho": "ZH",
    "kor": "KO",
    "ara": "AR",
    "hin": "HI",
    "pol": "PL",
    "nld": "NL",
    "swe": "SV",
    "nor": "NO",
    "dan": "DA",
    "fin": "FI",
    "tur": "TR",
    "heb": "HE",
    "hun": "HU",
    "ces": "CS",
    "cze": "CS",
    "ron": "RO",
    "rum": "RO",
    "tha": "TH",
    "vie": "VI",
    "ind": "ID",
    "msa": "MS",
    "ukr": "UK",
    "hrv": "HR",
    "bul": "BG",
    "cat": "CA",
    "slk": "SK",
    "slo": "SK",
    "slv": "SL",
    "lit": "LT",
    "lav": "LV",
    "est": "ET",
}

RESOLUTION_THRESHOLDS = [
    (3840, "4K"),
    (1920, "1080p"),
    (1280, "720p"),
    (854, "480p"),
]

_VIDEO_CODEC_MAP = {
    "h264": "H.264",
    "avc": "H.264",
    "hevc": "H.265",
    "h265": "H.265",
    "av1": "AV1",
    "vp9": "VP9",
    "mpeg2video": "MPEG-2",
    "mpeg4": "MPEG-4",
    "vc1": "VC-1",
}

_AUDIO_CODEC_MAP = {
    "truehd": "TrueHD",
    "eac3": "DD+",
    "ac3": "DD",
    "dts": "DTS",
    "aac": "AAC",
    "mp3": "MP3",
    "flac": "FLAC",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "pcm_s16le": "PCM",
    "pcm_s24le": "PCM",
    "pcm_s32le": "PCM",
}

_AUDIO_QUALITY_RANK: dict[str, int] = {
    label: idx
    for idx, label in enumerate(
        [
            "TrueHD Atmos",
            "TrueHD",
            "DTS-X",
            "DTS-HD",
            "DD+ Atmos",
            "DTS",
            "DD+",
            "DD",
            "FLAC",
            "Opus",
            "AAC",
            "Vorbis",
            "MP3",
            "PCM",
        ]
    )
}

_SUB_FORMAT_MAP = {
    "hdmv_pgs_subtitle": "PGS",
    "pgssub": "PGS",
    "dvd_subtitle": "VOB",
    "dvdsub": "VOB",
    "subrip": "SRT",
    "srt": "SRT",
    "ass": "SSA",
    "ssa": "SSA",
    "webvtt": "VTT",
    "vtt": "VTT",
    "mov_text": "TX3G",
    "microdvd": "SUB",
}

_EXTERNAL_SUB_EXTS = {".srt", ".ass", ".ssa", ".sub", ".vtt", ".sup"}


@dataclass
class AudioTrack:
    lang: str  # "EN", "JA", "UND"
    codec: str  # "DTS-HD", "TrueHD Atmos", "AAC", etc.


@dataclass
class SubTrack:
    lang: str  # "EN", "FR", "UND"
    format: str  # "PGS", "SRT", "ASS", "VOB", "VTT"
    embedded: bool  # True = stream in container; False = external sidecar


@dataclass
class MediaInfo:
    resolution: str
    languages: list[str]  # ordered unique ISO 639-1 codes (backward compat)
    raw_audio_langs: list[str]  # raw 3-letter codes from ffprobe (backward compat)
    video_codec: str | None  # "H.265", "H.264", "AV1", etc.
    hdr_type: str | None  # "HDR10", "HLG", "HDR10+", "DV", or None
    audio_tracks: list[AudioTrack]  # deduped: best codec per language
    subtitle_tracks: list[SubTrack]  # all embedded + external subs


def probe_file(path: str | Path) -> MediaInfo | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-probesize",
        "10M",
        "-analyzeduration",
        "5000000",
        "-print_format",
        "json",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        log.error("ffprobe not found — is ffmpeg installed?")
        return None
    except subprocess.TimeoutExpired:
        log.warning("ffprobe timed out on %s", path)
        return None

    if result.returncode != 0:
        stderr = result.stderr.strip()[:500]
        log.warning("ffprobe failed on %s:\n%s", path, stderr or "(no stderr output)")
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        log.warning("ffprobe returned invalid JSON for %s", path)
        return None

    streams = data.get("streams", [])
    resolution = _detect_resolution(streams)
    languages, raw = _detect_languages(streams)
    video_codec = _detect_video_codec(streams)
    hdr_type = _detect_hdr(streams)
    audio_tracks = _detect_audio_tracks(streams)
    subtitle_tracks = _detect_subtitle_tracks(streams)
    subtitle_tracks += _detect_external_subs(Path(path))

    return MediaInfo(
        resolution=resolution,
        languages=languages,
        raw_audio_langs=raw,
        video_codec=video_codec,
        hdr_type=hdr_type,
        audio_tracks=audio_tracks,
        subtitle_tracks=subtitle_tracks,
    )


def _detect_resolution(streams: list[dict]) -> str:
    for s in streams:
        if s.get("codec_type") == "video":
            width = s.get("width", 0)
            for threshold, label in RESOLUTION_THRESHOLDS:
                if width >= threshold:
                    return label
            return "SD"
    return "unknown"


def _detect_languages(streams: list[dict]) -> tuple[list[str], list[str]]:
    seen: dict[str, None] = {}
    raw: list[str] = []
    for s in streams:
        if s.get("codec_type") != "audio":
            continue
        tags = s.get("tags") or {}
        lang3 = (tags.get("language") or "").lower().strip()
        raw.append(lang3)
        if not lang3 or lang3 in ("und", "unknown", ""):
            continue
        lang2 = LANG_MAP.get(lang3, lang3[:2].upper() if len(lang3) >= 2 else lang3.upper())
        seen[lang2] = None
    return list(seen.keys()), raw


def _detect_video_codec(streams: list[dict]) -> str | None:
    for s in streams:
        if s.get("codec_type") == "video":
            name = (s.get("codec_name") or "").lower()
            return _VIDEO_CODEC_MAP.get(name)
    return None


def _detect_hdr(streams: list[dict]) -> str | None:
    for s in streams:
        if s.get("codec_type") != "video":
            continue
        side_data = s.get("side_data_list") or []
        side_types = [str(d.get("type", "")).lower() for d in side_data]

        # Priority: DV > HDR10+ > HDR10 > HLG
        for t in side_types:
            if "dovi" in t or "dolby vision" in t:
                return "DV"
        for t in side_types:
            if "smpte2094-40" in t or "hdr dynamic" in t:
                return "HDR10+"

        color_space = (s.get("color_space") or "").lower()
        color_transfer = (s.get("color_transfer") or "").lower()
        is_bt2020 = "bt2020" in color_space

        if is_bt2020 and color_transfer == "smpte2084":
            return "HDR10"
        if is_bt2020 and color_transfer == "arib-std-b67":
            return "HLG"
    return None


def _normalize_audio_codec(s: dict) -> str:
    name = (s.get("codec_name") or "").lower()
    profile = (s.get("profile") or "").lower()
    channel_layout = (s.get("channel_layout") or "").lower()
    side_data = s.get("side_data_list") or []
    side_types = [str(d.get("type", "")).lower() for d in side_data]

    if name == "truehd":
        if any("atmos" in t for t in side_types):
            return "TrueHD Atmos"
        return "TrueHD"

    if name == "eac3":
        # Atmos over EAC3: bitstream_id 16 + 7.x channel layout
        bitstream_id = s.get("bitstream_id", 0)
        if bitstream_id == 16 and "7" in channel_layout:
            return "DD+ Atmos"
        return "DD+"

    if name == "dts":
        for t in side_types:
            if "dts:x" in t:
                return "DTS-X"
        if profile in ("dts-hd ma", "dts_ma", "dts_hra", "dts-hd hra"):
            return "DTS-HD"
        return "DTS"

    return _AUDIO_CODEC_MAP.get(name, name.upper() if name else "?")


def _lang3_to_lang2(lang3: str) -> str:
    lang3 = lang3.lower().strip()
    if not lang3 or lang3 in ("und", "unknown", ""):
        return "UND"
    return LANG_MAP.get(lang3, lang3[:2].upper() if len(lang3) >= 2 else lang3.upper())


def _detect_audio_tracks(streams: list[dict]) -> list[AudioTrack]:
    # Collect all audio tracks
    all_tracks: list[tuple[str, str]] = []  # (lang2, codec)
    for s in streams:
        if s.get("codec_type") != "audio":
            continue
        tags = s.get("tags") or {}
        lang3 = (tags.get("language") or "").lower().strip()
        lang2 = _lang3_to_lang2(lang3)
        codec = _normalize_audio_codec(s)
        all_tracks.append((lang2, codec))

    # Dedup: for each language keep the highest-ranked codec
    best: dict[str, str] = {}
    for lang2, codec in all_tracks:
        if lang2 not in best:
            best[lang2] = codec
        else:
            current_rank = _AUDIO_QUALITY_RANK.get(best[lang2], 999)
            new_rank = _AUDIO_QUALITY_RANK.get(codec, 999)
            if new_rank < current_rank:
                best[lang2] = codec

    # Preserve original track order (first occurrence of each lang)
    seen: dict[str, None] = {}
    ordered: list[AudioTrack] = []
    for lang2, _ in all_tracks:
        if lang2 not in seen:
            seen[lang2] = None
            ordered.append(AudioTrack(lang=lang2, codec=best[lang2]))
    return ordered


def _detect_subtitle_tracks(streams: list[dict]) -> list[SubTrack]:
    tracks: list[SubTrack] = []
    for s in streams:
        if s.get("codec_type") != "subtitle":
            continue
        tags = s.get("tags") or {}
        lang3 = (tags.get("language") or "").lower().strip()
        lang2 = _lang3_to_lang2(lang3)
        codec_name = (s.get("codec_name") or "").lower()
        fmt = _SUB_FORMAT_MAP.get(codec_name, codec_name.upper() if codec_name else "?")
        tracks.append(SubTrack(lang=lang2, format=fmt, embedded=True))
    return tracks


def _detect_external_subs(video_path: Path) -> list[SubTrack]:
    tracks: list[SubTrack] = []
    try:
        parent = video_path.parent
        stem = video_path.stem
        for f in parent.iterdir():
            if f.suffix.lower() not in _EXTERNAL_SUB_EXTS:
                continue
            if not f.stem.startswith(stem):
                continue
            fmt = _SUB_FORMAT_MAP.get(f.suffix.lower().lstrip("."), f.suffix.upper().lstrip("."))
            # Infer language from filename suffix: Movie.en.srt → "en"
            remainder = f.stem[len(stem) :].lstrip(".")
            parts = remainder.split(".")
            lang2 = "UND"
            for part in parts:
                part = part.lower().strip()
                if part and len(part) in (2, 3):
                    lang2 = _lang3_to_lang2(part) if len(part) == 3 else part.upper()
                    break
            tracks.append(SubTrack(lang=lang2, format=fmt, embedded=False))
    except Exception as exc:
        log.debug("External sub scan failed for %s: %s", video_path, exc)
    return tracks
