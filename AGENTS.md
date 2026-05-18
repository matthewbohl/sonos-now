# Agent Handoff Notes

This project was developed as a terminal-native Sonos dashboard and control surface. The current package is the cleaned-up publishable version of the working prototype formerly called `sonos-now-2`.

## Project Shape

- Package: `sonos_now`
- Console command: `sonos-now`
- UI framework: Textual
- Sonos backend: direct SoCo calls, no `soco-cli`
- Tests: lightweight pytest-compatible assertions in `tests/`

## Important Behavioral Contracts

- Refresh polling must not block or swallow keyboard input. Refresh uses its own `_refreshing` state and must not reuse command busy state.
- User commands should show immediate status and speaker spinners.
- Grouping, member removal, and ungrouping optimistically update the UI, then revert only on command failure.
- Existing Sonos groups are expanded by default unless explicitly collapsed by the user.
- Adding a speaker to an existing group should keep the existing coordinator and avoid re-joining speakers already in that group.
- UPnP 701 from unjoin operations is treated as a non-fatal transition/no-op case when it appears during safe unjoin handling.
- `--view-only` must disable playback, track navigation, and volume mutation.
- The hidden visualizer scene is intentionally not listed in the help modal.

## Files To Start With

- `src/sonos_now/app.py`: Textual layout, key handling, optimistic UI, debug and research panes.
- `src/sonos_now/rendering.py`: pure display helpers for rows, details, album-art text, and research text.
- `src/sonos_now/grouping.py`: pure grouping helpers for labels, selected entries, shared tracks, and volumes.
- `src/sonos_now/art_manager.py`: lazy album-art fetch/conversion caches for full, compact, and fullscreen art.
- `src/sonos_now/soco_backend.py`: SoCo discovery, metadata, grouping, controls, safe unjoin logic.
- `src/sonos_now/visualizer.py`: independent visualizer engines and hidden festival scene.
- `src/sonos_now/everynoise.py`: lazy similar-artist cache with per-entry cache timestamps.
- `tests/`: fast regression coverage without real Sonos hardware.

## Verification

Use:

```bash
python -m pip install '.[dev]'
pytest
```

For a dependency-light sanity check:

```bash
python -m compileall src tests
PYTHONPATH=src python -c "import tests.test_backend as t; [getattr(t, name)() for name in dir(t) if name.startswith('test_')]; print('plain assertion tests passed')"
```

## Design Taste

Keep the app terminal-native, dense, and keyboard-driven. Prefer useful status and non-blocking background work over modal flows. The visualizer is allowed to be playful and colorful; the control surface should remain readable and predictable.
