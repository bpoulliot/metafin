from __future__ import annotations

from pydantic import BaseModel


class ScanStatusResponse(BaseModel):
    running: bool
    cancelled: bool = False
    total: int
    done: int
    current_item: str
    error: str | None = None


class StatsResponse(BaseModel):
    total_tagged: int
    images_modified: int
    last_scan_at: str | None
    last_scan_type: str | None
    next_scan_at: str | None


class MediaItem(BaseModel):
    item_id: str
    source: str
    file_path: str | None
    resolution: str | None
    languages: list[str]
    tags_applied: list[str]
    image_path: str | None
    last_scanned: str | None


class ConfigResponse(BaseModel):
    yaml: str


class ConfigSaveRequest(BaseModel):
    yaml: str


class HealthResponse(BaseModel):
    status: str
    jellyfin: dict  # {ok, status, message}
    sonarr: list[dict]  # [{name, ok, status, message}, ...]
    radarr: list[dict]
