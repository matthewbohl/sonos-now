from __future__ import annotations

from sonos_now.models import SpeakerEntry
from sonos_now.soco_backend import SonosService, _album_art_url, _group_label
from sonos_now.timefmt import format_duration, parse_duration


class FakeTransport:
    def __init__(self, state: str = "PLAYING") -> None:
        self.state = state


class FakeGroup:
    def __init__(self, members, coordinator) -> None:
        self.members = members
        self.coordinator = coordinator


class FakeDevice:
    is_visible = True
    ip_address = "192.168.1.10"

    def __init__(self, name: str, volume: int = 20, state: str = "PLAYING") -> None:
        self.player_name = name
        self.uid = name
        self.volume = volume
        self.state = state
        self.group = FakeGroup([self], self)
        self.play_called = False
        self.pause_called = False
        self.stop_called = False
        self.joined_to = None
        self.unjoin_called = False

    def get_current_track_info(self):
        return {
            "title": "Track",
            "artist": "Artist",
            "album": "Album",
            "position": "0:30",
            "duration": "3:00",
            "album_art": "/getaa?s=1&u=x",
        }

    def get_current_transport_info(self):
        return {"current_transport_state": self.state}

    def play(self):
        self.play_called = True

    def pause(self):
        self.pause_called = True

    def stop(self):
        self.stop_called = True

    def join(self, master):
        self.joined_to = master

    def unjoin(self):
        self.unjoin_called = True


class FakeUpnp701Device(FakeDevice):
    def unjoin(self):
        raise RuntimeError("UPnP Error 701 received")


def test_duration_formatting_round_trip():
    assert parse_duration("1:02") == 62
    assert parse_duration("1:02:03") == 3723
    assert format_duration(62) == "1:02"


def test_group_labels_match_original_style():
    assert _group_label(("Kitchen", "Office")) == "Kitchen + Office Duet"
    assert _group_label(("Den", "Kitchen", "Office")) == "Den, Kitchen + Office Ensemble"


def test_album_art_url_resolves_relative_soco_path():
    device = FakeDevice("Kitchen")

    assert _album_art_url(device, {"album_art": "/getaa?s=1&u=x"}) == "http://192.168.1.10:1400/getaa?s=1&u=x"
    assert _album_art_url(device, {"album_art": "https://example.test/a.jpg"}) == "https://example.test/a.jpg"


def test_service_snapshot_keeps_group_track_shared_and_volume_per_member():
    kitchen = FakeDevice("Kitchen", volume=35)
    office = FakeDevice("Office", volume=20)
    group = FakeGroup([kitchen, office], kitchen)
    kitchen.group = group
    office.group = group

    service = SonosService()
    service._discover_devices = lambda: {kitchen, office}  # type: ignore[method-assign]

    snapshot = service.snapshot()

    assert snapshot.entries[0] == SpeakerEntry(
        "Kitchen + Office Duet",
        is_group=True,
        members=("Kitchen", "Office"),
        coordinator="Kitchen",
    )
    tracks = {track.speaker: track for track in snapshot.tracks}
    assert tracks["Kitchen"].title == "Track"
    assert tracks["Office"].title == "Track"
    assert tracks["Kitchen"].volume == 35
    assert tracks["Office"].volume == 20


def test_play_pause_uses_transport_state():
    device = FakeDevice("Kitchen", state="PLAYING")
    service = SonosService()
    service._devices_by_name = {"Kitchen": device}

    service.play_pause(SpeakerEntry("Kitchen", speaker="Kitchen", members=("Kitchen",), coordinator="Kitchen"))

    assert device.pause_called


def test_play_pause_treats_paused_playback_as_paused():
    device = FakeDevice("Kitchen", state="PAUSED_PLAYBACK")
    service = SonosService()
    service._devices_by_name = {"Kitchen": device}

    service.play_pause(SpeakerEntry("Kitchen", speaker="Kitchen", members=("Kitchen",), coordinator="Kitchen"))

    assert device.play_called
    assert not device.pause_called


def test_group_speakers_joins_to_first_tagged_source_without_starting_playback():
    kitchen = FakeDevice("Kitchen", state="PAUSED_PLAYBACK")
    office = FakeDevice("Office")
    service = SonosService(group_join_delay=0)
    service._discover_devices = lambda: {kitchen, office}  # type: ignore[method-assign]

    service.group_speakers("Kitchen", ("Kitchen", "Office"))

    assert office.joined_to is kitchen
    assert not kitchen.play_called


