from __future__ import annotations

import time
from dataclasses import replace
from typing import Iterable
from urllib.parse import urljoin

from .models import SonosSnapshot, SpeakerEntry, TrackInfo
from .timefmt import parse_duration


class SonosService:
    """Direct SoCo backend for Sonos Now.

    The service deliberately exposes plain dataclasses so the Textual UI does
    not need to know about SoCo object lifetimes or UPnP quirks.
    """

    def __init__(
        self,
        speakers: Iterable[str] = (),
        *,
        subnets: Iterable[str] = (),
        discovery_timeout: float = 3.0,
        group_join_delay: float = 0.35,
    ) -> None:
        self.requested_speakers = tuple(speakers)
        self.subnets = tuple(subnets)
        self.discovery_timeout = discovery_timeout
        self.group_join_delay = group_join_delay
        self._devices_by_name: dict[str, object] = {}

    def snapshot(self) -> SonosSnapshot:
        devices = self._devices()
        entries = self._entries_for_devices(devices)
        tracks = self._tracks_for_entries(entries)
        return SonosSnapshot(entries=tuple(entries), tracks=tuple(tracks))

    def play_pause(self, entry: SpeakerEntry) -> None:
        device = self._device_for_control(entry, group_action=True)
        state = _playback_state(device)
        if state == "playing":
            _pause(device)
        else:
            _play(device)

    def next(self, entry: SpeakerEntry) -> None:
        _next(self._device_for_control(entry, group_action=True))

    def previous(self, entry: SpeakerEntry) -> None:
        _previous(self._device_for_control(entry, group_action=True))

    def change_volume(self, entry: SpeakerEntry, delta: int) -> None:
        for speaker in self._volume_targets(entry):
            device = self._devices_by_name.get(speaker)
            if device is None:
                continue
            current = _safe_volume(device)
            if current is None:
                continue
            device.volume = max(0, min(100, current + delta))

    def group_speakers(self, source: str, speakers: tuple[str, ...]) -> None:
        self._devices()
        master = self._devices_by_name.get(source)
        if master is None:
            raise RuntimeError(f"Source speaker not available: {source}")
        master = _group_coordinator(master)
        targets: list[tuple[str, object]] = []
        for speaker in speakers:
            device = self._devices_by_name.get(speaker)
            if device is None:
                raise RuntimeError(f"Speaker not available: {speaker}")
            if _same_device(device, master) or _same_group(device, master):
                continue
            targets.append((speaker, device))
        for index, (_speaker, device) in enumerate(targets):
            device.join(master)
            if index < len(targets) - 1 and self.group_join_delay > 0:
                time.sleep(self.group_join_delay)

    def remove_speaker_from_group(self, speaker: str, stop: bool = True) -> None:
        self._devices()
        device = self._devices_by_name.get(speaker)
        if device is None:
            raise RuntimeError(f"Speaker not available: {speaker}")
        if _group_size(device) > 1:
            _safe_unjoin(device)
        if stop:
            _pause(device)

    def ungroup_speakers(self, speakers: tuple[str, ...], stop: bool = True) -> None:
        self._devices()
        devices = [
            self._devices_by_name[speaker]
            for speaker in speakers
            if speaker in self._devices_by_name
        ]
        devices.sort(key=lambda device: _is_group_coordinator(device))
        for device in devices:
            if _group_size(device) > 1 and not _is_group_coordinator(device):
                _safe_unjoin(device)
            if stop:
                _stop(device)

    def _devices(self) -> list[object]:
        if self.requested_speakers:
            devices = self._manual_devices()
        else:
            devices = list(self._discover_devices())

        visible = [
            device
            for device in devices
            if getattr(device, "is_visible", True) and getattr(device, "player_name", None)
        ]
        self._devices_by_name = {str(device.player_name): device for device in visible}
        return visible

    def _manual_devices(self) -> list[object]:
        import soco

        discovered = {str(device.player_name): device for device in self._discover_devices() if getattr(device, "player_name", None)}
        devices: list[object] = []
        for speaker in self.requested_speakers:
            if _looks_like_host(speaker):
                devices.append(soco.SoCo(speaker))
            elif speaker in discovered:
                devices.append(discovered[speaker])
        return devices

    def _discover_devices(self) -> set[object]:
        import soco

        if self.subnets:
            try:
                return soco.discovery.scan_network(
                    include_invisible=True,
                    multi_household=True,
                    scan_timeout=max(0.1, min(self.discovery_timeout, 2.0)),
                    networks_to_scan=list(self.subnets),
                ) or set()
            except Exception:
                return set()

        try:
            return soco.discovery.discover(timeout=self.discovery_timeout) or set()
        except Exception:
            return set()

    def _entries_for_devices(self, devices: list[object]) -> list[SpeakerEntry]:
        groups: dict[tuple[str, ...], str] = {}
        for device in devices:
            try:
                visible_members = sorted(
                    str(member.player_name)
                    for member in device.group.members
                    if getattr(member, "is_visible", True) and getattr(member, "player_name", None)
                )
                coordinator = str(device.group.coordinator.player_name)
            except Exception:
                name = str(getattr(device, "player_name", "") or "")
                visible_members = [name] if name else []
                coordinator = name

            if visible_members:
                groups[tuple(visible_members)] = coordinator

        entries: list[SpeakerEntry] = []
        for members, coordinator in sorted(groups.items(), key=lambda item: item[0][0].casefold()):
            if len(members) > 1:
                entries.append(
                    SpeakerEntry(
                        label=_group_label(members),
                        is_group=True,
                        members=members,
                        coordinator=coordinator,
                    )
                )
                entries.extend(
                    SpeakerEntry(label=f"  {member}", speaker=member, members=(member,), coordinator=coordinator)
                    for member in members
                )
            else:
                member = members[0]
                entries.append(SpeakerEntry(label=member, speaker=member, members=(member,), coordinator=coordinator))
        return entries

    def _tracks_for_entries(self, entries: list[SpeakerEntry]) -> list[TrackInfo]:
        tracks_by_speaker: dict[str, TrackInfo] = {}
        for entry in entries:
            if entry.is_group:
                coordinator = entry.coordinator if entry.coordinator in entry.members else entry.members[0]
                base_track = self._track_for_speaker(coordinator)
                for member in entry.members:
                    volume = _safe_volume(self._devices_by_name.get(member))
                    tracks_by_speaker[member] = replace(base_track, speaker=member, volume=volume)
            elif entry.speaker and entry.speaker not in tracks_by_speaker:
                tracks_by_speaker[entry.speaker] = self._track_for_speaker(entry.speaker)

        return [tracks_by_speaker[speaker] for speaker in dict.fromkeys(entry.speaker for entry in entries if entry.speaker) if speaker]

    def _track_for_speaker(self, speaker: str) -> TrackInfo:
        device = self._devices_by_name.get(speaker)
        if device is None:
            return TrackInfo(speaker=speaker, error="Speaker not discovered")

        try:
            info = device.get_current_track_info()
            state = _playback_state(device)
            return TrackInfo(
                speaker=speaker,
                title=str(info.get("title") or ""),
                artist=str(info.get("artist") or info.get("creator") or ""),
                album=str(info.get("album") or ""),
                position=parse_duration(info.get("position")),
                duration=parse_duration(info.get("duration")),
                volume=_safe_volume(device),
                playback_state=state,
                album_art_url=_album_art_url(device, info),
            )
        except Exception as exc:
            volume = _safe_volume(device)
            return TrackInfo(speaker=speaker, volume=volume, error=str(exc))

    def _device_for_control(self, entry: SpeakerEntry, *, group_action: bool) -> object:
        speaker = entry.coordinator if group_action and entry.coordinator else entry.speaker
        if speaker is None and entry.members:
            speaker = entry.members[0]
        if not speaker or speaker not in self._devices_by_name:
            self._devices()
        device = self._devices_by_name.get(str(speaker))
        if device is None:
            raise RuntimeError(f"Speaker not available: {speaker}")
        return device

    def _volume_targets(self, entry: SpeakerEntry) -> tuple[str, ...]:
        if entry.is_group:
            return entry.members
        if entry.speaker:
            return (entry.speaker,)
        return ()


