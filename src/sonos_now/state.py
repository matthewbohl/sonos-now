from __future__ import annotations

from dataclasses import dataclass

from .everynoise import GenreResult


@dataclass
class ResearchState:
    visible: bool = False
    artist: str = ""
    results: tuple[GenreResult, ...] = ()
    selected_index: int = 0
    artist_scroll: int = 0
    focus_artists: bool = False
    loading: bool = False
    error: str = ""
    job_artist: str = ""
