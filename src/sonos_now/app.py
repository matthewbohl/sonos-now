from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Header, Static
from rich.text import Text

from .art_manager import AlbumArtManager
from .ascii_art import AlbumArt
from .everynoise import EveryNoiseClient, GenreResult
from .grouping import (
    entry_speakers as _entry_speakers,
    entry_tag as _entry_tag,
    expand_existing_group_members as _expand_existing_group_members,
    grouping_source as _grouping_source,
    is_group_member as _is_group_member,
    optimistic_group_label as _optimistic_group_label,
    shared_track_for_group as _shared_track_for_group,
    track_signature as _track_signature,
    volumes_for as _volumes_for,
)
from .models import SonosSnapshot, SpeakerEntry, TrackInfo
from .rendering import (
    album_art_text as _album_art_text,
    elapsed_text as _elapsed_text,
    fullscreen_album_art_text as _fullscreen_album_art_text,
    fullscreen_art_size as _fullscreen_art_size,
    fullscreen_art_title as _fullscreen_art_title,
    muted_speaker_text as _muted_speaker_text,
    research_lines as _research_lines,
    speaker_row_label as _speaker_row_label,
    speaker_state_indicator as _speaker_state_indicator,
    track_text as _track_text,
    track_with_side_album_art_text as _track_with_side_album_art_text,
)
from .soco_backend import SonosService
from .state import ResearchState
from .visualizer import VisualizerScreen

SPINNER_CHARS = "|/\\-o%"
OPTIMISTIC_GROUP_TTL_SECONDS = 8.0


@dataclass
class DebugEvent:
    label: str
    speakers: tuple[str, ...]
    started_at: float
    status: str = "running"
    finished_at: float | None = None
    error: str = ""


