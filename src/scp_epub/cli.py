from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SCP EPUB pipeline")
    parser.add_argument("--config", default="config/series-1.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("index", "fetch", "clean", "build"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--volume", default="001-099")
        subparser.add_argument("--refresh", action="store_true")
        subparser.add_argument("--missing-only", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    if argv == ["--help"]:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    from .pipeline import run_command

    run_command(args)
    return 0
