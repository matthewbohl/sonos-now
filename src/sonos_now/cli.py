from __future__ import annotations

import argparse

from .app import SonosNowApp
from .soco_backend import SonosService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sonos-now",
        description="Sonos Now: Textual terminal dashboard powered by direct SoCo calls.",
    )
    parser.add_argument(
        "speakers",
        nargs="*",
        help="Optional Sonos speaker names or IP addresses. If omitted, visible speakers are auto-discovered.",
    )
    parser.add_argument("--refresh", type=float, default=2.0, help="Polling interval in seconds")
    parser.add_argument("--discovery-timeout", type=float, default=3.0, help="Sonos discovery timeout in seconds")
    parser.add_argument("--view-only", action="store_true", help="Disable playback and volume controls")
    parser.add_argument(
        "--subnets",
        action="append",
        nargs="+",
        default=[],
        metavar="SUBNET",
        help="Discover Sonos speakers on one or more IPv4/CIDR subnets. May be repeated; commas accepted.",
    )
    return parser


def normalize_subnets(values: list[list[str]]) -> tuple[str, ...]:
    subnets: list[str] = []
    for group in values:
        for value in group:
            subnets.extend(part.strip() for part in value.split(",") if part.strip())
    return tuple(dict.fromkeys(subnets))


def main() -> None:
    args = build_parser().parse_args()
    service = SonosService(
        args.speakers,
        subnets=normalize_subnets(args.subnets),
        discovery_timeout=args.discovery_timeout,
    )
    app = SonosNowApp(service, refresh_interval=max(0.5, args.refresh), view_only=args.view_only)
    app.run()