def _playback_state(device: object) -> str:
    try:
        state = str(device.get_current_transport_info().get("current_transport_state") or "")
    except Exception:
        return ""
    text = state.strip().casefold()
    if "pause" in text:
        return "paused"
    if "play" in text:
        return "playing"
    if "stop" in text:
        return "stopped"
    return text


def _group_coordinator(device: object) -> object:
    try:
        return device.group.coordinator
    except Exception:
        return device


def _group_size(device: object) -> int:
    try:
        return len(tuple(device.group.members))
    except Exception:
        return 1


def _is_group_coordinator(device: object) -> bool:
    return _same_device(_group_coordinator(device), device)


def _same_group(device: object, master: object) -> bool:
    try:
        return any(_same_device(member, device) for member in master.group.members)
    except Exception:
        return False


def _same_device(left: object, right: object) -> bool:
    if left is right:
        return True
    left_uid = getattr(left, "uid", None)
    right_uid = getattr(right, "uid", None)
    if left_uid and right_uid:
        return left_uid == right_uid
    return getattr(left, "player_name", None) == getattr(right, "player_name", None)


def _safe_unjoin(device: object) -> bool:
    try:
        device.unjoin()
        return True
    except Exception as exc:
        if _is_upnp_701(exc):
            return False
        raise


def _is_upnp_701(exc: Exception) -> bool:
    code = getattr(exc, "error_code", None)
    if str(code) == "701":
        return True
    text = str(exc)
    return "701" in text and "UPnP" in text


def _safe_volume(device: object | None) -> int | None:
    if device is None:
        return None
    try:
        return max(0, min(100, int(device.volume)))
    except Exception:
        return None


def _play(device: object) -> None:
    try:
        device.play()
    except Exception:
        _av_transport_action(device, "Play", [("Speed", 1)])


def _pause(device: object) -> None:
    try:
        device.pause()
    except Exception:
        _av_transport_action(device, "Pause")


def _next(device: object) -> None:
    try:
        device.next()
    except Exception:
        _av_transport_action(device, "Next")


def _previous(device: object) -> None:
    try:
        device.previous()
    except Exception:
        _av_transport_action(device, "Previous")


def _stop(device: object) -> None:
    try:
        device.stop()
    except Exception:
        _av_transport_action(device, "Stop")


def _av_transport_action(device: object, action: str, extra: list[tuple[str, object]] | None = None) -> None:
    service = getattr(device, "avTransport", None)
    if service is None:
        raise RuntimeError(f"SoCo device does not expose AVTransport for {action}")
    args = [("InstanceID", 0), *(extra or [])]
    getattr(service, action)(args)


def _album_art_url(device: object, info: dict[str, object]) -> str:
    raw = str(info.get("album_art") or info.get("album_art_uri") or "")
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    host = getattr(device, "ip_address", "")
    return urljoin(f"http://{host}:1400", raw)


def _group_label(members: tuple[str, ...]) -> str:
    names = [member.strip() for member in members]
    if len(names) == 2:
        return f"{names[0]} + {names[1]} Duet"
    return f"{', '.join(names[:-1])} + {names[-1]} Ensemble"


def _looks_like_host(value: str) -> bool:
    return "." in value or ":" in value
