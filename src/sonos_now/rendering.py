from __future__ import annotations

from rich.text import Text

from .ascii_art import AlbumArt
from .everynoise import GenreResult
from .grouping import is_group_member, shared_track_for_group
from .models import SpeakerEntry, TrackInfo
from .progress import progress_bar
from .timefmt import format_duration

ART_STYLES = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
FULL_ALBUM_ART_SIZE = (56, 24)
COMPACT_ALBUM_ART_SIZE = (28, 12)
SIDE_BY_SIDE_METADATA_WIDTH = 44
MIN_FULLSCREEN_ART_SIZE = (32, 12)


def track_text(label: str, track: TrackInfo, volumes: tuple[tuple[str, int], ...]) -> str:
    if track.error:
        return f"[{label}]\nerror: {track.error}"
    return "\n".join(metadata_lines(label, track, volumes))


def metadata_lines(label: str, track: TrackInfo, volumes: tuple[tuple[str, int], ...]) -> list[str]:
    elapsed = format_duration(track.position)
    total = format_duration(track.duration)
    percent = f"{int((track.progress or 0) * 100):3d}%" if track.progress is not None else " --%"
    return [
        f"[{label}]",
        f"Song   : {track.title or 'Unknown title'}",
        f"Artist : {track.artist or 'Unknown artist'}",
        f"Album  : {track.album or 'Unknown album'}",
        f"Volume : {volume_text(volumes, track)}",
        f"Time   : {elapsed} / {total} {track.playback_state} {percent}".rstrip(),
        f"Progress {progress_bar(track.progress, 36)}",
    ]


def album_art_text(album_art: AlbumArt) -> Text:
    text = Text()
    for index, row in enumerate(album_art_rows(album_art)):
        if index:
            text.append("\n")
        text.append_text(row)
    return text


def track_with_side_album_art_text(track_text_value: str, album_art: AlbumArt) -> Text:
    left_lines = [ellipsize(line, SIDE_BY_SIDE_METADATA_WIDTH) for line in track_text_value.splitlines()]
    art_rows = album_art_rows(album_art)
    row_count = max(len(left_lines), len(art_rows))
    text = Text()
    for index in range(row_count):
        if index:
            text.append("\n")
        left = left_lines[index] if index < len(left_lines) else ""
        text.append(left.ljust(SIDE_BY_SIDE_METADATA_WIDTH))
        if index < len(art_rows):
            text.append("  ")
            text.append_text(art_rows[index])
    return text


def album_art_rows(album_art: AlbumArt, animation_frame: int | None = None) -> list[Text]:
    rows: list[Text] = []
    width = max((len(line) for line in album_art.lines), default=0)
    border_style = album_art_border_style(animation_frame)
    if width:
        rows.append(Text("+" + "-" * width + "+", style=border_style))
    for row_index, line in enumerate(album_art.lines):
        row = Text()
        colors = album_art.colors[row_index] if row_index < len(album_art.colors) else ()
        row.append("|", style=border_style)
        padded = line.ljust(width)
        for col_index, char in enumerate(padded):
            color_index = colors[col_index] if col_index < len(colors) else 7
            row.append(char, style=album_art_pixel_style(color_index, row_index, col_index, char, animation_frame))
        row.append("|", style=border_style)
        rows.append(row)
    if width:
        rows.append(Text("+" + "-" * width + "+", style=border_style))
    return rows


