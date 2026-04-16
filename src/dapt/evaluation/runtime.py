"""XBOW-oriented evaluation helpers and benchmark runner."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from dapt.executor import ArtifactStoreLayout, Executor, build_pentest_registry
from dapt.perceptor import Perceptor, PerceptorArtifactStore
from dapt.planner import BootstrapPolicy, Planner, PlannerArtifactStore

from .models import (
    BenchmarkMetadata,
    BenchmarkRunResult,
    BenchmarkSelection,
    BenchmarkSpec,
    BenchmarkTargetConfig,
    CampaignRunResult,
    EvaluationSummary,
    LifecycleCommandResult,
)
from .storage import EvaluationArtifactStore


class CommandRunner(Protocol):
    """Execution boundary for benchmark lifecycle commands."""

    def __call__(self, *, name: str, command: tuple[str, ...], cwd: Path) -> LifecycleCommandResult:
        """Run one benchmark lifecycle command."""


class CampaignRunner(Protocol):
    """Execution boundary for one DAPT benchmark campaign."""

    def __call__(
        self,
        *,
        repo_root: Path,
        benchmark: BenchmarkSpec,
        session_id: str,
        max_turns: int,
        hypothesis_llm_config: dict[str, Any] | None,
    ) -> CampaignRunResult:
        """Run DAPT against one benchmark."""


class LocalConversationLLM:
    """Deterministic local summarizer for evaluation runs without network access."""

    def send_message(self, message: str, conversation_id: str) -> str:
        if 'Please reply "yes"' in message:
            return "yes"
        chunk = message.splitlines()[-1].strip()
        collapsed = " ".join(chunk.split())
        return collapsed[:400]


def parse_benchmark_selection(raw_value: str) -> BenchmarkSelection:
    """Parse one/all/list benchmark selector input."""

    stripped = raw_value.strip()
    lowered = stripped.lower()
    if lowered == "all":
        return BenchmarkSelection(raw_value=stripped, mode="all")
    parts = [part.strip() for part in stripped.split(",") if part.strip()]
    if not parts:
        raise ValueError("Benchmark selection must be 'all', one id, or a comma-separated list of ids.")
    unique = _sorted_unique_ids(parts)
    if len(unique) == 1:
        return BenchmarkSelection(raw_value=stripped, mode="one", benchmark_ids=unique)
    return BenchmarkSelection(raw_value=stripped, mode="many", benchmark_ids=unique)


def discover_benchmarks(benchmark_root: Path) -> tuple[BenchmarkSpec, ...]:
    """Discover and validate all benchmarks beneath the selected root."""

    if not benchmark_root.exists():
        raise FileNotFoundError(f"Benchmark root does not exist: {benchmark_root}")
    if not benchmark_root.is_dir():
        raise NotADirectoryError(f"Benchmark root is not a directory: {benchmark_root}")
    specs: list[BenchmarkSpec] = []
    for child in sorted(benchmark_root.iterdir(), key=lambda path: _sort_key(path.name)):
        if not child.is_dir():
            continue
        specs.append(load_benchmark_spec(child))
    return tuple(specs)


def resolve_selected_benchmarks(
    specs: tuple[BenchmarkSpec, ...],
    selection: BenchmarkSelection,
) -> tuple[BenchmarkSpec, ...]:
    """Resolve the selected subset deterministically."""

    if selection.mode == "all":
        return specs
    selected: list[BenchmarkSpec] = []
    remaining = list(selection.benchmark_ids)
    for requested_id in selection.benchmark_ids:
        matched = next((spec for spec in specs if _benchmark_id_matches(spec.benchmark_id, requested_id)), None)
        if matched is None:
            raise ValueError(f"Unknown benchmark id: {requested_id}")
        selected.append(matched)
        remaining.remove(requested_id)
    return tuple(selected)


def load_benchmark_spec(benchmark_dir: Path) -> BenchmarkSpec:
    """Load one benchmark and its DAPT-specific target contract."""

    compose_file = benchmark_dir / "docker-compose.yml"
    metadata_file = benchmark_dir / "benchmark" / "benchmark-config.json"
    target_config_file = benchmark_dir / "benchmark" / "dapt-target.json"
    missing = [
        path.name if path.parent == benchmark_dir else path.relative_to(benchmark_dir).as_posix()
        for path in (compose_file, metadata_file, target_config_file)
        if not path.exists()
    ]
    if missing:
        raise ValueError(
            f"Benchmark {benchmark_dir.name!r} is missing required files: {', '.join(missing)}"
        )
    metadata_payload = json.loads(metadata_file.read_text(encoding="utf-8"))
    target_payload = json.loads(target_config_file.read_text(encoding="utf-8"))
    metadata = BenchmarkMetadata(
        name=str(metadata_payload["name"]),
        description=str(metadata_payload["description"]),
        level=int(metadata_payload["level"]),
        win_condition=str(metadata_payload["win_condition"]),
        tags=tuple(str(item) for item in metadata_payload.get("tags", [])),
        files=tuple(str(item) for item in metadata_payload.get("files", [])),
        canaries=tuple(str(item) for item in metadata_payload.get("canaries", [])),
    )
    if metadata.win_condition != "flag":
        raise ValueError(f"Benchmark {benchmark_dir.name!r} is unsupported: win_condition must be 'flag'.")
    target = BenchmarkTargetConfig(
        target_url=str(target_payload["target_url"]),
        target_host=None if target_payload.get("target_host") in (None, "") else str(target_payload["target_host"]),
        initial_context=dict(target_payload.get("initial_context", {})),
        success_conditions=tuple(str(item) for item in target_payload.get("success_conditions", [])),
        objective_summary=None
        if target_payload.get("objective_summary") in (None, "")
        else str(target_payload["objective_summary"]),
    )
    return BenchmarkSpec(
        benchmark_id=benchmark_dir.name,
        benchmark_dir=benchmark_dir,
        compose_file=compose_file,
        metadata_file=metadata_file,
        target_config_file=target_config_file,
        metadata=metadata,
        target=target,
        build_command=("make", "build"),
        up_command=("docker", "compose", "up", "-d", "--wait"),
        down_command=("docker", "compose", "down", "--remove-orphans"),
    )


def run_lifecycle_command(*, name: str, command: tuple[str, ...], cwd: Path) -> LifecycleCommandResult:
    """Default subprocess-backed benchmark lifecycle execution."""

    completed = subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return LifecycleCommandResult(
        name=name,
        command=command,
        cwd=str(cwd),
        status="succeeded" if completed.returncode == 0 else "failed",
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_local_campaign(
    *,
    repo_root: Path,
    benchmark: BenchmarkSpec,
    session_id: str,
    max_turns: int,
    hypothesis_llm_config: dict[str, Any] | None,
) -> CampaignRunResult:
    """Run a benchmark through the existing DAPT planner stack."""

    registry = build_pentest_registry()
    executor = Executor(
        registry=registry,
        artifact_store=ArtifactStoreLayout(repo_root=repo_root),
    )
    perceptor = Perceptor(
        llm=LocalConversationLLM(),
        artifact_store=PerceptorArtifactStore(repo_root=repo_root),
    )
    planner = Planner(
        repo_root=repo_root,
        registry=registry,
        executor=executor,
        perceptor=perceptor,
        artifact_store=PlannerArtifactStore(repo_root=repo_root),
        bootstrap_policy=BootstrapPolicy(repo_root=repo_root),
        hypothesis_llm_config=hypothesis_llm_config,
        max_turns=max_turns,
    )
    session = planner.start_session(
        session_id=session_id,
        target_url=benchmark.target.target_url,
        target_host=benchmark.target.target_host,
        initial_context=dict(benchmark.target.initial_context),
        success_conditions=benchmark.target.success_conditions,
        campaign_mode="ctf",
        objective_summary=benchmark.target.objective_summary,
    )
    completed = planner.run(session)
    planner_session_dir = PlannerArtifactStore(repo_root=repo_root).session_dir(
        completed.session_id,
        completed.target_name,
    )
    return CampaignRunResult(
        session_id=completed.session_id,
        target_name=completed.target_name,
        completed=completed.completed,
        termination_reason=completed.termination_reason,
        objective_met=completed.termination_reason == "objective-met",
        turn_count=len(completed.turns),
        artifact_paths=(planner_session_dir.relative_to(repo_root).as_posix(),),
    )


def run_benchmark(
    *,
    repo_root: Path,
    benchmark: BenchmarkSpec,
    run_id: str,
    session_prefix: str,
    command_runner: CommandRunner | None = None,
    campaign_runner: CampaignRunner | None = None,
    build: bool = True,
    bring_up: bool = True,
    tear_down: bool = True,
    max_turns: int = 10,
    hypothesis_llm_config: dict[str, Any] | None = None,
    artifact_store: EvaluationArtifactStore | None = None,
) -> BenchmarkRunResult:
    """Run one benchmark including optional lifecycle management."""

    command_runner = command_runner or run_lifecycle_command
    campaign_runner = campaign_runner or run_local_campaign
    artifact_store = artifact_store or EvaluationArtifactStore(repo_root=repo_root)
    lifecycle: list[LifecycleCommandResult] = []
    session_id = f"{session_prefix}-{_normalize_benchmark_identifier(benchmark.benchmark_id)}"
    notes: list[str] = []
    campaign: CampaignRunResult | None = None
    run_result: BenchmarkRunResult | None = None
    try:
        if build:
            result = command_runner(name="build", command=benchmark.build_command, cwd=benchmark.benchmark_dir)
            lifecycle.append(result)
            if result.status == "failed":
                notes.append("Build command failed.")
                run_result = BenchmarkRunResult(
                    run_id=run_id,
                    benchmark_id=benchmark.benchmark_id,
                    benchmark_name=benchmark.metadata.name,
                    benchmark_dir=str(benchmark.benchmark_dir),
                    target_url=benchmark.target.target_url,
                    status="failed",
                    objective_met=False,
                )
        else:
            lifecycle.append(
                LifecycleCommandResult(
                    name="build",
                    command=benchmark.build_command,
                    cwd=str(benchmark.benchmark_dir),
                    status="skipped",
                )
            )
        if bring_up:
            result = command_runner(name="up", command=benchmark.up_command, cwd=benchmark.benchmark_dir)
            lifecycle.append(result)
            if result.status == "failed":
                notes.append("Environment startup command failed.")
                run_result = BenchmarkRunResult(
                    run_id=run_id,
                    benchmark_id=benchmark.benchmark_id,
                    benchmark_name=benchmark.metadata.name,
                    benchmark_dir=str(benchmark.benchmark_dir),
                    target_url=benchmark.target.target_url,
                    status="failed",
                    objective_met=False,
                )
        else:
            lifecycle.append(
                LifecycleCommandResult(
                    name="up",
                    command=benchmark.up_command,
                    cwd=str(benchmark.benchmark_dir),
                    status="skipped",
                )
            )
        if run_result is None:
            campaign = campaign_runner(
                repo_root=repo_root,
                benchmark=benchmark,
                session_id=session_id,
                max_turns=max_turns,
                hypothesis_llm_config=hypothesis_llm_config,
            )
            run_result = BenchmarkRunResult(
                run_id=run_id,
                benchmark_id=benchmark.benchmark_id,
                benchmark_name=benchmark.metadata.name,
                benchmark_dir=str(benchmark.benchmark_dir),
                target_url=benchmark.target.target_url,
                status="succeeded" if campaign.objective_met else "failed",
                objective_met=campaign.objective_met,
                termination_reason=campaign.termination_reason,
                session_id=campaign.session_id,
                campaign=campaign,
            )
    except Exception as exc:
        notes.append(str(exc))
        run_result = BenchmarkRunResult(
            run_id=run_id,
            benchmark_id=benchmark.benchmark_id,
            benchmark_name=benchmark.metadata.name,
            benchmark_dir=str(benchmark.benchmark_dir),
            target_url=benchmark.target.target_url,
            status="failed",
            objective_met=False,
        )
    finally:
        if tear_down:
            teardown_result = command_runner(name="down", command=benchmark.down_command, cwd=benchmark.benchmark_dir)
            lifecycle.append(teardown_result)
        else:
            lifecycle.append(
                LifecycleCommandResult(
                    name="down",
                    command=benchmark.down_command,
                    cwd=str(benchmark.benchmark_dir),
                    status="skipped",
                )
            )
    assert run_result is not None
    finalized = replace(run_result, lifecycle_results=tuple(lifecycle), notes=tuple(notes))
    artifact_store.persist_benchmark_result(finalized)
    return finalized


def run_evaluation(
    *,
    repo_root: Path,
    benchmark_root: Path,
    selection: BenchmarkSelection,
    run_id: str | None = None,
    command_runner: CommandRunner | None = None,
    campaign_runner: CampaignRunner | None = None,
    build: bool = True,
    bring_up: bool = True,
    tear_down: bool = True,
    max_turns: int = 10,
    hypothesis_llm_config: dict[str, Any] | None = None,
) -> EvaluationSummary:
    """Run the selected benchmark subset and persist the evaluation summary."""

    resolved_run_id = run_id or datetime.now(UTC).strftime("eval-%Y%m%d-%H%M%S")
    specs = discover_benchmarks(benchmark_root)
    selected_specs = resolve_selected_benchmarks(specs, selection)
    artifact_store = EvaluationArtifactStore(repo_root=repo_root)
    results = tuple(
        run_benchmark(
            repo_root=repo_root,
            benchmark=benchmark,
            run_id=resolved_run_id,
            session_prefix=f"{resolved_run_id}-bench",
            command_runner=command_runner,
            campaign_runner=campaign_runner,
            build=build,
            bring_up=bring_up,
            tear_down=tear_down,
            max_turns=max_turns,
            hypothesis_llm_config=hypothesis_llm_config,
            artifact_store=artifact_store,
        )
        for benchmark in selected_specs
    )
    summary = EvaluationSummary(
        run_id=resolved_run_id,
        benchmark_root=str(benchmark_root),
        selection=selection,
        results=results,
    )
    artifact_store.persist_summary(summary)
    return summary


def _sort_key(value: str) -> tuple[int, str]:
    if value.isdigit():
        return (int(value), value)
    return (10**9, value)


def _sorted_unique_ids(values: list[str]) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for value in values:
        key = _normalize_benchmark_identifier(value)
        seen.setdefault(key, value)
    ordered = sorted(seen.values(), key=_sort_key)
    return tuple(ordered)


def _normalize_benchmark_identifier(value: str) -> str:
    stripped = value.strip()
    if stripped.isdigit():
        return str(int(stripped))
    return stripped


def _benchmark_id_matches(actual: str, requested: str) -> bool:
    return _normalize_benchmark_identifier(actual) == _normalize_benchmark_identifier(requested)