class SonosNowApp(App[None]):
    CSS_PATH = "sonos_now.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, service: SonosService, *, refresh_interval: float = 2.0, view_only: bool = False) -> None:
        super().__init__()
        self.service = service
        self.refresh_interval = refresh_interval
        self.topology_refresh_interval = max(10.0, refresh_interval * 5)
        self.view_only = view_only
        self.entries: list[SpeakerEntry] = []
        self.tracks: list[TrackInfo] = []
        self.expanded_groups: set[str] = set()
        self.collapsed_groups: set[str] = set()
        self.speaker_tags: dict[str, str] = {}
        self.tag_order: dict[str, list[str]] = {}
        self.selected_index = 0
        self.album_art = AlbumArtManager()
        self.similar_artists: dict[str, tuple[str, ...]] = {}
        self.similar_artist_jobs: set[str] = set()
        self.every_noise = EveryNoiseClient()
        self.message = "Starting Sonos Now"
        self._refreshing_topology = False
        self._refreshing_tracks = False
        self._busy_label = ""
        self._busy_started_at = 0.0
        self._busy_speakers: set[str] = set()
        self._spinner_index = 0
        self._command_cooldown_until = 0.0
        self._pending_expand_members: set[tuple[str, ...]] = set()
        self._optimistic_groups: dict[tuple[str, ...], float] = {}
        self.debug_events: list[DebugEvent] = []
        self.debug_visible = False
        self.debug_scroll = 0
        self.research = ResearchState()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="layout"):
            with Vertical(id="speaker-pane"):
                yield Static(" Speakers ", classes="pane-title")
                yield Static(id="speakers")
            with Vertical(id="detail-pane"):
                yield Static(" Now Playing ", classes="pane-title")
                yield Static(id="details")
                yield Static(" Every Noise Research ", id="research-title")
                yield Static(id="research-pane")
                yield Static(" SoCo Debug ", id="debug-title")
                yield Static(id="debug-pane")
        yield Static(id="status")

    def on_mount(self) -> None:
        self.set_interval(self.refresh_interval, self.action_refresh_tracks)
        self.set_interval(self.topology_refresh_interval, self.action_refresh)
        self.set_interval(0.15, self._tick_status)
        self.call_later(self.action_refresh)

    async def on_key(self, event) -> None:
        key = event.key
        char = getattr(event, "character", "") or ""
        if char in {"P", "p"}:
            event.stop()
            self.run_worker(self.action_play_pause(), exclusive=False)
        elif char in {"F", "f"}:
            event.stop()
            self.run_worker(self.action_next_track(), exclusive=False)
        elif char in {"B", "b"}:
            event.stop()
            self.run_worker(self.action_previous_track(), exclusive=False)
        elif char in {"I", "i"}:
            event.stop()
            self.run_worker(self.action_volume_up(), exclusive=False)
        elif char in {"K", "k"}:
            event.stop()
            self.run_worker(self.action_volume_down(), exclusive=False)
        elif char in {"V", "v"}:
            event.stop()
            self.action_visualizer()
        elif char in {"A", "a"}:
            event.stop()
            self.action_fullscreen_album_art()
        elif char == "R":
            event.stop()
            self.action_research_artist()
        elif char == "r":
            event.stop()
            self.run_worker(self.action_refresh(force=True), exclusive=False)
        elif key == "escape":
            if self.research.visible:
                event.stop()
                self.action_close_research()
        elif char in {"H", "h"}:
            event.stop()
            self.push_screen(HelpScreen())
        elif char in {"D", "d"}:
            event.stop()
            self.action_toggle_debug()
        elif char == "o":
            if self.debug_visible:
                event.stop()
                self.action_debug_scroll_up()
        elif char == "l":
            if self.debug_visible:
                event.stop()
                self.action_debug_scroll_down()
        elif key == "enter":
            if self.research.visible:
                event.stop()
                self.action_research_toggle_column()
        elif char in set("123456789"):
            event.stop()
            self.action_tag_speaker(char)
        elif char == "g":
            event.stop()
            self.run_worker(self.action_group_tagged(), exclusive=False)
        elif char == "G":
            event.stop()
            self.run_worker(self.action_ungroup_selected(), exclusive=False)
        elif key == "up":
            event.stop()
            if self.research.visible:
                self.action_research_up()
            else:
                self.action_cursor_up()
        elif key == "down":
            event.stop()
            if self.research.visible:
                self.action_research_down()
            else:
                self.action_cursor_down()
        elif key == "right":
            event.stop()
            self.action_expand_group()
        elif key == "left":
            event.stop()
            self.action_collapse_group()

    def action_toggle_debug(self) -> None:
        self.debug_visible = not self.debug_visible
        self.debug_scroll = 0
        self._render_debug()
        self._refresh_details_for_layout_change()
        self._set_status("Debug pane shown; o/l scroll" if self.debug_visible else "Debug pane hidden")

    def action_debug_scroll_up(self) -> None:
        self.debug_scroll = max(0, self.debug_scroll - 1)
        self._render_debug()

    def action_debug_scroll_down(self) -> None:
        self.debug_scroll += 1
        self._render_debug()

    def action_close_research(self) -> None:
        self.research.visible = False
        self._render_research()
        self._refresh_details_for_layout_change()
        self._set_status("Every Noise research hidden")

    def action_research_toggle_column(self) -> None:
        self.research.focus_artists = not self.research.focus_artists
        self._render_research()

    def action_research_up(self) -> None:
        if self.research.focus_artists:
            self.research.artist_scroll = max(0, self.research.artist_scroll - 1)
        else:
            self.research.selected_index = max(0, self.research.selected_index - 1)
            self.research.artist_scroll = 0
        self._render_research()

    def action_research_down(self) -> None:
        if self.research.focus_artists:
            selected = self._selected_research_result()
            max_scroll = max(0, len(selected.artists) - 20) if selected else 0
            self.research.artist_scroll = min(max_scroll, self.research.artist_scroll + 1)
        else:
            self.research.selected_index = min(max(0, len(self.research.results) - 1), self.research.selected_index + 1)
            self.research.artist_scroll = 0
        self._render_research()

    def action_cursor_up(self) -> None:
        self.selected_index = max(0, self.selected_index - 1)
        self._render_speakers()
        self._render_details()

    def action_cursor_down(self) -> None:
        self.selected_index = min(max(0, len(self._visible_entries()) - 1), self.selected_index + 1)
        self._render_speakers()
        self._render_details()

    async def action_refresh(self, force: bool = False) -> None:
        if self._visualizer_active():
            return
        if self._refreshing_topology or self._refreshing_tracks:
            return
        self._refreshing_topology = True
        debug_event = self._debug_start("refresh topology", ())
        refresh_tracks = False
        try:
            entries = await asyncio.to_thread(self.service.refresh_topology)
            warnings = getattr(self.service, "warnings", ())
        except Exception as exc:
            self._debug_finish(debug_event, "failed", str(exc))
            self._set_status(f"Refresh failed: {exc}")
        else:
            self._debug_finish(debug_event, "done")
            snapshot = SonosSnapshot(entries=tuple(entries), tracks=tuple(self.tracks), warnings=tuple(warnings))
            if (force or not self._busy_label) and not self._should_defer_snapshot_for_optimistic_groups(snapshot):
                self._apply_snapshot(snapshot)
                entry_speakers = {entry.speaker for entry in self.entries if entry.speaker}
                track_speakers = {track.speaker for track in self.tracks}
                refresh_tracks = force or bool(entry_speakers - track_speakers)
            else:
                self._render_debug()
        finally:
            self._refreshing_topology = False
        if refresh_tracks:
            await self.action_refresh_tracks()

    async def action_refresh_tracks(self) -> None:
        if self._visualizer_active():
            return
        if self._refreshing_tracks or self._refreshing_topology or not self.entries:
            return
        self._refreshing_tracks = True
        debug_event = self._debug_start("refresh tracks", ())
        try:
            tracks = await asyncio.to_thread(self.service.tracks_for_entries, tuple(self.entries))
        except Exception as exc:
            self._debug_finish(debug_event, "failed", str(exc))
            self._set_status(f"Track refresh failed: {exc}")
        else:
            self._debug_finish(debug_event, "done")
            self.tracks = list(tracks)
            if self.is_mounted:
                try:
                    self._render_speakers()
                    self._render_details()
                    self._prefetch_album_art()
                    self._prefetch_similar_artists()
                except ScreenStackError:
                    pass
        finally:
            self._refreshing_tracks = False

    def action_tag_speaker(self, tag: str) -> None:
        entry = self._selected_entry()
        speakers = _entry_speakers(entry)
        if not speakers:
            return

        for speaker in speakers:
            previous = self.speaker_tags.get(speaker)
            if previous == tag:
                self.speaker_tags.pop(speaker, None)
                self._remove_from_tag_order(previous, speaker)
            else:
                if previous:
                    self._remove_from_tag_order(previous, speaker)
                self.speaker_tags[speaker] = tag
                self.tag_order.setdefault(tag, [])
                if speaker not in self.tag_order[tag]:
                    self.tag_order[tag].append(speaker)

        self._set_status(f"Tag {tag}: {', '.join(self.tag_order.get(tag, [])) or 'empty'}")
        self._render_speakers()

    async def action_group_tagged(self) -> None:
        if self._commands_paused():
            return
        entry = self._selected_entry()
        tag = _entry_tag(entry, self.speaker_tags)
        if not tag:
            tagged_groups = [key for key, speakers in self.tag_order.items() if len(speakers) >= 2]
            tag = tagged_groups[0] if len(tagged_groups) == 1 else ""
        speakers = [speaker for speaker in self.tag_order.get(tag, []) if speaker in self.speaker_tags]
        if len(speakers) < 2:
            self._set_status("Tag at least two speakers with the same number before pressing g")
            return
        speakers = list(_expand_existing_group_members(tuple(speakers), self.entries))
        source = _grouping_source(speakers, self.entries)
        debug_event = self._debug_start("group speakers", speakers)
        self._begin_busy("group", speakers)
        previous_entries = list(self.entries)
        previous_tracks = list(self.tracks)
        previous_expanded_groups = set(self.expanded_groups)
        previous_collapsed_groups = set(self.collapsed_groups)
        previous_selected_index = self.selected_index
        optimistic_key = tuple(sorted(speakers))
        self._optimistic_groups[optimistic_key] = time.monotonic() + OPTIMISTIC_GROUP_TTL_SECONDS
        self._apply_optimistic_group(source, tuple(speakers))
        try:
            await asyncio.to_thread(self.service.group_speakers, source, tuple(speakers))
        except Exception as exc:
            self._debug_finish(debug_event, "failed", str(exc))
            self._optimistic_groups.pop(optimistic_key, None)
            self.entries = previous_entries
            self.tracks = previous_tracks
            self.expanded_groups = previous_expanded_groups
            self.collapsed_groups = previous_collapsed_groups
            self.selected_index = previous_selected_index
            self._render_speakers()
            self._render_details()
            self._set_status(f"group failed: {exc}")
        else:
            self._debug_finish(debug_event, "sent")
            for speaker in speakers:
                self.speaker_tags.pop(speaker, None)
            self.tag_order.pop(tag, None)
            self._pending_expand_members.add(tuple(sorted(speakers)))
            self._set_status(f"Grouped {', '.join(speakers)} from {source}")
            await self.action_refresh(force=True)
        finally:
            self._command_cooldown_until = time.monotonic() + 0.75
            self._end_busy()

    async def action_ungroup_selected(self) -> None:
        if self._commands_paused():
            return
        entry = self._selected_entry()
        speakers = _entry_speakers(entry)
        if not speakers:
            self._set_status("No speaker selected")
            return
        single_member = bool(entry and not entry.is_group and _is_group_member(entry, self.entries) and entry.speaker)
        label = "remove speaker from group" if single_member else "ungroup speakers"
        debug_event = self._debug_start(label, speakers)
        self._begin_busy("ungroup", speakers)
        previous_entries = list(self.entries)
        previous_tracks = list(self.tracks)
        previous_expanded_groups = set(self.expanded_groups)
        previous_collapsed_groups = set(self.collapsed_groups)
        previous_selected_index = self.selected_index
        if single_member and entry and entry.speaker:
            self._apply_optimistic_member_removal(entry.speaker)
        else:
            self._apply_optimistic_ungroup(tuple(speakers))
        try:
            if single_member and entry and entry.speaker:
                await asyncio.to_thread(self.service.remove_speaker_from_group, entry.speaker, True)
            else:
                await asyncio.to_thread(self.service.ungroup_speakers, tuple(speakers), True)
        except Exception as exc:
            self._debug_finish(debug_event, "failed", str(exc))
            self.entries = previous_entries
            self.tracks = previous_tracks
            self.expanded_groups = previous_expanded_groups
            self.collapsed_groups = previous_collapsed_groups
            self.selected_index = previous_selected_index
            self._render_speakers()
            self._render_details()
            self._set_status(f"ungroup failed: {exc}")
        else:
            self._debug_finish(debug_event, "sent")
            for speaker in speakers:
                tag = self.speaker_tags.pop(speaker, "")
                if tag:
                    self._remove_from_tag_order(tag, speaker)
            if single_member:
                self._set_status(f"Removed and paused {', '.join(speakers)}")
            else:
                self._set_status(f"Removed {', '.join(speakers)} from group and stopped playback")
            await self.action_refresh(force=True)
        finally:
            self._command_cooldown_until = time.monotonic() + 0.75
            self._end_busy()

    def _remove_from_tag_order(self, tag: str, speaker: str) -> None:
        speakers = self.tag_order.get(tag)
        if not speakers:
            return
        if speaker in speakers:
            speakers.remove(speaker)
        if not speakers:
            self.tag_order.pop(tag, None)

    def action_expand_group(self) -> None:
        entry = self._selected_entry()
        if entry and entry.is_group:
            self.collapsed_groups.discard(entry.key)
            self.expanded_groups.add(entry.key)
            self._set_status(f"Expanded {entry.label.strip()}")
            self._render_speakers()

    def action_collapse_group(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        if entry.is_group:
            self.collapsed_groups.add(entry.key)
            self.expanded_groups.discard(entry.key)
            self._set_status(f"Collapsed {entry.label.strip()}")
        else:
            parent = next((item for item in self.entries if item.is_group and entry.speaker in item.members), None)
            if parent:
                self.collapsed_groups.add(parent.key)
                self.expanded_groups.discard(parent.key)
                self.selected_index = self._visible_entries().index(parent)
                self._set_status(f"Collapsed {parent.label.strip()}")
        self._render_speakers()

    async def action_play_pause(self) -> None:
        await self._run_control("play/pause", lambda entry: self.service.play_pause(entry))

    async def action_next_track(self) -> None:
        await self._run_control("next", lambda entry: self.service.next(entry))

    async def action_previous_track(self) -> None:
        await self._run_control("previous", lambda entry: self.service.previous(entry))

    async def action_volume_up(self) -> None:
        await self._run_control("volume up", lambda entry: self.service.change_volume(entry, 5))

    async def action_volume_down(self) -> None:
        await self._run_control("volume down", lambda entry: self.service.change_volume(entry, -5))

    def action_visualizer(self) -> None:
        self.push_screen(VisualizerScreen())

    def action_fullscreen_album_art(self) -> None:
        item = self._selected_detail_item()
        if not item:
            self.push_screen(FullscreenAlbumArtScreen("No speaker selected"))
            return
        label, track, _volumes = item
        if track.error or not track.album_art_url:
            self.push_screen(FullscreenAlbumArtScreen(label))
            return
        self.push_screen(FullscreenAlbumArtScreen(label, track, self.album_art))

    def action_research_artist(self) -> None:
        artist = next(
            (track.artist.strip() for _label, track, _volumes in self._detail_items() if track.artist.strip() and not track.error),
            "",
        )
        if not artist:
            self._set_status("No artist available for Every Noise research")
            return
        if self.research.visible and self.research.artist.casefold() == artist.casefold():
            self.action_close_research()
            return
        self.research = ResearchState(visible=True, artist=artist, loading=True, job_artist=artist)
        self._set_status(f"Researching {artist} on Every Noise")
        self._render_research()
        self._refresh_details_for_layout_change()
        self.run_worker(self._load_research_results(artist), exclusive=False)

    async def _load_research_results(self, artist: str) -> None:
        try:
            results = await asyncio.to_thread(self.every_noise.search_artist_genres, artist, 10)
        except Exception as exc:
            if self.research.job_artist == artist:
                self.research.error = str(exc)
                self.research.results = ()
        else:
            if self.research.job_artist == artist:
                self.research.results = results
                self.research.error = ""
        finally:
            if self.research.job_artist == artist:
                self.research.loading = False
        self._render_research()

    def _selected_research_result(self) -> GenreResult | None:
        if not self.research.results:
            return None
        index = min(max(0, self.research.selected_index), len(self.research.results) - 1)
        return self.research.results[index]

    def _refresh_details_for_layout_change(self) -> None:
        if not self.is_mounted:
            return
        try:
            self._render_details()
            self._prefetch_album_art()
        except ScreenStackError:
            pass

    async def _run_control(self, label: str, func) -> None:
        if self.view_only:
            self._set_status("View-only mode: controls disabled")
            return
        if self._commands_paused():
            return
        targets = self._control_entries()
        if not targets:
            self._set_status("No speaker selected")
            return
        busy_speakers = tuple(dict.fromkeys(speaker for entry in targets for speaker in _entry_speakers(entry)))
        debug_event = self._debug_start(label, busy_speakers)
        self._begin_busy(label, busy_speakers)
        try:
            await asyncio.gather(*(asyncio.to_thread(func, entry) for entry in targets))
        except Exception as exc:
            self._debug_finish(debug_event, "failed", str(exc))
            self._set_status(f"{label} failed: {exc}")
        else:
            self._debug_finish(debug_event, "sent")
            self._set_status(f"{label} sent")
            await self.action_refresh(force=True)
        finally:
            self._command_cooldown_until = time.monotonic() + 0.75
            self._end_busy()

    def _apply_snapshot(self, snapshot: SonosSnapshot) -> None:
        if self._should_defer_snapshot_for_optimistic_groups(snapshot):
            self._render_debug()
            return

        selected_key = self._selected_entry().key if self._selected_entry() else ""
        self.entries = list(snapshot.entries)
        valid_track_speakers = {entry.speaker for entry in self.entries if entry.speaker}
        self.tracks = [track for track in snapshot.tracks if track.speaker in valid_track_speakers]
        if snapshot.warnings and not self.entries:
            self._set_status("; ".join(snapshot.warnings[-2:]))
        valid_speakers = valid_track_speakers
        self.speaker_tags = {speaker: tag for speaker, tag in self.speaker_tags.items() if speaker in valid_speakers}
        self.tag_order = {
            tag: [speaker for speaker in speakers if speaker in valid_speakers and self.speaker_tags.get(speaker) == tag]
            for tag, speakers in self.tag_order.items()
        }
        self.tag_order = {tag: speakers for tag, speakers in self.tag_order.items() if speakers}
        valid_group_keys = {entry.key for entry in self.entries if entry.is_group}
        self.collapsed_groups.intersection_update(valid_group_keys)
        self.expanded_groups = valid_group_keys - self.collapsed_groups
        for entry in self.entries:
            if entry.is_group and tuple(sorted(entry.members)) in self._pending_expand_members:
                self.collapsed_groups.discard(entry.key)
                self.expanded_groups.add(entry.key)
        if self._pending_expand_members:
            visible_groups = {tuple(sorted(entry.members)) for entry in self.entries if entry.is_group}
            self._pending_expand_members = {
                members for members in self._pending_expand_members if members not in visible_groups
            }
        visible_keys = [entry.key for entry in self._visible_entries()]
        if selected_key in visible_keys:
            self.selected_index = visible_keys.index(selected_key)
        else:
            self.selected_index = min(self.selected_index, max(0, len(visible_keys) - 1))
        if self.is_mounted:
            try:
                self._render_speakers()
                self._render_details()
                self._prefetch_album_art()
                self._prefetch_similar_artists()
            except ScreenStackError:
                pass

    def _should_defer_snapshot_for_optimistic_groups(self, snapshot: SonosSnapshot) -> bool:
        if not self._optimistic_groups:
            return False

        now = time.monotonic()
        visible_groups = {tuple(sorted(entry.members)) for entry in snapshot.entries if entry.is_group}
        self._optimistic_groups = {
            members: expires_at
            for members, expires_at in self._optimistic_groups.items()
            if expires_at > now and members not in visible_groups
        }
        return bool(self._optimistic_groups)

    def _apply_optimistic_group(self, source: str, speakers: tuple[str, ...]) -> None:
        members = tuple(dict.fromkeys(speakers))
        member_set = set(members)
        group = SpeakerEntry(
            label=_optimistic_group_label(members),
            is_group=True,
            members=members,
            coordinator=source,
        )
        member_entries = [
            SpeakerEntry(label=speaker, speaker=speaker, members=(speaker,), coordinator=source)
            for speaker in members
        ]
        remaining = [
            entry
            for entry in self.entries
            if not (entry.speaker in member_set or (entry.is_group and set(entry.members).intersection(member_set)))
        ]
        insert_at = min(
            (index for index, entry in enumerate(self.entries) if entry.speaker in member_set),
            default=len(remaining),
        )
        insert_at = min(insert_at, len(remaining))
        self.entries = [*remaining[:insert_at], group, *member_entries, *remaining[insert_at:]]
        self.collapsed_groups.discard(group.key)
        self.expanded_groups.add(group.key)
        visible_keys = [entry.key for entry in self._visible_entries()]
        self.selected_index = visible_keys.index(group.key) if group.key in visible_keys else min(self.selected_index, max(0, len(visible_keys) - 1))
        self._set_status(f"Grouping {', '.join(members)}...")
        self._render_speakers()
        self._render_details()

    def _apply_optimistic_member_removal(self, speaker: str) -> None:
        parent = next((entry for entry in self.entries if entry.is_group and speaker in entry.members), None)
        if parent is None:
            return
        remaining_members = tuple(member for member in parent.members if member != speaker)
        replacement_group = (
            SpeakerEntry(
                label=_optimistic_group_label(remaining_members),
                is_group=True,
                members=remaining_members,
                coordinator=parent.coordinator if parent.coordinator in remaining_members else remaining_members[0],
            )
            if len(remaining_members) > 1
            else None
        )
        output: list[SpeakerEntry] = []
        inserted = False
        for entry in self.entries:
            if entry.key == parent.key:
                if replacement_group:
                    output.append(replacement_group)
                    self.collapsed_groups.discard(replacement_group.key)
                    self.expanded_groups.add(replacement_group.key)
                    output.extend(
                        SpeakerEntry(label=member, speaker=member, members=(member,), coordinator=replacement_group.coordinator)
                        for member in remaining_members
                    )
                elif remaining_members:
                    member = remaining_members[0]
                    output.append(SpeakerEntry(label=member, speaker=member, members=(member,), coordinator=member))
                output.append(SpeakerEntry(label=speaker, speaker=speaker, members=(speaker,), coordinator=speaker))
                inserted = True
                continue
            if entry.speaker in parent.members or entry.key == parent.key:
                continue
            output.append(entry)
        if inserted:
            self.collapsed_groups.discard(parent.key)
            self.expanded_groups.discard(parent.key)
            self.entries = output
            self.selected_index = min(self.selected_index, max(0, len(self._visible_entries()) - 1))
            self._set_status(f"Removing and pausing {speaker}...")
            self._render_speakers()
            self._render_details()

    def _apply_optimistic_ungroup(self, speakers: tuple[str, ...]) -> None:
        speaker_set = set(speakers)
        output: list[SpeakerEntry] = []
        inserted: set[str] = set()
        for entry in self.entries:
            if entry.is_group and set(entry.members).issubset(speaker_set):
                self.collapsed_groups.discard(entry.key)
                self.expanded_groups.discard(entry.key)
                for member in entry.members:
                    output.append(SpeakerEntry(label=member, speaker=member, members=(member,), coordinator=member))
                    inserted.add(member)
                continue
            if entry.speaker in speaker_set and entry.speaker in inserted:
                continue
            output.append(entry)
        self.entries = output
        self.selected_index = min(self.selected_index, max(0, len(self._visible_entries()) - 1))
        self._set_status(f"Ungrouping {', '.join(speakers)}...")
        self._render_speakers()
        self._render_details()

    def _render_speakers(self) -> None:
        visible = self._visible_entries()
        self.selected_index = min(self.selected_index, max(0, len(visible) - 1))
        speaker_list = self.query_one("#speakers", Static)
        output = Text()
        track_by_speaker = {track.speaker: track for track in self.tracks}
        for index, entry in enumerate(visible):
            indent = "  " if _is_group_member(entry, self.entries) else ""
            prefix = "# " if entry.is_group else f"{indent}> "
            state = _speaker_state_indicator(entry, self.entries, track_by_speaker)
            tag = _entry_tag(entry, self.speaker_tags)
            tag_text = f"[{tag}]" if tag else "   "
            spinner = self._speaker_spinner(entry)
            base = f"{tag_text} {prefix}"
            label = _speaker_row_label(entry, max(4, 30 - len(base) - len(state) - len(spinner)))
            line = f"{base}{label}{state}{spinner}"
            style = "bold black on cyan" if index == self.selected_index else "yellow" if tag else "white"
            output.append(line.ljust(30), style=style)
            if index < len(visible) - 1:
                output.append("\n")
        speaker_list.update(output if visible else Text("No speakers discovered", style="dim"))

    def _speaker_spinner(self, entry: SpeakerEntry) -> str:
        if not self._busy_speakers:
            return ""
        if not set(_entry_speakers(entry)).intersection(self._busy_speakers):
            return ""
        return f" {SPINNER_CHARS[self._spinner_index % len(SPINNER_CHARS)]}"

    def _render_details(self) -> None:
        details = self.query_one("#details", Static)
        items = self._detail_items()
        if not items:
            details.update("Waiting for speakers...")
            return

        output = Text()
        for label, track, volumes in items:
            if len(output):
                output.append("\n\n")
            metadata_text = _track_text(label, track, volumes)
            similar = self.similar_artists.get(track.artist.strip().casefold())
            if similar:
                metadata_text = f"{metadata_text}\nSimilar Artists: {', '.join(similar[:6])}"
            elif track.artist.strip():
                metadata_text = f"{metadata_text}\nSimilar Artists: loading..."
            compact_layout = self._details_use_compact_art()
            art = self.album_art.cache("compact" if compact_layout else "full").get(_track_signature(track))
            if art and art.is_available:
                if compact_layout:
                    output.append(_track_with_side_album_art_text(metadata_text, art))
                else:
                    output.append(metadata_text)
                    output.append("\n\n")
                    output.append(_album_art_text(art))
            else:
                output.append(metadata_text)
        details.update(output)

    def _prefetch_album_art(self) -> None:
        for _label, track, _volumes in self._detail_items():
            signature = _track_signature(track)
            if not track.album_art_url:
                continue
            self._queue_album_art(track, signature, "full")
            if self._details_use_compact_art():
                self._queue_album_art(track, signature, "compact")

    def _queue_album_art(self, track: TrackInfo, signature: str, variant: str) -> None:
        cache = self.album_art.cache(variant)
        job_key = (signature, variant)
        if signature in cache or job_key in self.album_art.jobs:
            return
        cache[signature] = AlbumArt(signature=signature, error="loading")
        self.album_art.jobs.add(job_key)
        self.run_worker(self._load_album_art_variant(track, signature, variant), exclusive=False)

    def _details_use_compact_art(self) -> bool:
        return self.debug_visible and self.research.visible

    def _prefetch_similar_artists(self) -> None:
        for _label, track, _volumes in self._detail_items():
            artist = track.artist.strip()
            key = artist.casefold()
            if not artist or key in self.similar_artists or key in self.similar_artist_jobs:
                continue
            self.similar_artist_jobs.add(key)
            self.run_worker(self._load_similar_artists(artist, key), exclusive=False)

    async def _load_similar_artists(self, artist: str, key: str) -> None:
        try:
            similar = await asyncio.to_thread(self.every_noise.similar_artists, artist)
            self.similar_artists[key] = similar
        except Exception:
            self.similar_artists[key] = ()
        finally:
            self.similar_artist_jobs.discard(key)
        self._render_details()

    async def _load_album_art_variant(self, track: TrackInfo, signature: str, variant: str) -> None:
        await self.album_art.load_variant(track, signature, variant)
        self._render_details()

    def _visible_entries(self) -> list[SpeakerEntry]:
        visible: list[SpeakerEntry] = []
        collapsed: set[str] = set()
        for entry in self.entries:
            if entry.is_group:
                visible.append(entry)
                if entry.key in self.collapsed_groups:
                    collapsed.update(entry.members)
                continue
            if entry.speaker and entry.speaker in collapsed:
                continue
            visible.append(entry)
        return visible

    def _selected_entry(self) -> SpeakerEntry | None:
        visible = self._visible_entries()
        if not visible:
            return None
        return visible[min(self.selected_index, len(visible) - 1)]

    def _control_entries(self) -> list[SpeakerEntry]:
        entry = self._selected_entry()
        return [entry] if entry else []

    def _detail_items(self) -> list[tuple[str, TrackInfo, tuple[tuple[str, int], ...]]]:
        entries = self._control_entries()
        items: list[tuple[str, TrackInfo, tuple[tuple[str, int], ...]]] = []
        covered: set[str] = set()
        for entry in entries:
            item = self._detail_item_for_entry(entry)
            if item and not set(_entry_speakers(entry)).intersection(covered):
                items.append(item)
                covered.update(_entry_speakers(entry))
        return items

    def _selected_detail_item(self) -> tuple[str, TrackInfo, tuple[tuple[str, int], ...]] | None:
        entry = self._selected_entry()
        return self._detail_item_for_entry(entry) if entry else None

    def _detail_item_for_entry(self, entry: SpeakerEntry | None) -> tuple[str, TrackInfo, tuple[tuple[str, int], ...]] | None:
        if entry is None:
            return None
        track_by_speaker = {track.speaker: track for track in self.tracks}
        if entry.is_group:
            track = _shared_track_for_group(entry, track_by_speaker)
            if track:
                return ", ".join(entry.members), track, _volumes_for(entry.members, track_by_speaker)
            return None
        if entry.speaker:
            track = track_by_speaker.get(entry.speaker, TrackInfo(speaker=entry.speaker, error="Waiting for refresh"))
            return entry.label.strip(), track, _volumes_for((entry.speaker,), track_by_speaker)
        return None

    def _set_status(self, message: str) -> None:
        self.message = message
        if self.is_mounted:
            try:
                self.query_one("#status", Static).update(message)
            except ScreenStackError:
                pass

    def _debug_start(self, label: str, speakers: tuple[str, ...] | list[str]) -> DebugEvent:
        event = DebugEvent(label=label, speakers=tuple(speakers), started_at=time.monotonic())
        self.debug_events.append(event)
        if len(self.debug_events) > 100:
            del self.debug_events[: len(self.debug_events) - 100]
        return event

    def _debug_finish(self, event: DebugEvent, status: str, error: str = "") -> None:
        if event.status != "running":
            return
        event.status = status
        event.error = error
        event.finished_at = time.monotonic()

    def _debug_lines(self) -> list[str]:
        if not self.debug_events:
            return ["No SoCo commands recorded yet."]
        grouped: dict[tuple[str, tuple[str, ...], str, str], tuple[DebugEvent, int]] = {}
        for event in self.debug_events:
            if event.status == "running":
                continue
            key = (event.label, event.speakers, event.status, event.error)
            previous, count = grouped.get(key, (event, 0))
            latest_time = event.finished_at or event.started_at
            previous_time = previous.finished_at or previous.started_at
            grouped[key] = (event if latest_time >= previous_time else previous, count + 1)

        rows = [event for event, _count in grouped.values()]
        rows.sort(key=lambda event: event.finished_at or event.started_at, reverse=True)

        lines: list[str] = []
        for event in rows[:80]:
            if event.status == "failed":
                icon = "!"
            else:
                icon = "+"
            duration = _elapsed_text((event.finished_at or time.monotonic()) - event.started_at)
            count = ""
            if event.status != "running":
                count_value = grouped.get((event.label, event.speakers, event.status, event.error), (event, 1))[1]
                count = f" x{count_value}" if count_value > 1 else ""
            speakers = ", ".join(event.speakers) if event.speakers else "system"
            suffix = f" - {event.error}" if event.error else ""
            lines.append(f"{icon} {event.status.upper():7} {event.label}{count} -> {speakers} ({duration}){suffix}")
        return lines or ["No completed SoCo commands yet."]

    def _debug_status_line(self) -> str:
        running = [event for event in self.debug_events if event.status == "running"]
        if not running:
            return "idle"
        event = running[-1]
        icon = SPINNER_CHARS[self._spinner_index % len(SPINNER_CHARS)]
        speakers = ", ".join(event.speakers) if event.speakers else "system"
        elapsed = _elapsed_text(time.monotonic() - event.started_at)
        suffix = f" +{len(running) - 1} more" if len(running) > 1 else ""
        return f"{icon} {event.label} -> {speakers} ({elapsed}){suffix}"

    def _render_debug(self) -> None:
        if not self.is_mounted:
            return
        try:
            title = self.query_one("#debug-title", Static)
            pane = self.query_one("#debug-pane", Static)
        except ScreenStackError:
            return
        title.display = self.debug_visible
        pane.display = self.debug_visible
        if not self.debug_visible:
            return
        lines = self._debug_lines()
        visible_count = 5
        max_scroll = max(0, len(lines) - visible_count)
        self.debug_scroll = min(self.debug_scroll, max_scroll)
        visible = lines[self.debug_scroll : self.debug_scroll + visible_count]
        range_text = f"{self.debug_scroll + 1}-{min(len(lines), self.debug_scroll + visible_count)} of {len(lines)}"
        footer = f"o up | l down | {range_text}"
        status = f"running: {self._debug_status_line()}"
        pane.update(Text("\n".join([*visible, "", footer, status]), style="white on black"))

    def _render_research(self) -> None:
        if not self.is_mounted:
            return
        try:
            title = self.query_one("#research-title", Static)
            pane = self.query_one("#research-pane", Static)
        except ScreenStackError:
            return
        title.display = self.research.visible
        pane.display = self.research.visible
        if not self.research.visible:
            return
        pane.update(
            Text(
                "\n".join(
                    _research_lines(
                        self.research.artist,
                        self.research.results,
                        self.research.selected_index,
                        self.research.artist_scroll,
                        self.research.focus_artists,
                        loading=self.research.loading,
                        error=self.research.error,
                    )
                ),
                style="white on black",
            )
        )

    def _begin_busy(self, label: str, speakers: tuple[str, ...] | list[str], *, show_status: bool = True) -> None:
        self._busy_label = label
        self._busy_started_at = time.monotonic()
        self._busy_speakers = set(speakers)
        if show_status:
            self._set_busy_status()
        if self.is_mounted:
            try:
                self._render_speakers()
            except ScreenStackError:
                pass
        self._render_debug()

    def _end_busy(self) -> None:
        self._busy_label = ""
        self._busy_started_at = 0.0
        self._busy_speakers.clear()
        if self.is_mounted:
            try:
                self._render_speakers()
            except ScreenStackError:
                pass
        self._render_debug()

    def _set_busy_status(self) -> None:
        if not self._busy_label:
            return
        elapsed = _elapsed_text(time.monotonic() - self._busy_started_at)
        speakers = ", ".join(sorted(self._busy_speakers)) if self._busy_speakers else "system"
        self._set_status(f"{SPINNER_CHARS[self._spinner_index % len(SPINNER_CHARS)]} {self._busy_label} -> {speakers} ({elapsed})")

    def _tick_status(self) -> None:
        self._spinner_index = (self._spinner_index + 1) % len(SPINNER_CHARS)
        if self._busy_label:
            if self._busy_label != "refresh":
                self._set_busy_status()
            self._render_speakers()
            self._render_debug()

    def _commands_paused(self) -> bool:
        if self._busy_label:
            self._set_busy_status()
            return True
        remaining = self._command_cooldown_until - time.monotonic()
        if remaining > 0:
            self._set_status(f"Command just sent; waiting {remaining:.1f}s for Sonos")
            return True
        return False

    def _visualizer_active(self) -> bool:
        try:
            return isinstance(self.screen, VisualizerScreen)
        except ScreenStackError:
            return False


class HelpScreen(ModalScreen[None]):
    def compose(self) -> ComposeResult:
        yield Static(
            "\n".join(
                [
                    "[ Sonos Now Help ]",
                    "",
                    "Navigation",
                    "  Up / Down      Move speaker highlight",
                    "  Left / Right   Collapse / expand grouped speakers",
                    "  h              Show this help",
                    "  d              Toggle SoCo debug pane",
                    "  o / l          Scroll debug pane up / down",
                    "  q              Quit",
                    "",
                    "Playback",
                    "  p              Play / pause highlighted speaker or group",
                    "  f              Next track",
                    "  b              Previous track",
                    "  i              Volume up",
                    "  k              Volume down",
                    "  A              Fullscreen album art for highlighted row",
                    "  r              Refresh now",
                    "  R              Every Noise artist research",
                    "",
                    "Grouping",
                    "  1-9            Tag highlighted speaker for grouping",
                    "  g              Group speakers with the highlighted tag",
                    "                 First tagged speaker becomes the source",
                    "  G              Remove highlighted speaker/group and stop playback",
                    "",
                    "Visualizer",
                    "  v              Open fullscreen visualizer",
                    "  Left / Right   Cycle visualizer styles",
                    "  Any other key  Return from visualizer",
                    "",
                    "Press Esc, Enter, Space, or h to close.",
                ]
            ),
            id="help-modal",
        )

    def on_key(self, event) -> None:
        if event.key in {"escape", "enter", "space"} or (getattr(event, "character", "") or "") in {"h", "H"}:
            event.stop()
            self.dismiss()


class FullscreenAlbumArtScreen(Screen[None]):
    CSS = """
    FullscreenAlbumArtScreen {
        background: black;
    }

    #fullscreen-art {
        height: 1fr;
        background: black;
        color: white;
    }
    """

    def __init__(
        self,
        label: str,
        track: TrackInfo | None = None,
        album_art: AlbumArtManager | None = None,
    ) -> None:
        super().__init__()
        self.label = label
        self.track = track
        self.album_art = album_art or AlbumArtManager()
        self.error = ""
        self.current_art: AlbumArt | None = None
        self.started_at = time.monotonic()

    def compose(self) -> ComposeResult:
        yield Static(id="fullscreen-art")

    def on_mount(self) -> None:
        self.set_interval(0.18, self._tick_art)
        self._render_loading_or_fallback()
        if self.track and self.track.album_art_url:
            self.run_worker(self._load(), exclusive=True)

    def on_resize(self) -> None:
        if self.track and self.track.album_art_url:
            self.run_worker(self._load(), exclusive=True)
        else:
            self._render_loading_or_fallback()

    def on_key(self, event) -> None:
        event.stop()
        self.dismiss()

    async def _load(self) -> None:
        if not self.track:
            self._render_loading_or_fallback()
            return
        signature = _track_signature(self.track)
        width, height = _fullscreen_art_size(self.size.width, self.size.height)
        try:
            art = await self.album_art.fullscreen_art(self.track, signature, width, height)
        except Exception as exc:
            self.error = str(exc)
            self._render_loading_or_fallback()
            return
        self._render_art(art)

    def _render_loading_or_fallback(self) -> None:
        if not self.is_mounted:
            return
        title = _fullscreen_art_title(self.label, self.track)
        if self.track and self.track.album_art_url and not self.error:
            text = Text(f"\n{title.center(max(1, self.size.width))}\n\nLoading album art...", style="white on black")
        else:
            text = _muted_speaker_text(title, self.size.width, self.size.height, self.error)
        self.query_one("#fullscreen-art", Static).update(text)

    def _render_art(self, art: AlbumArt) -> None:
        self.current_art = art
        self._draw_art()

    def _tick_art(self) -> None:
        if self.current_art is not None:
            self._draw_art()

    def _draw_art(self) -> None:
        if not self.is_mounted:
            return
        if self.current_art is None:
            return
        title = _fullscreen_art_title(self.label, self.track)
        frame = int((time.monotonic() - self.started_at) * 8)
        text = _fullscreen_album_art_text(title, self.current_art, self.size.width, frame)
        self.query_one("#fullscreen-art", Static).update(text)
