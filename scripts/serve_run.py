#!/usr/bin/env python3
"""CLI helper to launch and serve a run's workspace web app locally."""

from __future__ import annotations

import argparse
import sys

from verify_run import select_run_dir, serve_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start and serve a local server for a run's workspace.")
    parser.add_argument("--prompt", dest="prompt_id", help="Prompt id under runs/.")
    parser.add_argument("--run-id", help="Run id under runs/<prompt-id>/ or <prompt-id>/<run-id>.")
    parser.add_argument("--start-cmd", help="Custom command to start server.")
    parser.add_argument("--port", type=int, help="Port number for local server.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout in seconds for server startup.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        run_dir = select_run_dir(args.run_id, args.prompt_id)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    return serve_run(
        run_dir,
        start_cmd=args.start_cmd,
        port=args.port,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
