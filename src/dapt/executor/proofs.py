"""Concrete proof tool and skill specs for the executor architecture."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .contracts import FieldSpec, SkillSpec, SkillStepSpec, ToolSpec
from .errors import NonRetryableExecutionError, RetryableExecutionError
from .models import ExecutionRequest, OutputEnvelope
from .registry import SpecRegistry


def _require_command_parameter(request: ExecutionRequest) -> None:
    command = request.parameters.get("command")
    if not isinstance(command, list) or not command:
        raise ValueError("Parameter 'command' must be a non-empty list")
    if not all(isinstance(item, str) and item for item in command):
        raise ValueError("Each command argument must be a non-empty string")


def _validate_optional_cwd(request: ExecutionRequest) -> None:
    cwd = request.parameters.get("cwd")
    if cwd is None:
        return
    path = Path(cwd)
    if not path.exists():
        raise ValueError(f"Working directory does not exist: {cwd}")
    if not path.is_dir():
        raise ValueError(f"Working directory is not a directory: {cwd}")


def _run_local_command(request: ExecutionRequest) -> OutputEnvelope:
    command = request.parameters["command"]
    cwd = request.parameters.get("cwd")
    timeout_seconds = request.parameters.get("timeout_seconds", 30)

    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RetryableExecutionError(f"Command timed out after {timeout_seconds}s") from exc
    except FileNotFoundError as exc:
        raise NonRetryableExecutionError(f"Executable not found: {command[0]}") from exc
    except OSError as exc:
        raise RetryableExecutionError(str(exc)) from exc

    return OutputEnvelope(
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
        metadata={
            "command": command,
            "cwd": cwd,
            "timeout_seconds": timeout_seconds,
        },
    )


def _parse_local_command_output(output: OutputEnvelope) -> dict[str, object]:
    command = output.metadata.get("command", [])
    return {
        "command": command,
        "cwd": output.metadata.get("cwd"),
        "exit_code": output.exit_code,
        "stdout_lines": len(output.stdout.splitlines()),
        "stderr_lines": len(output.stderr.splitlines()),
    }


def make_local_command_tool() -> ToolSpec:
    return ToolSpec(
        name="run-local-command",
        description="Execute a local command with typed parameters and captured output.",
        input_schema=(
            FieldSpec(
                name="command",
                type_name="list",
                description="Command and arguments as a tokenized argv list.",
            ),
            FieldSpec(
                name="cwd",
                type_name="str",
                description="Optional working directory for the command.",
                required=False,
            ),
            FieldSpec(
                name="timeout_seconds",
                type_name="int",
                description="Execution timeout in seconds.",
                required=False,
                default=30,
            ),
        ),
        validators=(_require_command_parameter,),
        preconditions=(_validate_optional_cwd,),
        executor=_run_local_command,
        output_parser=_parse_local_command_output,
    )


def _workspace_recon_aggregator(output: OutputEnvelope) -> dict[str, object]:
    return {
        "step_count": output.metadata.get("step_count", 0),
        "steps": ["print-working-directory", "list-target-path"],
        "produced_effects": ["workspace-context", "directory-listing"],
    }


def make_workspace_recon_skill() -> SkillSpec:
    return SkillSpec(
        name="workspace-recon",
        goal="Collect basic local workspace context through a small multi-step procedure.",
        required_state=(),
        preferred_tools=("run-local-command",),
        input_schema=(
            FieldSpec(
                name="path",
                type_name="str",
                description="Directory path to inspect.",
            ),
        ),
        step_sequence=(
            SkillStepSpec(
                name="print-working-directory",
                tool_name="run-local-command",
                parameter_builder=lambda request: {"command": ["pwd"]},
                success_hint="capture current execution directory",
            ),
            SkillStepSpec(
                name="list-target-path",
                tool_name="run-local-command",
                parameter_builder=lambda request: {
                    "command": ["ls", "-la", request.parameters["path"]]
                },
                success_hint="capture target directory listing",
            ),
        ),
        result_aggregator=_workspace_recon_aggregator,
        success_conditions=(
            "current directory is captured",
            "target directory listing is captured",
        ),
        produced_effects=("workspace-context", "directory-listing"),
    )


def build_reference_registry() -> SpecRegistry:
    registry = SpecRegistry()
    registry.register_tool(make_local_command_tool())
    registry.register_skill(make_workspace_recon_skill())
    return registry