def fullscreen_album_art_text(title: str, album_art: AlbumArt, screen_width: int, animation_frame: int | None = None) -> Text:
    width = max(1, screen_width)
    accent = fullscreen_animation_accent(animation_frame)
    text = Text(title.center(width), style=f"bold {accent} on black")
    text.append("\n")
    for row in album_art_rows(album_art, animation_frame):
        pad = max(0, (width - len(row.plain)) // 2)
        text.append(" " * pad)
        text.append_text(row)
        text.append("\n")
    text.append(" any key returns ".center(width), style=f"bold {accent} on black")
    return text


def album_art_border_style(animation_frame: int | None = None) -> str:
    if animation_frame is None:
        return "cyan on black"
    colors = ("cyan", "cyan", "blue", "cyan", "magenta", "cyan")
    return f"{colors[(animation_frame // 5) % len(colors)]} on black"


def album_art_pixel_style(
    color_index: int,
    row: int,
    col: int,
    char: str,
    animation_frame: int | None = None,
) -> str:
    color_index = max(0, min(7, color_index))
    if animation_frame is None or char == " ":
        return f"{ART_STYLES[color_index]} on black"
    shimmer = (row * 7 + col * 11 + animation_frame) % 43 == 0
    slow_wave = (row + animation_frame // 2) % 17 == 0 and col % 5 == 0
    if shimmer:
        return "bold white on black"
    if slow_wave:
        return f"bold {ART_STYLES[(color_index + 1) % len(ART_STYLES)]} on black"
    return f"{ART_STYLES[color_index]} on black"


def fullscreen_animation_accent(animation_frame: int | None = None) -> str:
    if animation_frame is None:
        return "white"
    accents = ("white", "cyan", "white", "magenta", "white", "blue")
    return accents[(animation_frame // 8) % len(accents)]


def fullscreen_art_title(label: str, track: TrackInfo | None) -> str:
    if track and not track.error:
        parts = [part for part in (track.title.strip(), track.artist.strip(), track.album.strip()) if part]
        if parts:
            return f" {label}: {' - '.join(parts[:3])} "
    return f" {label}: no active album art "


def fullscreen_art_size(screen_width: int, screen_height: int) -> tuple[int, int]:
    available_width = max(MIN_FULLSCREEN_ART_SIZE[0], screen_width - 4)
    available_height = max(MIN_FULLSCREEN_ART_SIZE[1], screen_height - 4)
    height = min(available_height, max(MIN_FULLSCREEN_ART_SIZE[1], available_width // 2))
    width = min(available_width, max(MIN_FULLSCREEN_ART_SIZE[0], height * 2))
    return width, height


def muted_speaker_text(title: str, screen_width: int, screen_height: int, error: str = "") -> Text:
    width = max(1, screen_width)
    art_width, art_height = fullscreen_art_size(screen_width, screen_height)
    speaker_lines = muted_speaker_lines(art_width, art_height)
    text = Text(title.center(width), style="bold white on black")
    text.append("\n")
    for line in speaker_lines:
        text.append(line.center(width), style="bold red on black")
        text.append("\n")
    message = "No active album art"
    if error:
        message = f"Album art unavailable: {ellipsize(error, max(16, width - 4))}"
    text.append(message.center(width), style="bold yellow on black")
    text.append("\n")
    text.append(" any key returns ".center(width), style="bold cyan on black")
    return text


def muted_speaker_lines(width: int, height: int) -> tuple[str, ...]:
    width = max(24, width)
    height = max(12, height)
    rows = [[" " for _ in range(width)] for _ in range(height)]
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    radius = min(width / 2.4, height / 2.1)

    for row in range(height):
        for col in range(width):
            dx = col - center_x
            dy = (row - center_y) * 2.0
            distance = (dx * dx + dy * dy) ** 0.5
            if abs(distance - radius) < 1.0:
                rows[row][col] = "O"
            slash_col = int(center_x + (center_y - row) * (width / max(1, height)) * 0.9)
            if abs(col - slash_col) <= 1:
                rows[row][col] = "/"

    box_left = max(1, int(width * 0.28))
    box_right = max(box_left + 3, int(width * 0.40))
    box_top = max(1, int(height * 0.38))
    box_bottom = min(height - 2, int(height * 0.62))
    cone_tip = min(width - 2, int(width * 0.66))
    mid = (box_top + box_bottom) // 2
    for row in range(box_top, box_bottom + 1):
        for col in range(box_left, box_right + 1):
            rows[row][col] = "#"
        spread = abs(row - mid)
        for col in range(box_right + 1, max(box_right + 2, cone_tip - spread * 2)):
            if 0 <= col < width:
                rows[row][col] = "#"

    return tuple("".join(row).rstrip() for row in rows)


def research_lines(
    artist: str,
    results: tuple[GenreResult, ...],
    selected_index: int,
    artist_scroll: int,
    focus_artists: bool,
    *,
    loading: bool = False,
    error: str = "",
) -> list[str]:
    lines = [
        f"[ Every Noise Research: {artist} ]",
        "",
    ]
    if loading:
        return [*lines, "Searching Every Noise and cached Spotify metadata..."]
    if error:
        return [*lines, f"Research failed: {error}", "", "R or Esc hides this pane."]
    if not results:
        return [*lines, "No genre matches found.", "", "R or Esc hides this pane."]

    selected_index = min(max(0, selected_index), len(results) - 1)
    selected = results[selected_index]
    genre_header = "Genres by match" + (" [active]" if not focus_artists else "")
    artist_header = "Artists in selected genre" + (" [active]" if focus_artists else "")
    lines.append(f"{genre_header:<42} {artist_header}")
    lines.append(f"{'-' * 40} {'-' * 43}")

    artists = selected.artists
    max_artist_scroll = max(0, len(artists) - 20)
    artist_scroll = min(max(0, artist_scroll), max_artist_scroll)
    visible_artists = artists[artist_scroll : artist_scroll + 20]
    row_count = max(10, min(20, max(len(results), len(visible_artists))))
    for index in range(row_count):
        if index < len(results):
            result = results[index]
            pointer = ">" if index == selected_index and not focus_artists else " "
            rank = f"#{result.rank}" if result.rank is not None else "--"
            genre = ellipsize(result.genre, 22)
            match = min(999, int(result.score))
            genre_line = f"{pointer} {genre:<22} {match:>3} {rank:<5}"
        else:
            genre_line = ""

        if index < len(visible_artists):
            artist_pointer = ">" if focus_artists and index == 0 else " "
            artist_line = f"{artist_pointer} {ellipsize(visible_artists[index], 39)}"
        else:
            artist_line = ""
        lines.append(f"{genre_line:<42} {artist_line}")

    lines.extend(
        [
            "",
            f"Selected: {selected.genre} via {selected.matched_artist}",
            "Up/Down moves through genres or artists. Enter switches column. R/Esc hides this pane.",
        ]
    )
    return lines


def volume_text(volumes: tuple[tuple[str, int], ...], track: TrackInfo) -> str:
    if volumes:
        if len(volumes) == 1:
            return f"{volumes[0][1]}%"
        return ", ".join(f"{speaker} {volume}%" for speaker, volume in volumes)
    if track.volume is not None:
        return f"{track.volume}%"
    return "loading..."


def speaker_row_label(entry: SpeakerEntry, width: int) -> str:
    if entry.is_group:
        names = list(entry.members)
        if len(names) <= 2:
            label = " + ".join(names)
        else:
            label = f"{names[0]} + {names[1]} + {len(names) - 2} more"
        return ellipsize(label, width)
    return ellipsize(entry.label.strip(), width)


def speaker_state_indicator(entry: SpeakerEntry, entries: list[SpeakerEntry], track_by_speaker: dict[str, TrackInfo]) -> str:
    if not entry.is_group and is_group_member(entry, entries):
        return ""
    track = shared_track_for_group(entry, track_by_speaker) if entry.is_group else track_by_speaker.get(entry.speaker or "")
    return f" ({playback_state_symbol(track)})"


def playback_state_symbol(track: TrackInfo | None) -> str:
    if track is None or track.error:
        return "..."
    state = (track.playback_state or "").casefold()
    if state in {"playing", "play"}:
        return ">"
    if state in {"paused_playback", "paused", "pause"}:
        return "||"
    if state in {"stopped", "stop"}:
        return "[]"
    if state:
        return "?"
    return "..."


def ellipsize(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3].rstrip() + "..."


def elapsed_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}" if minutes else f"{secs}s"
