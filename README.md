# Sonos Now

Sonos Now is a command-line Textual dashboard for Sonos speakers. It shows what is playing across your Sonos system, renders color album art in the terminal, supports grouping and playback controls, and includes a surprisingly loud fullscreen ASCII visualizer.

It uses [SoCo](https://github.com/SoCo/SoCo) directly, so it does not shell out to `soco-cli`.

## Requirements

- Python 3.10 or newer
- `pip`
- A terminal with color support
- Sonos speakers reachable from the machine running the app

## Install

Clone and install:

```bash
git clone git@github.com:matthewbohl/sonos-now.git
cd sonos-now
python -m venv .venv
. .venv/bin/activate
python -m pip install .
sonos-now
```

On Windows PowerShell, activate the virtual environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

For development and tests:

```bash
python -m pip install '.[dev]'
pytest
```

## Usage

Auto-discover visible speakers:

```bash
sonos-now
```

Discover across specific subnets:

```bash
sonos-now --subnets 192.168.1.0/24 192.168.2.0/24
```

Open specific speakers by name or IP:

```bash
sonos-now Kitchen Office
sonos-now 192.168.1.25
```

Run without controls:

```bash
sonos-now --view-only
```

If discovery misses speakers on another subnet or VLAN, pass every network to scan:

```bash
sonos-now --subnets 192.168.1.0/24 192.168.20.0/24
```

## Keys

- `Up` / `Down`: move through speakers
- `Left` / `Right`: collapse or expand grouped speakers
- `1`-`9`: tag the highlighted speaker for grouping
- `g`: group speakers with the highlighted tag; the first tagged speaker becomes the source
- `G`: remove the highlighted speaker from its group; on a group row this ungroups and stops all members, while on a member row it only pauses and removes that speaker
- `p`: play/pause
- `f`: next track
- `b`: previous track
- `i`: volume up
- `k`: volume down
- `A`: fullscreen album art for the highlighted speaker or group
- `r`: refresh
- `R`: show/hide Every Noise artist and genre research in the Now Playing pane
- `v`: fullscreen visualizer
- `h`: show help
- `d`: show/hide the SoCo debug pane
- `o` / `l`: scroll the debug pane up/down when visible
- `q`: quit

Inside the visualizer, left/right cycles through dedicated Textual visualizer engines, and any other key returns.

## Grouped Speakers

Grouped speakers appear as a generated group row prefixed with `#`, with member speakers indented and prefixed by `>`. Groups are expanded by default on startup and after refreshes, and they stay expanded unless you explicitly collapse them with the left arrow. Track metadata is fetched once from the coordinator and shared across the group, while volume is read and displayed per speaker because Sonos volumes are independent inside a group.

Playback commands on a group row go to the coordinator. Volume commands on a group row are applied to all members. On an individual speaker row, volume changes affect only that speaker.

To create a group from the keyboard, highlight the speaker that should provide the audio and press a number from `1` to `9`. Highlight each additional speaker and press the same number. Press `g` to join those speakers into a Sonos group without changing playback state. The UI shows the pending group immediately while SoCo works; if the command fails, it reverts to the prior speaker list. When adding a speaker to an existing group, tagging any member of that group expands to the full group, keeps the existing coordinator as source, leaves current members alone, and only joins the new speaker. Highlight a grouped speaker and press `G` to remove and pause only that speaker. Highlight a group row and press `G` to ungroup and stop all members.

The bottom status line reports user commands currently being sent and how long they have been running. Routine refreshes are kept out of that status line. Speakers involved in an active command show a small spinner next to their name, so it is clear when the app is waiting on Sonos. Press `d` to show a live debug pane in the lower part of Now Playing with recent SoCo command history, grouped repeat counts, and a fixed running-command status line.

## Architecture

The project is intentionally split into small pieces:

- `soco_backend.py`: direct SoCo discovery, grouping, metadata, volume, and controls
- `app.py`: Textual UI, keyboard handling, background workers, and status panes
- `rendering.py`: pure Rich/Textual rendering helpers for track details, speaker rows, research output, and album art
- `grouping.py`: pure grouping and row-selection helpers shared by the UI tests
- `art_manager.py`: lazy album-art fetch, conversion, and full/compact/fullscreen caches
- `state.py`: small UI state dataclasses
- `visualizer.py`: fullscreen Textual visualizer engines and palettes
- `models.py`: plain dataclasses shared by UI and backend
- `ascii_art.py`: colorized album-art conversion
- `everynoise.py`: lazy similar-artist suggestions and artist genre research with local caching
- `timefmt.py` / `progress.py`: small formatting helpers

See [AGENTS.md](AGENTS.md) and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for handoff notes for future maintainers and AI coding agents.