def test_group_speakers_joins_all_targets_for_larger_groups():
    kitchen = FakeDevice("Kitchen", state="PAUSED_PLAYBACK")
    office = FakeDevice("Office")
    den = FakeDevice("Den")
    service = SonosService(group_join_delay=0)
    service._discover_devices = lambda: {kitchen, office, den}  # type: ignore[method-assign]

    service.group_speakers("Kitchen", ("Kitchen", "Office", "Den"))

    assert office.joined_to is kitchen
    assert den.joined_to is kitchen
    assert not kitchen.play_called


def test_group_speakers_skips_members_already_in_source_group():
    kitchen = FakeDevice("Kitchen", state="PLAYING")
    office = FakeDevice("Office", state="PLAYING")
    den = FakeDevice("Den", state="PLAYING")
    group = FakeGroup([kitchen, office], kitchen)
    kitchen.group = group
    office.group = group
    service = SonosService(group_join_delay=0)
    service._discover_devices = lambda: {kitchen, office, den}  # type: ignore[method-assign]

    service.group_speakers("Kitchen", ("Kitchen", "Office", "Den"))

    assert office.joined_to is None
    assert den.joined_to is kitchen
    assert not kitchen.pause_called
    assert not office.pause_called


def test_remove_speaker_from_group_unjoins_and_pauses_only_that_speaker():
    kitchen = FakeDevice("Kitchen")
    office = FakeDevice("Office")
    group = FakeGroup([kitchen, office], kitchen)
    kitchen.group = group
    office.group = group
    service = SonosService()
    service._discover_devices = lambda: {kitchen, office}  # type: ignore[method-assign]

    service.remove_speaker_from_group("Office", stop=True)

    assert office.unjoin_called
    assert office.pause_called
    assert not kitchen.stop_called
    assert not kitchen.pause_called


def test_remove_speaker_from_group_suppresses_upnp_701_unjoin_error():
    kitchen = FakeDevice("Kitchen")
    office = FakeUpnp701Device("Office")
    group = FakeGroup([kitchen, office], kitchen)
    kitchen.group = group
    office.group = group
    service = SonosService()
    service._discover_devices = lambda: {kitchen, office}  # type: ignore[method-assign]

    service.remove_speaker_from_group("Office", stop=True)

    assert office.pause_called


def test_ungroup_speakers_unjoins_and_stops_playback():
    kitchen = FakeDevice("Kitchen")
    office = FakeDevice("Office")
    group = FakeGroup([kitchen, office], kitchen)
    kitchen.group = group
    office.group = group
    service = SonosService()
    service._discover_devices = lambda: {kitchen, office}  # type: ignore[method-assign]

    service.ungroup_speakers(("Kitchen", "Office"), stop=True)

    assert not kitchen.unjoin_called
    assert office.unjoin_called
    assert kitchen.stop_called
    assert office.stop_called


def test_app_keeps_control_bindings_out_of_textual_footer_to_avoid_double_dispatch():
    from sonos_now.app import SonosNowApp

    service = SonosService()
    app = SonosNowApp(service)

    assert all(binding.key not in {"p", "f", "b", "i", "k", "v", "r", "space", "g"} for binding in app.BINDINGS)


def test_speaker_rows_use_compact_group_labels_and_requested_spinner_chars():
    from sonos_now.app import (
        SPINNER_CHARS,
        _expand_existing_group_members,
        _grouping_source,
        _is_group_member,
        _speaker_row_label,
        _speaker_state_indicator,
    )
    from sonos_now.models import TrackInfo

    group = SpeakerEntry(
        "Kitchen, Living Room, Office + Patio Ensemble",
        is_group=True,
        members=("Kitchen", "Living Room", "Office", "Patio"),
        coordinator="Kitchen",
    )
    kitchen = SpeakerEntry("Kitchen", speaker="Kitchen", members=("Kitchen",), coordinator="Kitchen")

    assert SPINNER_CHARS == "|/\\-o%"
    assert _speaker_row_label(group, 18) == "Kitchen + Livin..."
    assert _is_group_member(kitchen, [group, kitchen])
    assert _grouping_source(["Patio", "Den"], [group, kitchen]) == "Kitchen"
    assert _expand_existing_group_members(("Patio", "Den"), [group, kitchen]) == (
        "Kitchen",
        "Living Room",
        "Office",
        "Patio",
        "Den",
    )
    assert _speaker_state_indicator(group, [group, kitchen], {"Kitchen": TrackInfo("Kitchen", playback_state="PLAYING")}) == "> "
    assert _speaker_state_indicator(kitchen, [group, kitchen], {"Kitchen": TrackInfo("Kitchen", playback_state="PLAYING")}) == ""


