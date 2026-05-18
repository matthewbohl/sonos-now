# Development Notes

## Local Setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install '.[dev]'
pytest
```

Run the app from a checkout:

```bash
sonos-now
```

Or without installing the console script:

```bash
PYTHONPATH=src python -m sonos_now
```

## Discovery And Networking

SoCo discovery works best when the machine is on the same network as the speakers. For routed networks or multiple VLANs, use:

```bash
sonos-now --subnets 192.168.1.0/24 192.168.20.0/24
```

## Debugging

- Press `d` in the app to show the debug pane.
- The bottom app status bar shows active user commands.
- Routine refreshes are visible in the debug pane but intentionally do not take over the command status bar.

## Code Map

- `app.py` owns Textual composition, key handling, optimistic UI updates, and worker scheduling.
- `soco_backend.py` owns SoCo discovery, topology refresh, track polling, grouping, playback, and volume commands.
- `rendering.py`, `grouping.py`, and `art_manager.py` keep pure display logic, grouping helpers, and album-art caching out of the main app class.
- `everynoise.py` owns artist research and similar-artist caching. Cache entries use individual timestamps so one stale artist does not expire the whole file.

## Release Checklist

1. Run `python -m compileall src tests`.
2. Run `pytest`.
3. Install locally with `python -m pip install .`.
4. Launch `sonos-now` and smoke-test discovery, selection, album art, grouping, ungrouping, visualizer, and `--view-only`.
5. Tag releases from a clean git tree.
