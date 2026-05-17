from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import requests
from PIL import Image

RAMP = " .:-=+*#%@"
PALETTE = (
    (0, 0, 0),
    (205, 49, 49),
    (13, 188, 121),
    (229, 229, 16),
    (36, 114, 200),
    (188, 63, 188),
    (17, 168, 205),
    (229, 229, 229),
)


@dataclass(frozen=True)
class AlbumArt:
    signature: str = ""
    lines: tuple[str, ...] = ()
    colors: tuple[tuple[int, ...], ...] = ()
    error: str | None = None

    @property
    def is_available(self) -> bool:
        return self.error is None and bool(self.lines)


def fetch_image_bytes(url: str, timeout: float = 5.0) -> bytes:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def image_bytes_to_colored_ascii(
    image_bytes: bytes,
    width: int = 48,
    height: int = 24,
) -> tuple[tuple[str, ...], tuple[tuple[int, ...], ...]]:
    image = Image.open(BytesIO(image_bytes))
    return image_to_colored_ascii(image, width=width, height=height)


def image_to_colored_ascii(
    image: Image.Image,
    width: int = 48,
    height: int = 24,
) -> tuple[tuple[str, ...], tuple[tuple[int, ...], ...]]:
    width = max(8, width)
    height = max(4, height)
    rgb_image = image.convert("RGB").resize((width, height))
    gray_image = rgb_image.convert("L")

    lines: list[str] = []
    color_rows: list[tuple[int, ...]] = []
    for y in range(height):
        chars: list[str] = []
        colors: list[int] = []
        for x in range(width):
            value = gray_image.getpixel((x, y))
            chars.append(RAMP[value * (len(RAMP) - 1) // 255])
            colors.append(_nearest_palette_index(rgb_image.getpixel((x, y))))
        lines.append("".join(chars))
        color_rows.append(tuple(colors))

    return tuple(lines), tuple(color_rows)


def _nearest_palette_index(rgb: tuple[int, int, int]) -> int:
    red, green, blue = rgb
    distances = [
        ((red - pr) ** 2 + (green - pg) ** 2 + (blue - pb) ** 2, index)
        for index, (pr, pg, pb) in enumerate(PALETTE)
    ]
    return min(distances)[1]
