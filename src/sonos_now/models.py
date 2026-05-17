from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrackInfo:
    speaker: str
    title: str = ""
    artist: str = ""
    album: str = ""
    position: int | None = None
    duration: int | None = None
    volume: int | None = None
    playback_state: str = ""
    album_art_url: str = ""
    error: str | None = None

    @property
    def is_available(self) -> bool:
        return self.error is None

    @property
    def progress(self) -> float | None:
        if self.position is None or self.duration in (None, 0):
            return None
        return max(0.0, min(1.0, self.position / self.duration))

    @property
    def should_advance_position(self) -> bool:
        if not self.playback_state:
            return True
        return self.playback_state.casefold() in {"playing", "play"}


@dataclass(frozen=True)
class SpeakerEntry:
    label: str
    speaker: str | None = None
    is_group: bool = False
    members: tuple[str, ...] = ()
    coordinator: str | None = None

    @property
    def key(self) -> str:
        if self.is_group:
            return "group:" + "|".join(self.members)
        return "speaker:" + str(self.speaker or self.label)


@dataclass(frozen=True)
class SonosSnapshot:
    entries: tuple[SpeakerEntry, ...]
    tracks: tuple[TrackInfo, ...]
