from __future__ import annotations

import asyncio

from .ascii_art import AlbumArt, fetch_image_bytes, image_bytes_to_colored_ascii
from .models import TrackInfo
from .rendering import COMPACT_ALBUM_ART_SIZE, FULL_ALBUM_ART_SIZE


class AlbumArtManager:
    def __init__(self) -> None:
        self.full: dict[str, AlbumArt] = {}
        self.compact: dict[str, AlbumArt] = {}
        self.fullscreen: dict[tuple[str, int, int], AlbumArt] = {}
        self.image_bytes: dict[str, bytes] = {}
        self.jobs: set[tuple[str, str]] = set()
        self.locks: dict[str, asyncio.Lock] = {}

    def cache(self, variant: str) -> dict[str, AlbumArt]:
        return self.compact if variant == "compact" else self.full

    async def load_variant(self, track: TrackInfo, signature: str, variant: str) -> AlbumArt:
        try:
            image = await self.image_for(track, signature)
            width, height = COMPACT_ALBUM_ART_SIZE if variant == "compact" else FULL_ALBUM_ART_SIZE
            lines, colors = await asyncio.to_thread(image_bytes_to_colored_ascii, image, width, height)
            art = AlbumArt(signature=signature, lines=lines, colors=colors)
            self.cache(variant)[signature] = art
            return art
        except Exception as exc:
            art = AlbumArt(signature=signature, error=str(exc))
            self.cache(variant)[signature] = art
            return art
        finally:
            self.jobs.discard((signature, variant))

    async def fullscreen_art(self, track: TrackInfo, signature: str, width: int, height: int) -> AlbumArt:
        cache_key = (signature, width, height)
        art = self.fullscreen.get(cache_key)
        if art is not None:
            return art
        image = await self.image_for(track, signature)
        lines, colors = await asyncio.to_thread(image_bytes_to_colored_ascii, image, width, height)
        art = AlbumArt(signature=signature, lines=lines, colors=colors)
        self.fullscreen[cache_key] = art
        self._trim_fullscreen_cache()
        return art

    async def image_for(self, track: TrackInfo, signature: str) -> bytes:
        image = self.image_bytes.get(signature)
        if image is not None:
            return image
        lock = self.locks.setdefault(signature, asyncio.Lock())
        async with lock:
            image = self.image_bytes.get(signature)
            if image is None:
                image = await asyncio.to_thread(fetch_image_bytes, track.album_art_url, 5.0)
                self.image_bytes[signature] = image
            return image

    def _trim_fullscreen_cache(self, max_entries: int = 16) -> None:
        while len(self.fullscreen) > max_entries:
            self.fullscreen.pop(next(iter(self.fullscreen)))
