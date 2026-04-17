"""XBOW-oriented evaluation helpers and benchmark runner."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from dapt.executor import ArtifactStoreLayout, Executor, build_pentest_registry
from dapt.perceptor import Perceptor, PerceptorArtifactStore
from dapt.planner import BootstrapPolicy, Planner, PlannerArtifactStore, PlannerBudgetLimits

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
        budget_limits: PlannerBudgetLimits | None,
    ) -> CampaignRunResult:
        """Run DAPT against one benchmark."""


class TargetResolver(Protocol):
    """Resolve a live target URL for a started benchmark."""

    def __call__(self, *, benchmark: BenchmarkSpec) -> BenchmarkTargetConfig:
        """Return a benchmark target config with a concrete target URL."""


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
    metadata_file = _resolve_metadata_file(benchmark_dir)
    target_config_file = benchmark_dir / "benchmark" / "dapt-target.json"
    missing = [
        path.name if path.parent == benchmark_dir else path.relative_to(benchmark_dir).as_posix()
        for path in (compose_file, metadata_file)
        if not path.exists()
    ]
    if missing:
        raise ValueError(
            f"Benchmark {benchmark_dir.name!r} is missing required files: {', '.join(missing)}"
        )
    metadata_payload = json.loads(metadata_file.read_text(encoding="utf-8"))
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
    if target_config_file.exists():
        target_payload = json.loads(target_config_file.read_text(encoding="utf-8"))
        target = BenchmarkTargetConfig(
            target_url=str(target_payload["target_url"]),
            target_host=None if target_payload.get("target_host") in (None, "") else str(target_payload["target_host"]),
            initial_context=dict(target_payload.get("initial_context", {})),
            success_conditions=tuple(str(item) for item in target_payload.get("success_conditions", [])),
            objective_summary=None
            if target_payload.get("objective_summary") in (None, "")
            else str(target_payload["objective_summary"]),
        )
    else:
        target = _infer_target_config_from_compose(
            compose_file=compose_file,
            objective_summary=f"Capture the flag for {metadata.name}.",
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
    budget_limits: PlannerBudgetLimits | None = None,
) -> CampaignRunResult:
    """Run a benchmark through the existing DAPT planner stack."""

    registry = build_pentest_registry(repo_root=repo_root)
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
        budget_limits=budget_limits,
        max_turns=max_turns,
    )
    session = planner.start_session(
        session_id=session_id,
        target_url=benchmark.target.target_url or "",
        target_host=benchmark.target.target_host,
        initial_context=dict(benchmark.target.initial_context),
        success_conditions=benchmark.target.success_conditions,
        campaign_mode="ctf",
        objective_summary=benchmark.target.objective_summary,
        benchmark_metadata=benchmark.metadata.as_planner_context(benchmark_id=benchmark.benchmark_id),
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
    budget_limits: PlannerBudgetLimits | None = None,
    target_resolver: TargetResolver | None = None,
    artifact_store: EvaluationArtifactStore | None = None,
) -> BenchmarkRunResult:
    """Run one benchmark including optional lifecycle management."""

    command_runner = command_runner or run_lifecycle_command
    campaign_runner = campaign_runner or run_local_campaign
    target_resolver = target_resolver or resolve_benchmark_target
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
            resolved_target = target_resolver(benchmark=benchmark)
            campaign = campaign_runner(
                repo_root=repo_root,
                benchmark=replace(benchmark, target=resolved_target),
                session_id=session_id,
                max_turns=max_turns,
                hypothesis_llm_config=hypothesis_llm_config,
                budget_limits=budget_limits,
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
    budget_limits: PlannerBudgetLimits | None = None,
    target_resolver: TargetResolver | None = None,
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
            budget_limits=budget_limits,
            target_resolver=target_resolver,
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
    match = re.fullmatch(r"XBEN-(?P<number>\d+)-\d+", stripped, flags=re.IGNORECASE)
    if match is not None:
        return str(int(match.group("number")))
    return stripped


def _benchmark_id_matches(actual: str, requested: str) -> bool:
    return _normalize_benchmark_identifier(actual) == _normalize_benchmark_identifier(requested)


def _resolve_metadata_file(benchmark_dir: Path) -> Path:
    legacy = benchmark_dir / "benchmark" / "benchmark-config.json"
    if legacy.exists():
        return legacy
    return benchmark_dir / "benchmark.json"


def _infer_target_config_from_compose(
    *,
    compose_file: Path,
    objective_summary: str | None,
) -> BenchmarkTargetConfig:
    service_name, container_port, scheme, path = _first_exposed_http_service(compose_file.read_text(encoding="utf-8"))
    return BenchmarkTargetConfig(
        target_url=None,
        target_host="127.0.0.1",
        initial_context={},
        success_conditions=(),
        objective_summary=objective_summary,
        target_service=service_name,
        target_container_port=container_port,
        target_scheme=scheme,
        target_path=path,
    )


def resolve_benchmark_target(*, benchmark: BenchmarkSpec) -> BenchmarkTargetConfig:
    if benchmark.target.target_url:
        return benchmark.target
    service_name = benchmark.target.target_service
    container_port = benchmark.target.target_container_port
    if not service_name or container_port is None:
        raise ValueError(
            f"Benchmark {benchmark.benchmark_id!r} does not expose a repo-visible target URL or port mapping."
        )
    completed = subprocess.run(
        ["docker", "compose", "port", service_name, str(container_port)],
        cwd=benchmark.benchmark_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"Failed to resolve target for benchmark {benchmark.benchmark_id!r}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    host_port = _parse_docker_compose_port(completed.stdout)
    scheme = benchmark.target.target_scheme or "http"
    path = benchmark.target.target_path or "/"
    target_url = f"{scheme}://127.0.0.1:{host_port}{path}"
    return replace(
        benchmark.target,
        target_url=target_url,
        target_host="127.0.0.1",
        initial_context={
            **benchmark.target.initial_context,
            "target_url": target_url,
        },
    )


def _parse_docker_compose_port(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        raise ValueError("docker compose port returned no output")
    match = re.search(r":(?P<port>\d+)$", stripped)
    if not match:
        raise ValueError(f"Unable to parse docker compose port output: {stripped!r}")
    return int(match.group("port"))


def _first_exposed_http_service(compose_text: str) -> tuple[str, int, str, str]:
    lines = compose_text.splitlines()
    in_services = False
    current_service: str | None = None
    current_indent: int | None = None
    in_ports = False
    ports_indent: int | None = None
    service_ports: list[tuple[str, int]] = []
    service_health_urls: dict[str, str] = {}

    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if stripped == "services:" and indent == 0:
            in_services = True
            continue
        if not in_services:
            continue
        if indent == 2 and stripped.endswith(":"):
            current_service = stripped[:-1]
            current_indent = indent
            in_ports = False
            ports_indent = None
            continue
        if current_service is None or current_indent is None:
            continue
        if indent <= current_indent:
            current_service = None
            current_indent = None
            in_ports = False
            ports_indent = None
            continue
        if stripped == "ports:":
            in_ports = True
            ports_indent = indent
            continue
        if in_ports and ports_indent is not None:
            if indent <= ports_indent:
                in_ports = False
            elif stripped.startswith("-"):
                parsed_port = _parse_container_port_entry(stripped[1:].strip().strip("\"'"))
                if parsed_port is not None:
                    service_ports.append((current_service, parsed_port))
                continue
        if "http://localhost:" in stripped or "https://localhost:" in stripped:
            match = re.search(r"(https?://localhost:\d+[^\s\"']*)", stripped)
            if match:
                service_health_urls[current_service] = match.group(1)

    if not service_ports:
        raise ValueError("Unable to infer an exposed benchmark service from docker-compose.yml")
    service_name, container_port = service_ports[0]
    health_url = service_health_urls.get(service_name, "")
    scheme = "https" if health_url.startswith("https://") or container_port == 443 else "http"
    path_match = re.search(r"https?://localhost:\d+(?P<path>/[^\s\"']*)", health_url)
    path = path_match.group("path") if path_match else "/"
    return service_name, container_port, scheme, path


def _parse_container_port_entry(value: str) -> int | None:
    if not value:
        return None
    match = re.search(r"(?P<port>\d+)(?:/(tcp|udp))?$", value)
    if match is None:
        return None
    return int(match.group("port"))