def test_playback_state_symbols_are_plain_ascii():
    from sonos_now.app import _playback_state_symbol
    from sonos_now.models import TrackInfo

    assert _playback_state_symbol(TrackInfo("Kitchen", playback_state="PLAYING")) == ">"
    assert _playback_state_symbol(TrackInfo("Kitchen", playback_state="PAUSED_PLAYBACK")) == "||"
    assert _playback_state_symbol(TrackInfo("Kitchen", playback_state="STOPPED")) == "[]"
    assert _playback_state_symbol(None) == "..."


def test_debug_lines_group_repeated_completed_commands():
    from sonos_now.app import DebugEvent, SonosNowApp

    app = SonosNowApp(SonosService())
    app.debug_events = [
        DebugEvent("refresh snapshot", (), 1.0, status="done", finished_at=2.0),
        DebugEvent("refresh snapshot", (), 3.0, status="done", finished_at=4.0),
    ]

    assert "refresh snapshot x2" in app._debug_lines()[0]


def test_debug_running_status_is_separate_from_history_lines():
    from sonos_now.app import SonosNowApp

    app = SonosNowApp(SonosService())
    app._debug_start("group speakers", ("Kitchen", "Office"))

    assert "No completed SoCo commands yet." in app._debug_lines()
    assert "group speakers -> Kitchen, Office" in app._debug_status_line()


def test_refresh_busy_can_avoid_status_bar_message():
    from sonos_now.app import SonosNowApp

    app = SonosNowApp(SonosService())
    app.message = "ready"

    app._begin_busy("refresh", (), show_status=False)

    assert app.message == "ready"


def test_groups_expand_by_default_but_respect_explicit_collapse():
    from sonos_now.app import SonosNowApp
    from sonos_now.models import SonosSnapshot

    app = SonosNowApp(SonosService())
    group = SpeakerEntry(
        "Kitchen + Office Duet",
        is_group=True,
        members=("Kitchen", "Office"),
        coordinator="Kitchen",
    )
    kitchen = SpeakerEntry("Kitchen", speaker="Kitchen", members=("Kitchen",), coordinator="Kitchen")
    office = SpeakerEntry("Office", speaker="Office", members=("Office",), coordinator="Kitchen")

    app._apply_snapshot(SonosSnapshot(entries=(group, kitchen, office), tracks=()))

    assert app._visible_entries() == [group, kitchen, office]
    app.collapsed_groups.add(group.key)
    app._apply_snapshot(SonosSnapshot(entries=(group, kitchen, office), tracks=()))
    assert app._visible_entries() == [group]


def test_optimistic_group_snapshot_is_preserved_until_sonos_reports_it():
    import time

    from sonos_now.app import OPTIMISTIC_GROUP_TTL_SECONDS, SonosNowApp
    from sonos_now.models import SonosSnapshot

    app = SonosNowApp(SonosService())
    kitchen = SpeakerEntry("Kitchen", speaker="Kitchen", members=("Kitchen",), coordinator="Kitchen")
    office = SpeakerEntry("Office", speaker="Office", members=("Office",), coordinator="Office")
    group = SpeakerEntry("Kitchen + Office Duet", is_group=True, members=("Kitchen", "Office"), coordinator="Kitchen")

    app._optimistic_groups[("Kitchen", "Office")] = time.monotonic() + OPTIMISTIC_GROUP_TTL_SECONDS

    stale_snapshot = SonosSnapshot(entries=(kitchen, office), tracks=())
    assert app._should_defer_snapshot_for_optimistic_groups(stale_snapshot)

    observed_snapshot = SonosSnapshot(entries=(group, kitchen, office), tracks=())
    assert not app._should_defer_snapshot_for_optimistic_groups(observed_snapshot)
    assert not app._optimistic_groups


