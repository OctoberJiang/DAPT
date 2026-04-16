"""Command-line entrypoint for XBOW benchmark evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .runtime import parse_benchmark_selection, run_evaluation


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""

    parser = argparse.ArgumentParser(description="Run DAPT against selected XBOW benchmarks.")
    parser.add_argument(
        "--benchmarks",
        required=True,
        help="Benchmark selector: 'all', one id like '12', or a comma-separated list like '1,2,5'.",
    )
    parser.add_argument(
        "--benchmark-root",
        default="XBOW-benchmarks/benchmarks",
        help="Path to the benchmark root directory. Defaults to XBOW-benchmarks/benchmarks under the repo root.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional stable evaluation run id used for artifact paths.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=10,
        help="Maximum planner turns per benchmark session.",
    )
    parser.add_argument("--skip-build", action="store_true", help="Skip the benchmark build command.")
    parser.add_argument("--skip-up", action="store_true", help="Skip the benchmark startup command.")
    parser.add_argument("--skip-down", action="store_true", help="Skip the benchmark teardown command.")
    parser.add_argument("--planner-provider", default=None, help="Optional planner LLM provider override.")
    parser.add_argument("--planner-model", default=None, help="Optional planner LLM model override.")
    parser.add_argument("--planner-api-base-url", default=None, help="Optional planner LLM base URL override.")
    parser.add_argument("--planner-api-key", default=None, help="Optional planner LLM API key override.")
    parser.add_argument(
        "--planner-api-key-env-var",
        default=None,
        help="Optional planner LLM API key environment variable name override.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the evaluation CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    selection = parse_benchmark_selection(args.benchmarks)
    hypothesis_llm_config = _planner_llm_config_from_args(args)
    summary = run_evaluation(
        repo_root=Path.cwd(),
        benchmark_root=Path(args.benchmark_root),
        selection=selection,
        run_id=args.run_id,
        build=not args.skip_build,
        bring_up=not args.skip_up,
        tear_down=not args.skip_down,
        max_turns=args.max_turns,
        hypothesis_llm_config=hypothesis_llm_config,
    )
    summary_path = Path.cwd() / "artifacts" / "evaluation" / _run_dir_name(summary.run_id) / "summary.json"
    print(summary_path.as_posix())
    return 0


def _planner_llm_config_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    values = {
        "provider": args.planner_provider,
        "model": args.planner_model,
        "api_base_url": args.planner_api_base_url,
        "api_key": args.planner_api_key,
        "api_key_env_var": args.planner_api_key_env_var,
    }
    filtered = {key: value for key, value in values.items() if value not in (None, "")}
    return filtered or None


def _run_dir_name(run_id: str) -> str:
    return "-".join(part for part in run_id.lower().replace("_", "-").split() if part)
