from __future__ import annotations

from sonos_now.visualizer import ENGINES, _secret_festival


def test_visualizer_engines_and_secret_scene_render_nonblank_frames():
    assert len(ENGINES) >= 10
    for engine in ENGINES:
        frame = engine.renderer(48, 14, 3.5, engine.chars)
        assert len(frame.splitlines()) == 14
        assert any(char != " " for char in frame)
    secret = _secret_festival(80, 24, 2.0)
    assert "ULTRA" in secret
    assert any(char in secret for char in ("o", "O", "@"))
