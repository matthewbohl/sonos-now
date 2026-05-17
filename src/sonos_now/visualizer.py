from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static

ROTATE_SECONDS = 60.0
PARTY_CHARS = " .,:;irsXA253hMHGS#9B&@"
MATRIX_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&*+=-"


@dataclass(frozen=True)
class VisualizerEngine:
    name: str
    chars: str
    palette: tuple[str, ...]
    background: str
    renderer: Callable[[int, int, float, str], str]


class VisualizerScreen(Screen[None]):
    def __init__(self) -> None:
        super().__init__()
        self.started_at = time.monotonic()
        self.style_offset = 0
        self.secret = False

    def compose(self) -> ComposeResult:
        yield Static(id="visualizer")

    def on_mount(self) -> None:
        self.set_interval(1 / 30, self._draw)
        self._draw()

    def action_previous_style(self) -> None:
        self.secret = False
        self.style_offset -= 1

    def action_next_style(self) -> None:
        self.secret = False
        self.style_offset += 1

    def on_key(self, event) -> None:
        char = getattr(event, "character", "") or ""
        if event.key == "left":
            event.stop()
            self.action_previous_style()
            return
        if event.key == "right":
            event.stop()
            self.action_next_style()
            return
        if char in {"S", "s"}:
            event.stop()
            self.secret = not self.secret
            return
        event.stop()
        self.dismiss()

    def _draw(self) -> None:
        elapsed = time.monotonic() - self.started_at
        width, height = self.size.width, self.size.height
        if width <= 0 or height <= 0:
            return
        body_height = max(1, height - 2)
        if self.secret:
            title = " SECRET FESTIVAL "
            body = _secret_festival(width, body_height, elapsed)
            text = _secret_text(title, body, " left/right style | any other key returns ", width, elapsed)
        else:
            index = (int(elapsed // ROTATE_SECONDS) + self.style_offset) % len(ENGINES)
            engine = ENGINES[index]
            title = f" {engine.name} "
            body = engine.renderer(width, body_height, elapsed % ROTATE_SECONDS, engine.chars)
            text = _engine_text(engine, title, body, " left/right style | any other key returns ", width, elapsed)
        self.query_one("#visualizer", Static).update(text)


def _engine_text(engine: VisualizerEngine, title: str, body: str, hint: str, width: int, elapsed: float) -> Text:
    text = Text(title.center(width), style=f"bold #ffffff on {engine.background}")
    text.append("\n")
    for row_index, line in enumerate(body.splitlines()):
        for col_index, char in enumerate(line):
            text.append(char, style=_engine_style(engine, char, row_index, col_index, elapsed))
        text.append("\n")
    text.append(hint.center(width), style=f"bold {engine.palette[1]} on {engine.background}")
    return text


def _engine_style(engine: VisualizerEngine, char: str, row: int, col: int, elapsed: float) -> str:
    pulse = int(elapsed * 12 + row * 1.7 + col * 0.37)
    palette = engine.palette
    if char == " ":
        shimmer = (row * 5 + col * 3 + int(elapsed * 9)) % 29 == 0
        fg = palette[0] if shimmer else engine.background
        return f"{fg} on {engine.background}"
    if char in {"@", "#", "%", "&", "B", "9"}:
        return f"bold {palette[-1]} on {palette[(pulse + 2) % len(palette)]}"
    if char in {"*", "+", "=", "o", "x", "X", "|", "/", "\\"}:
        return f"bold {palette[(pulse + 1) % len(palette)]} on {engine.background}"
    if char in MATRIX_CHARS:
        fg = "#ffffff" if (row + col + int(elapsed * 18)) % 13 == 0 else palette[(pulse + col) % len(palette)]
        return f"bold {fg} on {engine.background}"
    return f"{palette[pulse % len(palette)]} on {engine.background}"


def _dazzle_prism(width: int, height: int, elapsed: float, chars: str) -> str:
    lines: list[str] = []
    center_y = height / 2.0
    center_x = width / 2.0
    phase = elapsed * 2.2
    for row in range(height):
        line: list[str] = []
        for col in range(width):
            dx = (col - center_x) / max(1.0, center_x)
            dy = ((row - center_y) / max(1.0, center_y)) * 1.8
            radius = math.hypot(dx, dy)
            angle = math.atan2(dy, dx)
            folded = abs(((angle + phase * 0.14) % (math.pi / 2.0)) - math.pi / 4.0)
            facets = (
                math.sin(22.0 * radius - phase)
                + math.sin(16.0 * folded + phase * 1.7)
                + math.cos(11.0 * (dx - dy) + phase * 0.9)
                + math.sin((col ^ row) * 0.13 + phase)
            )
            line.append(_pick(chars, (facets + 4.0) / 8.0))
        lines.append("".join(line))
    return "\n".join(lines)


def _matrix(width: int, height: int, elapsed: float, chars: str) -> str:
    rows = [[" " for _ in range(width)] for _ in range(height)]
    for col in range(width):
        speed = 6 + (col * 7) % 13
        head = int(elapsed * speed + col * 5) % max(1, height)
        trail = 5 + col % 16
        for distance in range(trail):
            row = (head - distance) % max(1, height)
            rows[row][col] = chars[(row * 17 + col * 31 + int(elapsed * 14)) % len(chars)]
    return "\n".join("".join(row) for row in rows)


def _warp_tunnel(width: int, height: int, elapsed: float, chars: str) -> str:
    lines: list[str] = []
    center_y = height / 2.0
    center_x = width / 2.0
    for row in range(height):
        line: list[str] = []
        for col in range(width):
            dx = (col - center_x) / max(1.0, center_x)
            dy = (row - center_y) / max(1.0, center_y)
            radius = max(0.02, math.hypot(dx, dy))
            angle = math.atan2(dy, dx)
            tunnel = math.sin((1.0 / radius) * 3.2 + elapsed * 9.0 + math.sin(angle * 7.0))
            ribs = math.cos(angle * 16.0 - elapsed * 4.0)
            line.append(_pick(chars, (tunnel + ribs + 2.0) / 4.0))
        lines.append("".join(line))
    return "\n".join(lines)


def _spectrum(width: int, height: int, elapsed: float, chars: str) -> str:
    rows = [[" " for _ in range(width)] for _ in range(height)]
    for col in range(width):
        wave = (
            math.sin(elapsed * 3.2 + col * 0.19)
            + math.sin(elapsed * 6.1 + col * 0.07)
            + math.cos(elapsed * 2.2 - col * 0.13)
        )
        bar_height = max(1, int(((wave + 3.0) / 6.0) * height))
        for row in range(height):
            fill_from_bottom = height - 1 - row
            if fill_from_bottom < bar_height:
                level = 1.0 - (fill_from_bottom / max(1, height))
                rows[row][col] = "@" if level > 0.82 else "#" if level > 0.62 else "*" if level > 0.38 else "="
    return "\n".join("".join(row) for row in rows)


def _plasma(width: int, height: int, elapsed: float, chars: str) -> str:
    lines: list[str] = []
    for row in range(height):
        y = row / max(1, height - 1)
        line: list[str] = []
        for col in range(width):
            x = col / max(1, width - 1)
            value = (
                math.sin((x * 12.0) + elapsed * 2.7)
                + math.sin((y * 14.0) - elapsed * 3.1)
                + math.sin(((x + y) * 11.0) + elapsed * 1.8)
                + math.cos(math.hypot(x - 0.5, y - 0.5) * 34.0 - elapsed * 3.6)
            )
            line.append(_pick(chars, (value + 4.0) / 8.0))
        lines.append("".join(line))
    return "\n".join(lines)


def _starfield(width: int, height: int, elapsed: float, chars: str) -> str:
    rows = [[" " for _ in range(width)] for _ in range(height)]
    center_x, center_y = width / 2.0, height / 2.0
    for index in range(max(100, min(900, width * height // 5))):
        seed_x = ((index * 37) % 1000) / 1000.0 - 0.5
        seed_y = ((index * 91 + 17) % 1000) / 1000.0 - 0.5
        travel = (((index * 53) % 1000) / 1000.0 - elapsed * 0.22) % 1.0
        scale = 1.0 / max(0.06, travel)
        col = int(center_x + seed_x * center_x * scale)
        row = int(center_y + seed_y * center_y * scale)
        if 0 <= row < height and 0 <= col < width:
            rows[row][col] = "@" if travel < 0.14 else "#" if travel < 0.28 else "*" if travel < 0.45 else "."
    return "\n".join("".join(row) for row in rows)


def _acid_trip(width: int, height: int, elapsed: float, chars: str) -> str:
    lines: list[str] = []
    for row in range(height):
        y = row / max(1, height - 1)
        melt = math.sin(y * 9.0 + elapsed * 2.2) * 0.10 + math.sin(y * 31.0 - elapsed * 3.0) * 0.04
        line: list[str] = []
        for col in range(width):
            x = col / max(1, width - 1)
            warped_x = x + melt + math.sin((x + y) * 18.0 + elapsed * 2.6) * 0.03
            value = (
                math.sin((warped_x * 14.0) - elapsed * 4.0 + math.sin(y * 20.0))
                + math.cos((y * 32.0) + elapsed * 3.1 + math.sin(x * 10.0))
                + math.sin((warped_x - y) * 24.0 + elapsed * 1.3)
            )
            line.append(_pick(chars, (value + 3.0) / 6.0))
        lines.append("".join(line))
    return "\n".join(lines)


def _swirl(width: int, height: int, elapsed: float, chars: str) -> str:
    lines: list[str] = []
    center_y = height / 2.0
    center_x = width / 2.0
    for row in range(height):
        line: list[str] = []
        for col in range(width):
            dx = (col - center_x) / max(1.0, center_x)
            dy = (row - center_y) / max(1.0, center_y)
            radius = math.hypot(dx, dy)
            angle = math.atan2(dy, dx)
            value = math.sin(radius * 34.0 - angle * 7.0 - elapsed * 6.0)
            line.append(_pick(chars, (value + 1.0) / 2.0))
        lines.append("".join(line))
    return "\n".join(lines)


def _chonky_blobs(width: int, height: int, elapsed: float, chars: str) -> str:
    blobs = ((0.22, 0.28, 0.18), (0.72, 0.30, 0.22), (0.42, 0.68, 0.26), (0.82, 0.76, 0.16), (0.14, 0.78, 0.20), (0.58, 0.46, 0.18))
    lines: list[str] = []
    for row in range(height):
        y = row / max(1, height - 1)
        line: list[str] = []
        for col in range(width):
            x = col / max(1, width - 1)
            field = 0.0
            for index, (base_x, base_y, size) in enumerate(blobs):
                bx = base_x + math.sin(elapsed * (0.45 + index * 0.09) + index) * 0.14
                by = base_y + math.cos(elapsed * (0.36 + index * 0.07) + index * 1.7) * 0.12
                dx = (x - bx) * (width / max(1, height))
                dy = y - by
                field += (size * size) / max(0.001, dx * dx + dy * dy)
            line.append(" " if field < 0.45 else _pick(chars, min(1.0, field / 5.0)))
        lines.append("".join(line))
    return "\n".join(lines)


def _laser_lattice(width: int, height: int, elapsed: float, chars: str) -> str:
    rows = [[" " for _ in range(width)] for _ in range(height)]
    beams = max(4, width // 18)
    for beam in range(beams):
        origin = int((beam + 0.5) * width / beams + math.sin(elapsed * 1.4 + beam) * 6)
        for row in range(height):
            drift = int(math.sin(elapsed * 2.0 + row * 0.18 + beam) * row * 0.28)
            for col in (origin + drift, origin - drift):
                if 0 <= col < width:
                    rows[row][col] = "/" if drift >= 0 else "\\"
    for row in range(0, height, 4):
        phase = int(elapsed * 12 + row) % max(1, width)
        for col in range(width):
            if (col + phase) % 11 < 2:
                rows[row][col] = "="
    return "\n".join("".join(row) for row in rows)


def _neon_tides(width: int, height: int, elapsed: float, chars: str) -> str:
    lines: list[str] = []
    for row in range(height):
        y = row / max(1, height - 1)
        line: list[str] = []
        for col in range(width):
            x = col / max(1, width - 1)
            tide = (
                math.sin((x * 18.0) + elapsed * 2.0 + math.sin(y * 8.0))
                + math.sin((y * 25.0) + elapsed * 1.5)
                + math.cos((x - y) * 20.0 - elapsed * 2.7)
            )
            sparkle = 1.0 if (row * 17 + col * 31 + int(elapsed * 18)) % 97 == 0 else 0.0
            line.append(_pick(chars, (tide + 3.0 + sparkle) / 7.0))
        lines.append("".join(line))
    return "\n".join(lines)


ENGINES: tuple[VisualizerEngine, ...] = (
    VisualizerEngine("Dazzle Prism", " .-:=+*xX#%@&", ("#ff2bd6", "#00f5ff", "#fff200", "#ff7a00", "#ffffff"), "#080014", _dazzle_prism),
    VisualizerEngine("Matrix Rain", MATRIX_CHARS, ("#001a08", "#00ff66", "#72ff00", "#ffffff", "#b6ff00"), "#001006", _matrix),
    VisualizerEngine("Warp Tunnel", " .-:=+*#%@", ("#7df9ff", "#8a2be2", "#ff1493", "#fff700", "#ffffff"), "#050019", _warp_tunnel),
    VisualizerEngine("Spectrum Pop", " -=+*#%@", ("#00e5ff", "#00ff9d", "#faff00", "#ff2e63", "#ffffff"), "#001217", _spectrum),
    VisualizerEngine("Plasma Weave", PARTY_CHARS, ("#ff00aa", "#00ffee", "#ffe600", "#ff6600", "#ffffff"), "#120012", _plasma),
    VisualizerEngine("Starfield", " .*+xX#%@", ("#ffffff", "#8bd3ff", "#b388ff", "#ffdf6e", "#ff5fd7"), "#020617", _starfield),
    VisualizerEngine("Melty Acid Trip", "~-=+*#%@&", ("#ff355e", "#fdff00", "#00ff87", "#00b7ff", "#ffffff"), "#120400", _acid_trip),
    VisualizerEngine("Hypno-Swirl", " .oO@%#", ("#ff00ff", "#00ffff", "#ffff00", "#ff3366", "#ffffff"), "#090018", _swirl),
    VisualizerEngine("Chonky Blobs", "  .:=#@&", ("#ff6b00", "#ff00a8", "#34ffea", "#f8ff4a", "#ffffff"), "#120600", _chonky_blobs),
    VisualizerEngine("Laser Lattice", " .`'/-\\|+xX#%@", ("#ff004c", "#00f5ff", "#faff00", "#9d4edd", "#ffffff"), "#06000d", _laser_lattice),
    VisualizerEngine("Neon Tides", " .,:;~=+*#%@", ("#00ffd5", "#0077ff", "#ff00cc", "#ffee00", "#ffffff"), "#00131a", _neon_tides),
)


def _secret_festival(width: int, height: int, elapsed: float) -> str:
    rows = [[" " for _ in range(width)] for _ in range(height)]
    horizon = max(2, height // 4)
    stage_w = max(28, min(width - 4, width // 2))
    stage_left = max(0, width // 2 - stage_w // 2)
    stage = [
        "/" + "=" * (stage_w - 2) + "\\",
        "|" + " ULTRA  NIGHT  STAGE ".center(stage_w - 2, "=") + "|",
        "|" + ("[]" * ((stage_w - 2) // 2))[: stage_w - 2] + "|",
        "\\" + "_" * (stage_w - 2) + "/",
    ]
    _stamp(rows, horizon, stage_left, tuple(stage))
    for tower_x in (max(0, stage_left - 8), min(width - 8, stage_left + stage_w + 1)):
        tower = ("  /\\  ", " /##\\ ", "/####\\", "  ||  ", "  ||  ")
        _stamp(rows, max(0, horizon - 2), tower_x, tower)
    lasers = (width // 6, width // 3, width // 2, width * 2 // 3, width * 5 // 6)
    for source in lasers:
        for step in range(height):
            sway = math.sin(elapsed * 2.2 + source * 0.04 + step * 0.15)
            offset = int(step * (0.45 + sway * 0.14))
            for col in (source - offset, source + offset):
                if 0 <= col < width and 0 <= step < height:
                    rows[step][col] = "/" if col >= source else "\\"
    crowd_top = min(height - 1, horizon + len(stage) + 1)
    crowd_chars = ("o", "O", "@", "*")
    for row in range(crowd_top, height):
        density = (row - crowd_top + 1) / max(1, height - crowd_top)
        spacing = max(2, int(7 - density * 5))
        phase = int(math.sin(elapsed * 4.0 + row * 0.7) * 2)
        for col in range((row + phase) % spacing, width, spacing):
            bob = int(math.sin(elapsed * 7.0 + col * 0.21 + row) > 0.35)
            rows[row][col] = crowd_chars[(row + col + int(elapsed * 5)) % len(crowd_chars)]
            if bob and row > crowd_top and col + 1 < width:
                rows[row - 1][col + 1] = "\\"
            if bob and row > crowd_top and col - 1 >= 0:
                rows[row - 1][col - 1] = "/"
    for burst in range(10):
        cx = (burst * 23 + int(elapsed * 9) * (burst + 3)) % max(1, width)
        cy = 1 + (burst * 7) % max(1, max(1, horizon))
        radius = 1 + ((int(elapsed * 4) + burst) % 4)
        for angle_index in range(8):
            angle = angle_index * math.pi / 4.0 + elapsed
            col = int(cx + math.cos(angle) * radius)
            row = int(cy + math.sin(angle) * radius * 0.5)
            if 0 <= row < height and 0 <= col < width:
                rows[row][col] = "*"
    return "\n".join("".join(row) for row in rows)


def _secret_text(title: str, body: str, hint: str, width: int, elapsed: float) -> Text:
    palette = ("#ff2bd6", "#00f5ff", "#fff200", "#ff7a00", "#ffffff", "#00ff66")
    background = "#050005"
    text = Text(title.center(width), style=f"bold #ffffff on {background}")
    text.append("\n")
    for row_index, line in enumerate(body.splitlines()):
        for col_index, char in enumerate(line):
            pulse = int(elapsed * 10 + row_index * 2 + col_index * 0.4)
            if char == " ":
                text.append(char, style=f"{background} on {background}")
            elif char in {"\\", "/", "*"}:
                text.append(char, style=f"bold {palette[(pulse + 2) % len(palette)]} on {background}")
            elif char in {"o", "O", "@", "#"}:
                text.append(char, style=f"bold {palette[pulse % len(palette)]} on {background}")
            else:
                text.append(char, style=f"bold {palette[(pulse + col_index) % len(palette)]} on {background}")
        text.append("\n")
    text.append(hint.center(width), style=f"bold #00f5ff on {background}")
    return text


def _stamp(rows: list[list[str]], top: int, left: int, sprite: tuple[str, ...]) -> None:
    for row_offset, line in enumerate(sprite):
        row = top + row_offset
        if row < 0 or row >= len(rows):
            continue
        for col_offset, char in enumerate(line):
            col = left + col_offset
            if char != " " and 0 <= col < len(rows[row]):
                rows[row][col] = char


def _pick(chars: str, value: float) -> str:
    normalized = max(0.0, min(1.0, value))
    return chars[min(len(chars) - 1, int(normalized * (len(chars) - 1)))]
