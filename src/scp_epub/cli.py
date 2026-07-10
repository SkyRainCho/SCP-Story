from __future__ import annotations

import argparse
from collections.abc import Sequence


DEFAULT_CONFIG = "config/series-1.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SCP EPUB pipeline")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    command_parent = argparse.ArgumentParser(add_help=False)
    command_parent.add_argument("--config", default=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("index", "manifest", "fetch", "clean", "build"):
        subparser = subparsers.add_parser(command, parents=[command_parent])
        subparser.add_argument("--volume", default="001-099")
        subparser.add_argument("--refresh", action="store_true")
        subparser.add_argument("--missing-only", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    normalized_argv = None if argv is None else tuple(argv)
    if normalized_argv in (("-h",), ("--help",)):
        parser.print_help()
        return 0
    args = parser.parse_args(normalized_argv)
    from .pipeline import run_command

    run_command(args)
    return 0
