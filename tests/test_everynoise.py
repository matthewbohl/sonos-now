from __future__ import annotations

import json
import time

from sonos_now.everynoise import EveryNoiseClient


def test_every_noise_cache_uses_individual_entry_timestamps(tmp_path):
    cache_path = tmp_path / "everynoise-cache.json"
    now = time.time()
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artist_genre_cache": {
                    "fresh": {"written_at": now, "value": ["art rock"]},
                    "stale": {"written_at": now - 100, "value": ["expired"]},
                },
                "artist_search_cache": {},
                "genre_artist_cache": {},
                "similar_artist_cache": {},
            }
        ),
        encoding="utf-8",
    )

    client = EveryNoiseClient(cache_path=cache_path, cache_ttl_seconds=10)

    assert client._artist_genre_cache == {"fresh": ("art rock",)}
    assert "fresh" in client._cache_timestamps["artist_genre_cache"]
    assert "stale" not in client._cache_timestamps["artist_genre_cache"]


def test_every_noise_legacy_cache_is_loaded_with_per_key_timestamps(tmp_path):
    cache_path = tmp_path / "everynoise-cache.json"
    written_at = time.time()
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "written_at": written_at,
                "artist_genre_cache": {"artist-id": ["jazz"]},
                "artist_search_cache": {},
                "genre_artist_cache": {},
                "similar_artist_cache": {},
            }
        ),
        encoding="utf-8",
    )

    client = EveryNoiseClient(cache_path=cache_path, cache_ttl_seconds=10)

    assert client._artist_genre_cache == {"artist-id": ("jazz",)}
    assert client._cache_timestamps["artist_genre_cache"] == {"artist-id": written_at}


def test_every_noise_save_preserves_existing_entry_timestamps(tmp_path):
    cache_path = tmp_path / "everynoise-cache.json"
    client = EveryNoiseClient(cache_path=cache_path, cache_ttl_seconds=10)
    client._artist_genre_cache["artist-id"] = ("ambient",)
    client._cache_timestamps["artist_genre_cache"]["artist-id"] = 123.0

    client._save_cache()

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["artist_genre_cache"]["artist-id"]["written_at"] == 123.0
    assert payload["artist_genre_cache"]["artist-id"]["value"] == ["ambient"]
