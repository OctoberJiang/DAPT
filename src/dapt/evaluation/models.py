"""Typed contracts for benchmark discovery and evaluation runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

EvaluationSelectionMode = Literal["all", "one", "many"]
CommandStatus = Literal["succeeded", "failed", "skipped"]
EvaluationStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class BenchmarkSelection:
    """User-visible benchmark selector contract."""

    raw_value: str
    mode: EvaluationSelectionMode
    benchmark_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkMetadata:
    """Subset of XBOW benchmark metadata used by DAPT evaluation."""

    name: str
    description: str
    level: int
    win_condition: str
    tags: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    canaries: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkTargetConfig:
    """Repo-visible target-resolution contract for one benchmark."""

    target_url: str
    target_host: str | None = None
    initial_context: dict[str, object] = field(default_factory=dict)
    success_conditions: tuple[str, ...] = ()
    objective_summary: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkSpec:
    """Discovered benchmark plus DAPT-specific runtime details."""

    benchmark_id: str
    benchmark_dir: Path
    compose_file: Path
    metadata_file: Path
    target_config_file: Path
    metadata: BenchmarkMetadata
    target: BenchmarkTargetConfig
    build_command: tuple[str, ...]
    up_command: tuple[str, ...]
    down_command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LifecycleCommandResult:
    """One benchmark lifecycle command execution outcome."""

    name: str
    command: tuple[str, ...]
    cwd: str
    status: CommandStatus
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "command": list(self.command),
            "cwd": self.cwd,
            "status": self.status,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


@dataclass(frozen=True, slots=True)
class CampaignRunResult:
    """Outcome returned by the DAPT campaign runner for one benchmark."""

    session_id: str
    target_name: str
    completed: bool
    termination_reason: str | None
    objective_met: bool
    turn_count: int
    artifact_paths: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "target_name": self.target_name,
            "completed": self.completed,
            "termination_reason": self.termination_reason,
            "objective_met": self.objective_met,
            "turn_count": self.turn_count,
            "artifact_paths": list(self.artifact_paths),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkRunResult:
    """Persisted evaluation result for one benchmark."""

    run_id: str
    benchmark_id: str
    benchmark_name: str
    benchmark_dir: str
    target_url: str
    status: EvaluationStatus
    objective_met: bool
    termination_reason: str | None = None
    session_id: str | None = None
    lifecycle_results: tuple[LifecycleCommandResult, ...] = ()
    campaign: CampaignRunResult | None = None
    notes: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "benchmark_id": self.benchmark_id,
            "benchmark_name": self.benchmark_name,
            "benchmark_dir": self.benchmark_dir,
            "target_url": self.target_url,
            "status": self.status,
            "objective_met": self.objective_met,
            "termination_reason": self.termination_reason,
            "session_id": self.session_id,
            "lifecycle_results": [result.as_payload() for result in self.lifecycle_results],
            "campaign": None if self.campaign is None else self.campaign.as_payload(),
            "notes": list(self.notes),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    """Aggregate outcome for one evaluation invocation."""

    run_id: str
    benchmark_root: str
    selection: BenchmarkSelection
    results: tuple[BenchmarkRunResult, ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_benchmarks(self) -> int:
        return len(self.results)

    @property
    def succeeded(self) -> int:
        return sum(1 for result in self.results if result.status == "succeeded")

    @property
    def failed(self) -> int:
        return sum(1 for result in self.results if result.status == "failed")

    def as_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "benchmark_root": self.benchmark_root,
            "selection": {
                "raw_value": self.selection.raw_value,
                "mode": self.selection.mode,
                "benchmark_ids": list(self.selection.benchmark_ids),
            },
            "total_benchmarks": self.total_benchmarks,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "results": [result.as_payload() for result in self.results],
            "created_at": self.created_at.isoformat(),
        }