def test_research_lines_show_ranked_genres_and_artist_column():
    from sonos_now.app import _research_lines
    from sonos_now.everynoise import GenreResult

    results = (
        GenreResult("art rock", 122.4, "Radiohead", "artist-id", rank=3, artists=("Thom Yorke", "Atoms for Peace")),
        GenreResult("alternative rock", 110.1, "Radiohead", "artist-id", rank=8, artists=("The Smile",)),
    )

    lines = _research_lines("Radiohead", results, 0, 0, False)

    assert "Every Noise Research: Radiohead" in lines[0]
    assert "art rock" in "\n".join(lines)
    assert "Thom Yorke" in "\n".join(lines)


def test_research_navigation_is_app_state_not_a_modal_screen():
    from sonos_now.app import SonosNowApp
    from sonos_now.everynoise import GenreResult

    app = SonosNowApp(SonosService())
    app.research_visible = True
    app.research_results = (
        GenreResult("art rock", 122.4, "Radiohead", "artist-id", artists=("Thom Yorke",)),
        GenreResult("alternative rock", 110.1, "Radiohead", "artist-id", artists=("The Smile",)),
    )

    app.action_research_down()
    assert app.research_selected_index == 1

    app.action_research_toggle_column()
    assert app.research_focus_artists

    app.action_close_research()
    assert not app.research_visible


def test_side_by_side_album_art_keeps_art_to_right_of_metadata():
    from sonos_now.app import SIDE_BY_SIDE_METADATA_WIDTH, _track_with_side_album_art_text
    from sonos_now.ascii_art import AlbumArt

    art = AlbumArt(
        signature="track",
        lines=("@@", "##"),
        colors=((7, 7), (4, 4)),
    )

    rendered = _track_with_side_album_art_text("Song   : A long title\nArtist : Someone", art)
    lines = rendered.plain.splitlines()

    assert lines[0].startswith("Song   : A long title")
    assert lines[0].index("+--+") >= SIDE_BY_SIDE_METADATA_WIDTH
    assert "|@@|" in lines[1]


def test_fullscreen_art_helpers_size_and_muted_fallback():
    from sonos_now.app import MIN_FULLSCREEN_ART_SIZE, _fullscreen_art_size, _muted_speaker_lines

    width, height = _fullscreen_art_size(100, 40)
    assert width >= MIN_FULLSCREEN_ART_SIZE[0]
    assert height >= MIN_FULLSCREEN_ART_SIZE[1]
    assert width <= 96
    assert width >= height

    muted = "\n".join(_muted_speaker_lines(40, 18))
    assert "/" in muted
    assert "O" in muted
    assert "#" in muted


def test_fullscreen_album_art_animation_preserves_ascii_image():
    from sonos_now.app import _fullscreen_album_art_text
    from sonos_now.ascii_art import AlbumArt

    art = AlbumArt(
        signature="track",
        lines=("@@", "##"),
        colors=((7, 7), (4, 4)),
    )

    static = _fullscreen_album_art_text("Title", art, 24)
    animated = _fullscreen_album_art_text("Title", art, 24, animation_frame=12)

    assert static.plain == animated.plain
    assert static.spans != animated.spans


def test_fullscreen_album_art_uses_highlighted_entry_not_marked_entries():
    from sonos_now.app import SonosNowApp
    from sonos_now.models import TrackInfo

    app = SonosNowApp(SonosService())
    kitchen = SpeakerEntry("Kitchen", speaker="Kitchen", members=("Kitchen",), coordinator="Kitchen")
    office = SpeakerEntry("Office", speaker="Office", members=("Office",), coordinator="Office")
    app.entries = [kitchen, office]
    app.tracks = [
        TrackInfo(speaker="Kitchen", title="Kitchen Song", album_art_url="http://example/kitchen.jpg"),
        TrackInfo(speaker="Office", title="Office Song", album_art_url="http://example/office.jpg"),
    ]
    app.marked.add(kitchen.key)
    app.selected_index = 1

    item = app._selected_detail_item()

    assert item is not None
    assert item[1].title == "Office Song"


def test_visualizer_engines_and_secret_scene_render_nonblank_frames():
    from sonos_now.visualizer import ENGINES, _secret_festival

    assert len(ENGINES) >= 10
    for engine in ENGINES:
        frame = engine.renderer(48, 14, 3.5, engine.chars)
        assert len(frame.splitlines()) == 14
        assert any(char != " " for char in frame)
    secret = _secret_festival(80, 24, 2.0)
    assert "ULTRA" in secret
    assert any(char in secret for char in ("o", "O", "@"))
