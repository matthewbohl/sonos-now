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


def test_track_refresh_uses_existing_topology_without_rediscovery():
    kitchen = FakeDevice("Kitchen", volume=35)
    service = SonosService()
    service._devices_by_name = {"Kitchen": kitchen}
    service._discover_devices = lambda: (_ for _ in ()).throw(RuntimeError("should not rediscover"))  # type: ignore[method-assign]

    tracks = service.tracks_for_entries((SpeakerEntry("Kitchen", speaker="Kitchen", members=("Kitchen",), coordinator="Kitchen"),))

    assert len(tracks) == 1
    assert tracks[0].speaker == "Kitchen"
    assert tracks[0].title == "Track"


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
