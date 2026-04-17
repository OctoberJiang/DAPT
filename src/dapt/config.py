"""Repo-visible mutable runtime configuration for DAPT."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from dapt.planner import PlannerBudgetLimits

DEFAULT_CONFIG_FILE_NAME = "dapt.config.json"


class RuntimeConfigError(ValueError):
    """Raised when the repo-visible runtime config is invalid."""


@dataclass(frozen=True, slots=True)
class PlannerLLMSettings:
    """Editable planner LLM settings loaded from the repo config."""

    enabled: bool = False
    provider: str | None = None
    model: str | None = None
    api_base_url: str | None = None
    api_key: str | None = None
    api_key_env_var: str = "DAPT_PLANNER_API_KEY"
    temperature: float = 0.2
    max_output_tokens: int = 1200
    timeout_seconds: float = 30.0
    extra_headers: dict[str, str] = field(default_factory=dict)
    input_cost_cny_per_1k_tokens: float | None = None
    output_cost_cny_per_1k_tokens: float | None = None

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enabled": self.enabled,
            "api_key_env_var": self.api_key_env_var,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
        }
        if self.provider is not None:
            payload["provider"] = self.provider
        if self.model is not None:
            payload["model"] = self.model
        if self.api_base_url is not None:
            payload["api_base_url"] = self.api_base_url
        if self.api_key is not None:
            payload["api_key"] = self.api_key
        if self.extra_headers:
            payload["extra_headers"] = dict(self.extra_headers)
        pricing: dict[str, float] = {}
        if self.input_cost_cny_per_1k_tokens is not None:
            pricing["input_cost_cny_per_1k_tokens"] = self.input_cost_cny_per_1k_tokens
        if self.output_cost_cny_per_1k_tokens is not None:
            pricing["output_cost_cny_per_1k_tokens"] = self.output_cost_cny_per_1k_tokens
        if pricing:
            payload["pricing"] = pricing
        return payload


@dataclass(frozen=True, slots=True)
class PlannerBudgetSettings:
    """Editable planner budget settings loaded from the repo config."""

    max_runtime_seconds: float | None = None
    max_tool_calls: int | None = None
    max_llm_cost_cny: float | None = None

    def to_limits(self) -> PlannerBudgetLimits:
        return PlannerBudgetLimits(
            max_runtime_seconds=self.max_runtime_seconds,
            max_tool_calls=self.max_tool_calls,
            max_llm_cost_cny=self.max_llm_cost_cny,
        )


@dataclass(frozen=True, slots=True)
class EvaluationDefaults:
    """Editable evaluation defaults loaded from the repo config."""

    benchmarks: str | None = None
    benchmark_root: str = "XBOW-benchmarks/benchmarks"
    run_id: str | None = None
    max_turns: int = 10
    build: bool = True
    bring_up: bool = True
    tear_down: bool = True


@dataclass(frozen=True, slots=True)
class ReportDefaults:
    """Editable report defaults loaded from the repo config."""

    session_dir: str | None = None
    report_format: str = "markdown"
    output: str | None = None


@dataclass(frozen=True, slots=True)
class PentestDefaults:
    """Editable pentest tool-command defaults loaded from the repo config."""

    tool_commands: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Normalized mutable repo config."""

    config_version: int = 1
    planner_llm: PlannerLLMSettings = field(default_factory=PlannerLLMSettings)
    planner_budget: PlannerBudgetSettings = field(default_factory=PlannerBudgetSettings)
    evaluation: EvaluationDefaults = field(default_factory=EvaluationDefaults)
    report: ReportDefaults = field(default_factory=ReportDefaults)
    pentest: PentestDefaults = field(default_factory=PentestDefaults)


