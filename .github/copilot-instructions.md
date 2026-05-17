# Copilot / AI Agent Instructions

This is a Python Textual app. Preserve the existing terminal-first interaction model.

- Avoid blocking the Textual event loop with network or image work; use workers or `asyncio.to_thread`.
- Do not make refresh polling share command busy state.
- Keep Sonos mutations in `soco_backend.py` and UI state in `app.py`.
- Keep visualizer work in `visualizer.py`.
- For grouping changes, update optimistic UI behavior and backend tests together.
- For SoCo edge cases, add fake-device tests in `tests/test_backend.py` rather than relying on real Sonos hardware.
- Do not expose the secret visualizer key in the help modal.

