"""Command-line entrypoint for report generation."""

from __future__ import annotations

import argparse
from pathlib import Path

from .runtime import assemble_report, write_report


def build_parser() -> argparse.ArgumentParser:
    """Create the report CLI parser."""

    parser = argparse.ArgumentParser(description="Generate a structured report from a DAPT session directory.")
    parser.add_argument(
        "--session-dir",
        required=True,
        help="Planner session directory, absolute or relative to the repo root.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
        help="Rendered report format.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path. Defaults to artifacts/report/<session>/report.<ext>.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the report CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path.cwd()
    report = assemble_report(repo_root=repo_root, session_dir=Path(args.session_dir))
    rendered = write_report(
        repo_root=repo_root,
        report=report,
        report_format=args.format,
        output_path=None if args.output is None else Path(args.output),
    )
    print(rendered.output_path)
    return 0