def load_runtime_config(repo_root: Path, config_path: str | Path | None = None) -> RuntimeConfig:
    """Load the repo-visible runtime config, returning defaults when missing."""

    resolved_path = resolve_runtime_config_path(repo_root=repo_root, config_path=config_path)
    if not resolved_path.exists():
        return RuntimeConfig()
    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeConfigError("Runtime config root must be a JSON object.")

    config_version = _read_int(payload.get("config_version", 1), field_name="config_version")
    planner_payload = _read_mapping(payload.get("planner", {}), field_name="planner")
    llm_payload = _read_mapping(planner_payload.get("llm", {}), field_name="planner.llm")
    budget_payload = _read_mapping(planner_payload.get("budget", {}), field_name="planner.budget")
    evaluation_payload = _read_mapping(payload.get("evaluation", {}), field_name="evaluation")
    report_payload = _read_mapping(payload.get("report", {}), field_name="report")
    pentest_payload = _read_mapping(payload.get("pentest", {}), field_name="pentest")

    return RuntimeConfig(
        config_version=config_version,
        planner_llm=PlannerLLMSettings(
            enabled=_read_bool(llm_payload.get("enabled", False), field_name="planner.llm.enabled"),
            provider=_read_optional_string(llm_payload.get("provider"), field_name="planner.llm.provider"),
            model=_read_optional_string(llm_payload.get("model"), field_name="planner.llm.model"),
            api_base_url=_read_optional_string(
                llm_payload.get("api_base_url"),
                field_name="planner.llm.api_base_url",
            ),
            api_key=_read_optional_string(llm_payload.get("api_key"), field_name="planner.llm.api_key"),
            api_key_env_var=_read_optional_string(
                llm_payload.get("api_key_env_var", "DAPT_PLANNER_API_KEY"),
                field_name="planner.llm.api_key_env_var",
            )
            or "DAPT_PLANNER_API_KEY",
            temperature=_read_float(llm_payload.get("temperature", 0.2), field_name="planner.llm.temperature"),
            max_output_tokens=_read_int(
                llm_payload.get("max_output_tokens", 1200),
                field_name="planner.llm.max_output_tokens",
            ),
            timeout_seconds=_read_float(
                llm_payload.get("timeout_seconds", 30.0),
                field_name="planner.llm.timeout_seconds",
            ),
            extra_headers=_read_string_mapping(
                llm_payload.get("extra_headers", {}),
                field_name="planner.llm.extra_headers",
            ),
            input_cost_cny_per_1k_tokens=_read_optional_float(
                _read_mapping(llm_payload.get("pricing", {}), field_name="planner.llm.pricing").get(
                    "input_cost_cny_per_1k_tokens"
                ),
                field_name="planner.llm.pricing.input_cost_cny_per_1k_tokens",
            ),
            output_cost_cny_per_1k_tokens=_read_optional_float(
                _read_mapping(llm_payload.get("pricing", {}), field_name="planner.llm.pricing").get(
                    "output_cost_cny_per_1k_tokens"
                ),
                field_name="planner.llm.pricing.output_cost_cny_per_1k_tokens",
            ),
        ),
        planner_budget=PlannerBudgetSettings(
            max_runtime_seconds=_read_optional_float(
                budget_payload.get("max_runtime_seconds"),
                field_name="planner.budget.max_runtime_seconds",
            ),
            max_tool_calls=_read_optional_int(
                budget_payload.get("max_tool_calls"),
                field_name="planner.budget.max_tool_calls",
            ),
            max_llm_cost_cny=_read_optional_float(
                budget_payload.get("max_llm_cost_cny"),
                field_name="planner.budget.max_llm_cost_cny",
            ),
        ),
        evaluation=EvaluationDefaults(
            benchmarks=_read_optional_string(
                evaluation_payload.get("benchmarks"),
                field_name="evaluation.benchmarks",
            ),
            benchmark_root=_read_string(
                evaluation_payload.get("benchmark_root", "XBOW-benchmarks/benchmarks"),
                field_name="evaluation.benchmark_root",
            ),
            run_id=_read_optional_string(evaluation_payload.get("run_id"), field_name="evaluation.run_id"),
            max_turns=_read_int(
                evaluation_payload.get("max_turns", 10),
                field_name="evaluation.max_turns",
            ),
            build=_read_bool(evaluation_payload.get("build", True), field_name="evaluation.build"),
            bring_up=_read_bool(evaluation_payload.get("bring_up", True), field_name="evaluation.bring_up"),
            tear_down=_read_bool(evaluation_payload.get("tear_down", True), field_name="evaluation.tear_down"),
        ),
        report=ReportDefaults(
            session_dir=_read_optional_string(report_payload.get("session_dir"), field_name="report.session_dir"),
            report_format=_read_string(report_payload.get("format", "markdown"), field_name="report.format"),
            output=_read_optional_string(report_payload.get("output"), field_name="report.output"),
        ),
        pentest=PentestDefaults(
            tool_commands=_read_tool_command_mapping(
                pentest_payload.get("tool_commands", {}),
                field_name="pentest.tool_commands",
            )
        ),
    )


def resolve_runtime_config_path(repo_root: Path, config_path: str | Path | None = None) -> Path:
    """Resolve the runtime config path relative to the repo root."""

    raw = Path(config_path) if config_path is not None else Path(DEFAULT_CONFIG_FILE_NAME)
    return raw if raw.is_absolute() else repo_root / raw


def _read_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise RuntimeConfigError(f"{field_name} must be a JSON object.")
    return value


def _read_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeConfigError(f"{field_name} must be a non-empty string.")
    return value


def _read_optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeConfigError(f"{field_name} must be a string when set.")
    stripped = value.strip()
    return stripped or None


def _read_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeConfigError(f"{field_name} must be a boolean.")
    return value


def _read_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeConfigError(f"{field_name} must be an integer.")
    return value


def _read_optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    return _read_int(value, field_name=field_name)


def _read_float(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeConfigError(f"{field_name} must be a number.")
    return float(value)


def _read_optional_float(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    return _read_float(value, field_name=field_name)


def _read_string_mapping(value: Any, *, field_name: str) -> dict[str, str]:
    mapping = _read_mapping(value, field_name=field_name)
    normalized: dict[str, str] = {}
    for key, item in mapping.items():
        if not isinstance(key, str):
            raise RuntimeConfigError(f"{field_name} keys must be strings.")
        if not isinstance(item, str):
            raise RuntimeConfigError(f"{field_name} values must be strings.")
        normalized[key] = item
    return normalized


def _read_tool_command_mapping(value: Any, *, field_name: str) -> dict[str, tuple[str, ...]]:
    mapping = _read_mapping(value, field_name=field_name)
    normalized: dict[str, tuple[str, ...]] = {}
    for key, item in mapping.items():
        if not isinstance(key, str) or not key.strip():
            raise RuntimeConfigError(f"{field_name} keys must be non-empty strings.")
        normalized[key.strip()] = _read_tool_command(item, field_name=f"{field_name}.{key.strip()}")
    return normalized


def _read_tool_command(value: Any, *, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        return (_read_string(value, field_name=field_name),)
    if not isinstance(value, list) or not value:
        raise RuntimeConfigError(f"{field_name} must be a string or a non-empty list of strings.")
    tokens: list[str] = []
    for index, item in enumerate(value):
        tokens.append(_read_string(item, field_name=f"{field_name}[{index}]"))
    return tuple(tokens)
