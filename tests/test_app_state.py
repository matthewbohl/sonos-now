from __future__ import annotations

import asyncio
import time

from sonos_now.app import DebugEvent, OPTIMISTIC_GROUP_TTL_SECONDS, SPINNER_CHARS, SonosNowApp
from sonos_now.everynoise import GenreResult
from sonos_now.models import SonosSnapshot, SpeakerEntry, TrackInfo
from sonos_now.soco_backend import SonosService


def test_app_keeps_control_bindings_out_of_textual_footer_to_avoid_double_dispatch():
    app = SonosNowApp(SonosService())

    assert all(binding.key not in {"p", "f", "b", "i", "k", "v", "r", "space", "g"} for binding in app.BINDINGS)


def test_spinner_uses_requested_ascii_cycle():
    assert SPINNER_CHARS == "|/\\-o%"


def test_debug_lines_group_repeated_completed_commands():
    app = SonosNowApp(SonosService())
    app.debug_events = [
        DebugEvent("refresh snapshot", (), 1.0, status="done", finished_at=2.0),
        DebugEvent("refresh snapshot", (), 3.0, status="done", finished_at=4.0),
    ]

    assert "refresh snapshot x2" in app._debug_lines()[0]


def test_debug_running_status_is_separate_from_history_lines():
    app = SonosNowApp(SonosService())
    app._debug_start("group speakers", ("Kitchen", "Office"))

    assert "No completed SoCo commands yet." in app._debug_lines()
    assert "group speakers -> Kitchen, Office" in app._debug_status_line()


def test_refresh_busy_can_avoid_status_bar_message():
    app = SonosNowApp(SonosService())
    app.message = "ready"

    app._begin_busy("refresh", (), show_status=False)

    assert app.message == "ready"


def test_app_topology_refresh_does_not_use_full_snapshot_path():
    class SplitRefreshService:
        warnings: tuple[str, ...] = ()

        def __init__(self) -> None:
            self.refresh_topology_called = False
            self.tracks_for_entries_called = False

        def snapshot(self):
            raise AssertionError("UI refresh should not use full snapshot")

        def refresh_topology(self):
            self.refresh_topology_called = True
            return (SpeakerEntry("Kitchen", speaker="Kitchen", members=("Kitchen",), coordinator="Kitchen"),)

        def tracks_for_entries(self, entries):
            self.tracks_for_entries_called = True
            return (TrackInfo(speaker="Kitchen", title="Track"),)

    service = SplitRefreshService()
    app = SonosNowApp(service)  # type: ignore[arg-type]

    asyncio.run(app.action_refresh(force=True))

    assert service.refresh_topology_called
    assert service.tracks_for_entries_called
    assert app.entries[0].speaker == "Kitchen"
    assert app.tracks[0].title == "Track"


def test_groups_expand_by_default_but_respect_explicit_collapse():
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


def test_research_navigation_is_app_state_not_a_modal_screen():
    app = SonosNowApp(SonosService())
    app.research.visible = True
    app.research.results = (
        GenreResult("art rock", 122.4, "Radiohead", "artist-id", artists=("Thom Yorke",)),
        GenreResult("alternative rock", 110.1, "Radiohead", "artist-id", artists=("The Smile",)),
    )

    app.action_research_down()
    assert app.research.selected_index == 1

    app.action_research_toggle_column()
    assert app.research.focus_artists

    app.action_close_research()
    assert not app.research.visible


def test_fullscreen_album_art_uses_highlighted_entry():
    app = SonosNowApp(SonosService())
    kitchen = SpeakerEntry("Kitchen", speaker="Kitchen", members=("Kitchen",), coordinator="Kitchen")
    office = SpeakerEntry("Office", speaker="Office", members=("Office",), coordinator="Office")
    app.entries = [kitchen, office]
    app.tracks = [
        TrackInfo(speaker="Kitchen", title="Kitchen Song", album_art_url="http://example/kitchen.jpg"),
        TrackInfo(speaker="Office", title="Office Song", album_art_url="http://example/office.jpg"),
    ]
    app.selected_index = 1

    item = app._selected_detail_item()

    assert item is not None
    assert item[1].title == "Office Song"
