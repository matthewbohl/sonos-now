from __future__ import annotations

import json
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from time import monotonic
from typing import Any

import requests


EVERY_NOISE_BASE = "https://everynoise.com"
SPOTIFY_BASE = "https://api.spotify.com/v1"
DEFAULT_CACHE_TTL_SECONDS = 3 * 24 * 60 * 60
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class GenreResult:
    genre: str
    score: float
    matched_artist: str
    matched_artist_id: str
    rank: int | None = None
    artists: tuple[str, ...] = ()


class EveryNoiseClient:
    def __init__(
        self,
        timeout: float = 8.0,
        cache_path: Path | None = None,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self.timeout = timeout
        self.cache_path = cache_path or _default_cache_path()
        self.cache_ttl_seconds = cache_ttl_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 sonos-ascii-ui",
                "Referer": f"{EVERY_NOISE_BASE}/research.html",
            }
        )
        self._spotify_token = ""
        self._spotify_token_expires_at = 0.0
        self._artist_search_cache: dict[str, list[dict[str, Any]]] = {}
        self._artist_genre_cache: dict[str, tuple[str, ...]] = {}
        self._genre_artist_cache: dict[str, tuple[dict[str, Any], ...]] = {}
        self._similar_artist_cache: dict[str, tuple[str, ...]] = {}
        self._cache_timestamps: dict[str, dict[str, float]] = {
            "artist_search_cache": {},
            "artist_genre_cache": {},
            "genre_artist_cache": {},
            "similar_artist_cache": {},
        }
        self._load_cache()

    def search_artist_genres(self, artist: str, limit: int = 8) -> tuple[GenreResult, ...]:
        query = artist.strip()
        if not query:
            return ()

        candidates = self._search_spotify_artists(query, limit=limit)
        results: dict[str, GenreResult] = {}
        for candidate in candidates:
            candidate_id = str(candidate.get("id") or "")
            candidate_name = str(candidate.get("name") or "")
            if not candidate_id or not candidate_name:
                continue

            name_score = _artist_match_score(query, candidate_name)
            if name_score < 0.48:
                continue

            popularity = float(candidate.get("popularity") or 0)
            genres = self._artist_genres(candidate_id)
            for genre_index, genre in enumerate(genres):
                ranked_artists = self.genre_artists(genre)
                rank = _rank_for_artist(ranked_artists, candidate_id, candidate_name)
                rank_bonus = 0.0 if rank is None else max(0.0, 30.0 - min(rank, 300) / 10.0)
                genre_position_bonus = max(0.0, 12.0 - genre_index)
                score = (name_score * 100.0) + (popularity / 8.0) + rank_bonus + genre_position_bonus
                artists = tuple(str(item.get("name") or "") for item in ranked_artists if item.get("name"))
                result = GenreResult(
                    genre=genre,
                    score=score,
                    matched_artist=candidate_name,
                    matched_artist_id=candidate_id,
                    rank=rank,
                    artists=artists,
                )
                previous = results.get(genre)
                if previous is None or result.score > previous.score:
                    results[genre] = result

        return tuple(sorted(results.values(), key=lambda item: (-item.score, item.genre.casefold())))

    def similar_artists(self, artist: str, limit: int = 8) -> tuple[str, ...]:
        key = artist.strip().casefold()
        if not key:
            return ()
        if key in self._similar_artist_cache:
            return self._similar_artist_cache[key][:limit]

        results = self.search_artist_genres(artist)
        scored: dict[str, float] = {}
        source_names = {_normalize_artist(artist)}
        source_names.update(_normalize_artist(result.matched_artist) for result in results)

        for genre_index, result in enumerate(results[:6]):
            genre_weight = max(1.0, result.score / 10.0) + max(0.0, 6.0 - genre_index)
            for artist_index, similar_artist in enumerate(result.artists[:80]):
                if _normalize_artist(similar_artist) in source_names:
                    continue
                score = genre_weight / (artist_index + 1)
                scored[similar_artist] = scored.get(similar_artist, 0.0) + score

        similar = tuple(
            name
            for name, _score in sorted(scored.items(), key=lambda item: (-item[1], item[0].casefold()))
        )
        self._similar_artist_cache[key] = similar
        self._touch_cache_key("similar_artist_cache", key)
        self._save_cache()
        return similar[:limit]

    def genre_artists(self, genre: str) -> tuple[dict[str, Any], ...]:
        key = genre.strip().casefold()
        if key in self._genre_artist_cache:
            return self._genre_artist_cache[key]

        response = self.session.get(
            f"{EVERY_NOISE_BASE}/api/genre/{genre}",
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        artists = tuple(payload.get(genre, payload.get(genre.lstrip("*"), ())) or ())
        self._genre_artist_cache[key] = artists
        self._touch_cache_key("genre_artist_cache", key)
        self._save_cache()
        return artists

    def _search_spotify_artists(self, artist: str, limit: int) -> list[dict[str, Any]]:
        key = f"{artist.casefold()}:{limit}"
        if key in self._artist_search_cache:
            return self._artist_search_cache[key]

        response = self.session.get(
            f"{SPOTIFY_BASE}/search",
            params={"type": "artist", "q": artist, "limit": limit},
            headers={"Authorization": f"Bearer {self._spotify_auth_token()}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        artists = list(response.json().get("artists", {}).get("items", ()))
        self._artist_search_cache[key] = artists
        self._touch_cache_key("artist_search_cache", key)
        self._save_cache()
        return artists

    def _artist_genres(self, artist_id: str) -> tuple[str, ...]:
        if artist_id in self._artist_genre_cache:
            return self._artist_genre_cache[artist_id]

        response = self.session.get(
            f"{EVERY_NOISE_BASE}/api/{artist_id}",
            timeout=self.timeout,
        )
        response.raise_for_status()
        genres = tuple(str(genre) for genre in response.json().get(artist_id, ()) if genre)
        self._artist_genre_cache[artist_id] = genres
        self._touch_cache_key("artist_genre_cache", artist_id)
        self._save_cache()
        return genres

    def _spotify_auth_token(self) -> str:
        if self._spotify_token and monotonic() < self._spotify_token_expires_at:
            return self._spotify_token

        response = self.session.get(
            f"{EVERY_NOISE_BASE}/spotify_auth.cgi",
            params={"action": "accesstoken", "secret": "fetch"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        self._spotify_token = str(payload["access_token"])
        self._spotify_token_expires_at = monotonic() + max(60, int(payload.get("expires_in", 3600)) - 60)
        return self._spotify_token

    def _load_cache(self) -> None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        schema_version = payload.get("schema_version")
        if schema_version == 1:
            self._load_legacy_cache(payload)
            return
        if schema_version != SCHEMA_VERSION:
            return

        self._artist_search_cache = self._load_timed_cache(
            payload,
            "artist_search_cache",
            lambda value: list(value),
        )
        self._artist_genre_cache = self._load_timed_cache(
            payload,
            "artist_genre_cache",
            lambda value: tuple(str(item) for item in value),
        )
        self._genre_artist_cache = self._load_timed_cache(
            payload,
            "genre_artist_cache",
            lambda value: tuple(dict(item) for item in value),
        )
        self._similar_artist_cache = self._load_timed_cache(
            payload,
            "similar_artist_cache",
            lambda value: tuple(str(item) for item in value),
        )

    def _load_legacy_cache(self, payload: dict[str, Any]) -> None:
        written_at = float(payload.get("written_at") or 0)
        if time.time() - written_at > self.cache_ttl_seconds:
            return
        self._artist_search_cache = {
            str(key): list(value)
            for key, value in dict(payload.get("artist_search_cache") or {}).items()
        }
        self._artist_genre_cache = {
            str(key): tuple(str(item) for item in value)
            for key, value in dict(payload.get("artist_genre_cache") or {}).items()
        }
        self._genre_artist_cache = {
            str(key): tuple(dict(item) for item in value)
            for key, value in dict(payload.get("genre_artist_cache") or {}).items()
        }
        self._similar_artist_cache = {
            str(key): tuple(str(item) for item in value)
            for key, value in dict(payload.get("similar_artist_cache") or {}).items()
        }
        for cache_name, cache in (
            ("artist_search_cache", self._artist_search_cache),
            ("artist_genre_cache", self._artist_genre_cache),
            ("genre_artist_cache", self._genre_artist_cache),
            ("similar_artist_cache", self._similar_artist_cache),
        ):
            self._cache_timestamps[cache_name] = {key: written_at for key in cache}

    def _load_timed_cache(self, payload: dict[str, Any], cache_name: str, convert) -> dict[str, Any]:
        now = time.time()
        output: dict[str, Any] = {}
        timestamps: dict[str, float] = {}
        raw_cache = dict(payload.get(cache_name) or {})
        for raw_key, raw_entry in raw_cache.items():
            key = str(raw_key)
            entry = dict(raw_entry or {})
            written_at = float(entry.get("written_at") or 0)
            if now - written_at > self.cache_ttl_seconds:
                continue
            output[key] = convert(entry.get("value"))
            timestamps[key] = written_at
        self._cache_timestamps[cache_name] = timestamps
        return output

    def _save_cache(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "artist_search_cache": self._timed_cache_payload("artist_search_cache", self._artist_search_cache),
            "artist_genre_cache": self._timed_cache_payload("artist_genre_cache", self._artist_genre_cache),
            "genre_artist_cache": self._timed_cache_payload("genre_artist_cache", self._genre_artist_cache),
            "similar_artist_cache": self._timed_cache_payload("similar_artist_cache", self._similar_artist_cache),
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.cache_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            tmp_path.replace(self.cache_path)
        except OSError:
            return

    def _timed_cache_payload(self, cache_name: str, cache: dict[str, Any]) -> dict[str, dict[str, Any]]:
        timestamps = self._cache_timestamps.setdefault(cache_name, {})
        now = time.time()
        return {
            key: {
                "written_at": timestamps.setdefault(key, now),
                "value": value,
            }
            for key, value in cache.items()
        }

    def _touch_cache_key(self, cache_name: str, key: str) -> None:
        self._cache_timestamps.setdefault(cache_name, {})[key] = time.time()


def _artist_match_score(query: str, candidate: str) -> float:
    normalized_query = _normalize_artist(query)
    normalized_candidate = _normalize_artist(candidate)
    if not normalized_query or not normalized_candidate:
        return 0.0
    if normalized_query == normalized_candidate:
        return 1.0
    if normalized_query in normalized_candidate or normalized_candidate in normalized_query:
        return 0.86
    return SequenceMatcher(None, normalized_query, normalized_candidate).ratio()


def _rank_for_artist(artists: tuple[dict[str, Any], ...], artist_id: str, artist_name: str) -> int | None:
    normalized_name = _normalize_artist(artist_name)
    for index, artist in enumerate(artists, start=1):
        if artist.get("id") == artist_id:
            return int(artist.get("rank") or index)
        if _normalize_artist(str(artist.get("name") or "")) == normalized_name:
            return int(artist.get("rank") or index)
    return None


def _normalize_artist(value: str) -> str:
    lowered = value.casefold().strip()
    for prefix in ("the ",):
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix) :]
    return "".join(char for char in lowered if char.isalnum())


def _default_cache_path() -> Path:
    return Path.home() / ".cache" / "sonos-ascii-ui" / "everynoise-cache.json"
