from __future__ import annotations

from sonos_now.ascii_art import AlbumArt
from sonos_now.everynoise import GenreResult
from sonos_now.grouping import expand_existing_group_members, grouping_source, is_group_member
from sonos_now.models import SpeakerEntry, TrackInfo
from sonos_now.rendering import (
    MIN_FULLSCREEN_ART_SIZE,
    SIDE_BY_SIDE_METADATA_WIDTH,
    fullscreen_album_art_text,
    fullscreen_art_size,
    muted_speaker_lines,
    playback_state_symbol,
    research_lines,
    speaker_row_label,
    speaker_state_indicator,
    track_with_side_album_art_text,
)


def test_speaker_rows_use_compact_group_labels_and_requested_spinner_chars():
    group = SpeakerEntry(
        "Kitchen, Living Room, Office + Patio Ensemble",
        is_group=True,
        members=("Kitchen", "Living Room", "Office", "Patio"),
        coordinator="Kitchen",
    )
    kitchen = SpeakerEntry("Kitchen", speaker="Kitchen", members=("Kitchen",), coordinator="Kitchen")

    assert speaker_row_label(group, 18) == "Kitchen + Livin..."
    assert is_group_member(kitchen, [group, kitchen])
    assert grouping_source(["Patio", "Den"], [group, kitchen]) == "Kitchen"
    assert expand_existing_group_members(("Patio", "Den"), [group, kitchen]) == (
        "Kitchen",
        "Living Room",
        "Office",
        "Patio",
        "Den",
    )
    assert speaker_state_indicator(group, [group, kitchen], {"Kitchen": TrackInfo("Kitchen", playback_state="PLAYING")}) == " (>)"
    assert speaker_state_indicator(kitchen, [group, kitchen], {"Kitchen": TrackInfo("Kitchen", playback_state="PLAYING")}) == ""


def test_playback_state_symbols_are_plain_ascii():
    assert playback_state_symbol(TrackInfo("Kitchen", playback_state="PLAYING")) == ">"
    assert playback_state_symbol(TrackInfo("Kitchen", playback_state="PAUSED_PLAYBACK")) == "||"
    assert playback_state_symbol(TrackInfo("Kitchen", playback_state="STOPPED")) == "[]"
    assert playback_state_symbol(None) == "..."


def test_research_lines_show_ranked_genres_and_artist_column():
    results = (
        GenreResult("art rock", 122.4, "Radiohead", "artist-id", rank=3, artists=("Thom Yorke", "Atoms for Peace")),
        GenreResult("alternative rock", 110.1, "Radiohead", "artist-id", rank=8, artists=("The Smile",)),
    )

    lines = research_lines("Radiohead", results, 0, 0, False)

    assert "Every Noise Research: Radiohead" in lines[0]
    assert "art rock" in "\n".join(lines)
    assert "Thom Yorke" in "\n".join(lines)


def test_side_by_side_album_art_keeps_art_to_right_of_metadata():
    art = AlbumArt(
        signature="track",
        lines=("@@", "##"),
        colors=((7, 7), (4, 4)),
    )

    rendered = track_with_side_album_art_text("Song   : A long title\nArtist : Someone", art)
    lines = rendered.plain.splitlines()

    assert lines[0].startswith("Song   : A long title")
    assert lines[0].index("+--+") >= SIDE_BY_SIDE_METADATA_WIDTH
    assert "|@@|" in lines[1]


def test_fullscreen_art_helpers_size_and_muted_fallback():
    width, height = fullscreen_art_size(100, 40)
    assert width >= MIN_FULLSCREEN_ART_SIZE[0]
    assert height >= MIN_FULLSCREEN_ART_SIZE[1]
    assert width <= 96
    assert width >= height

    muted = "\n".join(muted_speaker_lines(40, 18))
    assert "/" in muted
    assert "O" in muted
    assert "#" in muted


def test_fullscreen_album_art_animation_preserves_ascii_image():
    art = AlbumArt(
        signature="track",
        lines=("@@", "##"),
        colors=((7, 7), (4, 4)),
    )

    static = fullscreen_album_art_text("Title", art, 24)
    animated = fullscreen_album_art_text("Title", art, 24, animation_frame=12)

    assert static.plain == animated.plain
    assert static.spans != animated.spans
