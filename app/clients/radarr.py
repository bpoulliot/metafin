from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class RadarrClient:
    def __init__(self, url: str, api_key: str, name: str = "") -> None:
        self.base = url.rstrip("/")
        self.name = name or url
        self._client = httpx.Client(headers={"X-Api-Key": api_key}, timeout=30)
        self._tag_cache: dict[str, int] | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RadarrClient:
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

    def _load_tags(self) -> dict[str, int]:
        tags = self._get("/tag")
        return {t["label"]: t["id"] for t in tags}

    def _get_or_create_tag(self, label: str) -> int:
        if self._tag_cache is None:
            self._tag_cache = self._load_tags()
        if label not in self._tag_cache:
            result = self._post("/tag", {"label": label})
            self._tag_cache[label] = result["id"]
            log.info("[%s] Created Radarr tag: %s (id=%s)", self.name, label, result["id"])
        return self._tag_cache[label]

    def _tag_ids(self, labels: list[str]) -> list[int]:
        return [self._get_or_create_tag(lbl) for lbl in labels]

    def get_movies(self) -> list[dict]:
        return self._get("/movie")

    def get_movie_by_id(self, movie_id: int) -> dict:
        return self._get(f"/movie/{movie_id}")

    def set_managed_tags(self, movie_id: int, prefix: str, new_tag_labels: list[str]) -> None:
        movie = self.get_movie_by_id(movie_id)
        if self._tag_cache is None:
            self._tag_cache = self._load_tags()

        managed_ids = {tid for label, tid in self._tag_cache.items() if label.startswith(prefix)}
        current_ids: list[int] = movie.get("tags") or []
        kept = [tid for tid in current_ids if tid not in managed_ids]
        new_ids = self._tag_ids(new_tag_labels)
        merged = list(dict.fromkeys(kept + new_ids))

        if merged != current_ids:
            movie["tags"] = merged
            self._put(f"/movie/{movie_id}", movie)
            log.debug("[%s] Movie %s tags updated: %s", self.name, movie_id, new_tag_labels)
