from __future__ import annotations


def progress_bar(progress: float | None, width: int = 30) -> str:
    width = max(4, width)
    if progress is None:
        return "[" + "?" * (width - 2) + "]"
    progress = max(0.0, min(1.0, progress))
    inner_width = width - 2
    filled = round(inner_width * progress)
    return "[" + "#" * filled + "-" * (inner_width - filled) + "]"
