from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class SonarrClient:
    def __init__(self, url: str, api_key: str, name: str = "") -> None:
        self.base = url.rstrip("/")
        self.name = name or url
        self._client = httpx.Client(headers={"X-Api-Key": api_key}, timeout=30)
        self._tag_cache: dict[str, int] | None = None  # label → id

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SonarrClient:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _get(self, path: str, **params) -> Any:
        r = self._client.get(f"{self.base}/api/v3{path}", params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, json: dict) -> Any:
        r = self._client.post(f"{self.base}/api/v3{path}", json=json)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, json: dict) -> Any:
        r = self._client.put(f"{self.base}/api/v3{path}", json=json)
        r.raise_for_status()
        return r.json()

    def health(self) -> dict:
        """Return {"ok": bool, "status": str, "message": str}."""
        try:
            r = self._client.get(f"{self.base}/ping", timeout=5)
            if r.status_code == 200:
                return {"ok": True, "status": "healthy", "message": "Healthy"}
            if r.status_code in (401, 403):
                return {"ok": False, "status": "auth_error", "message": "Invalid API key"}
            return {"ok": False, "status": "error", "message": f"HTTP {r.status_code}"}
        except httpx.TimeoutException:
            return {"ok": False, "status": "timeout", "message": "Timed out"}
        except Exception:
            return {"ok": False, "status": "unreachable", "message": "Unreachable"}

    # --- tag management ---

    def _load_tags(self) -> dict[str, int]:
        tags = self._get("/tag")
        return {t["label"]: t["id"] for t in tags}

    def _get_or_create_tag(self, label: str) -> int:
        if self._tag_cache is None:
            self._tag_cache = self._load_tags()
        if label not in self._tag_cache:
            result = self._post("/tag", {"label": label})
            self._tag_cache[label] = result["id"]
            log.info("[%s] Created Sonarr tag: %s (id=%s)", self.name, label, result["id"])
        return self._tag_cache[label]

    def _tag_ids(self, labels: list[str]) -> list[int]:
        return [self._get_or_create_tag(lbl) for lbl in labels]

    # --- series ---

    def get_series(self) -> list[dict]:
        return self._get("/series")

    def get_series_by_id(self, series_id: int) -> dict:
        return self._get(f"/series/{series_id}")

    def set_managed_tags(self, series_id: int, prefix: str, new_tag_labels: list[str]) -> None:
        series = self.get_series_by_id(series_id)
        if self._tag_cache is None:
            self._tag_cache = self._load_tags()

        # IDs of tags this tool manages (those whose label starts with prefix)
        managed_ids = {tid for label, tid in self._tag_cache.items() if label.startswith(prefix)}
        current_ids: list[int] = series.get("tags") or []

        # Remove managed, add new
        kept = [tid for tid in current_ids if tid not in managed_ids]
        new_ids = self._tag_ids(new_tag_labels)
        merged = list(dict.fromkeys(kept + new_ids))  # dedup, preserve order

        if merged != current_ids:
            series["tags"] = merged
            self._put(f"/series/{series_id}", series)
            log.debug("[%s] Series %s tags updated: %s", self.name, series_id, new_tag_labels)
