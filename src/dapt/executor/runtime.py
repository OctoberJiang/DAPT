"""Executor runtime that dispatches tools and skills and persists raw outputs."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .contracts import FieldSpec, SkillSpec, ToolSpec
from .errors import (
    NonRetryableExecutionError,
    PreconditionsFailedError,
    RetryableExecutionError,
    SchemaValidationError,
    UnknownActionError,
)
from .models import ExecutionRequest, ExecutionResult, OutputEnvelope
from .registry import SpecRegistry
from .storage import ArtifactStoreLayout


TYPE_VALIDATORS: dict[str, type[Any] | tuple[type[Any], ...]] = {
    "any": object,
    "str": str,
    "int": int,
    "float": (int, float),
    "bool": bool,
    "dict": dict,
    "list": list,
}


class Executor:
    """Runtime entrypoint for planner-issued execution requests."""

    def __init__(
        self,
        *,
        registry: SpecRegistry,
        artifact_store: ArtifactStoreLayout,
        max_retries: int = 1,
    ) -> None:
        self.registry = registry
        self.artifact_store = artifact_store
        self.max_retries = max_retries
        self.artifact_store.initialize()

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if request.action_kind == "tool":
            spec = self.registry.get_tool(request.target_name)
            if spec is None:
                raise UnknownActionError(f"Unknown tool: {request.target_name}")
            normalized = self._normalize_request(
                request=request,
                input_schema=spec.input_schema,
                default_parameters=spec.default_parameters,
            )
            return self._execute_tool(spec=spec, request=normalized)

        if request.action_kind == "skill":
            spec = self.registry.get_skill(request.target_name)
            if spec is None:
                raise UnknownActionError(f"Unknown skill: {request.target_name}")
            normalized = self._normalize_request(
                request=request,
                input_schema=spec.input_schema,
                default_parameters={},
            )
            return self._execute_skill(spec=spec, request=normalized)

        raise UnknownActionError(f"Unsupported action kind: {request.action_kind}")

    def _execute_tool(
        self,
        *,
        spec: ToolSpec,
        request: ExecutionRequest,
        step_name: str | None = None,
    ) -> ExecutionResult:
        attempts = 0
        persisted_artifacts: list = []
        try:
            if spec.executor is None:
                raise NonRetryableExecutionError(f"Tool '{spec.name}' has no executor")
            self._run_validators(spec.validators, request)
            self._run_validators(
                spec.preconditions,
                request,
                error_type=PreconditionsFailedError,
            )
        except (SchemaValidationError, PreconditionsFailedError, NonRetryableExecutionError) as exc:
            attempts = 1
            error_output = OutputEnvelope(
                stderr=str(exc),
                metadata={"retryable": False, "error_type": type(exc).__name__},
            )
            persisted_artifacts.extend(
                self.artifact_store.persist_output(
                    request=request,
                    output=error_output,
                    artifact_name=spec.name,
                    attempt=attempts,
                    step_name=step_name,
                )
            )
            return self._failure_result(
                request=request,
                attempts=attempts,
                output=error_output,
                artifacts=persisted_artifacts,
                error_message=str(exc),
            )

        while attempts <= self.max_retries:
            attempts += 1
            try:
                output = spec.executor(request)
            except RetryableExecutionError as exc:
                error_output = OutputEnvelope(
                    stderr=str(exc),
                    metadata={"retryable": True, "error_type": type(exc).__name__},
                )
                persisted_artifacts.extend(
                    self.artifact_store.persist_output(
                        request=request,
                        output=error_output,
                        artifact_name=spec.name,
                        attempt=attempts,
                        step_name=step_name,
                    )
                )
                if attempts > self.max_retries:
                    return self._failure_result(
                        request=request,
                        attempts=attempts,
                        output=error_output,
                        artifacts=persisted_artifacts,
                        error_message=str(exc),
                    )
                continue
            except (SchemaValidationError, PreconditionsFailedError, NonRetryableExecutionError) as exc:
                error_output = OutputEnvelope(
                    stderr=str(exc),
                    metadata={"retryable": False, "error_type": type(exc).__name__},
                )
                persisted_artifacts.extend(
                    self.artifact_store.persist_output(
                        request=request,
                        output=error_output,
                        artifact_name=spec.name,
                        attempt=attempts,
                        step_name=step_name,
                    )
                )
                return self._failure_result(
                    request=request,
                    attempts=attempts,
                    output=error_output,
                    artifacts=persisted_artifacts,
                    error_message=str(exc),
                )
            except Exception as exc:
                error_output = OutputEnvelope(
                    stderr=str(exc),
                    metadata={"retryable": False, "error_type": type(exc).__name__},
                )
                persisted_artifacts.extend(
                    self.artifact_store.persist_output(
                        request=request,
                        output=error_output,
                        artifact_name=spec.name,
                        attempt=attempts,
                        step_name=step_name,
                    )
                )
                return self._failure_result(
                    request=request,
                    attempts=attempts,
                    output=error_output,
                    artifacts=persisted_artifacts,
                    error_message=str(exc),
                )

            persisted_artifacts.extend(
                self.artifact_store.persist_output(
                    request=request,
                    output=output,
                    artifact_name=spec.name,
                    attempt=attempts,
                    step_name=step_name,
                )
            )
            try:
                self._raise_for_failed_output(output)
                effects = spec.output_parser(output) if spec.output_parser else {}
                result = ExecutionResult(
                    request_id=request.request_id,
                    target_name=request.target_name,
                    action_kind=request.action_kind,
                    status="succeeded",
                    output=output,
                    artifacts=tuple(persisted_artifacts),
                    effects=effects,
                    attempts=attempts,
                    completed_at=datetime.now(UTC),
                )
                self._run_result_validators(spec.postconditions, result)
                return result
            except RetryableExecutionError as exc:
                if attempts > self.max_retries:
                    return self._failure_result(
                        request=request,
                        attempts=attempts,
                        output=output,
                        artifacts=persisted_artifacts,
                        error_message=str(exc),
                    )
                continue
            except (SchemaValidationError, PreconditionsFailedError, NonRetryableExecutionError) as exc:
                return self._failure_result(
                    request=request,
                    attempts=attempts,
                    output=output,
                    artifacts=persisted_artifacts,
                    error_message=str(exc),
                )
            except Exception as exc:
                return self._failure_result(
                    request=request,
                    attempts=attempts,
                    output=output,
                    artifacts=persisted_artifacts,
                    error_message=str(exc),
                )

        unreachable_error = "Executor exhausted retry loop unexpectedly"
        return self._failure_result(
            request=request,
            attempts=attempts,
            output=OutputEnvelope(stderr=unreachable_error),
            artifacts=persisted_artifacts,
            error_message=unreachable_error,
        )

    def _execute_skill(self, *, spec: SkillSpec, request: ExecutionRequest) -> ExecutionResult:
        self._run_validators(spec.validators, request)
        self._validate_required_state(spec, request)

        step_outputs: list[OutputEnvelope] = []
        all_artifacts = []
        step_effects: list[dict[str, Any]] = []

        for step in spec.step_sequence:
            self._run_validators(step.preconditions, request, error_type=PreconditionsFailedError)
            tool_spec = self.registry.get_tool(step.tool_name)
            if tool_spec is None:
                raise UnknownActionError(
                    f"Skill '{spec.name}' references unknown tool '{step.tool_name}'"
                )

            step_request = replace(
                request,
                action_kind="tool",
                target_name=step.tool_name,
                parameters=step.parameter_builder(request),
            )
            normalized_step_request = self._normalize_request(
                request=step_request,
                input_schema=tool_spec.input_schema,
                default_parameters=tool_spec.default_parameters,
            )
            step_result = self._execute_tool(
                spec=tool_spec,
                request=normalized_step_request,
                step_name=step.name,
            )
            all_artifacts.extend(step_result.artifacts)
            if step_result.output is not None:
                step_outputs.append(step_result.output)
            if step_result.effects:
                step_effects.append(step_result.effects)
            if step_result.status != "succeeded" and step.on_failure != "continue":
                combined_output = self._combine_outputs(step_outputs, step_effects, spec.name)
                all_artifacts.extend(
                    self.artifact_store.persist_output(
                        request=request,
                        output=combined_output,
                        artifact_name=spec.name,
                        attempt=1,
                    )
                )
                return self._failure_result(
                    request=request,
                    attempts=1,
                    output=combined_output,
                    artifacts=all_artifacts,
                    error_message=step_result.error_message or f"Skill step failed: {step.name}",
                )

        combined_output = self._combine_outputs(step_outputs, step_effects, spec.name)
        all_artifacts.extend(
            self.artifact_store.persist_output(
                request=request,
                output=combined_output,
                artifact_name=spec.name,
                attempt=1,
            )
        )
        effects = spec.result_aggregator(combined_output) if spec.result_aggregator else {
            "step_count": len(step_outputs),
            "produced_effects": list(spec.produced_effects),
        }
        return ExecutionResult(
            request_id=request.request_id,
            target_name=request.target_name,
            action_kind=request.action_kind,
            status="succeeded",
            output=combined_output,
            artifacts=tuple(all_artifacts),
            effects=effects,
            attempts=1,
            completed_at=datetime.now(UTC),
        )

    def _normalize_request(
        self,
        *,
        request: ExecutionRequest,
        input_schema: tuple[FieldSpec, ...],
        default_parameters: dict[str, Any],
    ) -> ExecutionRequest:
        parameters = dict(default_parameters)
        for field in input_schema:
            if field.default is not None and field.name not in parameters:
                parameters[field.name] = field.default
        parameters.update(request.parameters)

        for field in input_schema:
            if field.required and field.name not in parameters:
                raise SchemaValidationError(f"Missing required parameter: {field.name}")
            if field.name in parameters and not self._matches_type(parameters[field.name], field):
                raise SchemaValidationError(
                    f"Parameter '{field.name}' must be of type {field.type_name}"
                )

        return replace(request, parameters=parameters)

    def _matches_type(self, value: Any, field: FieldSpec) -> bool:
        expected_type = TYPE_VALIDATORS.get(field.type_name, object)
        return isinstance(value, expected_type)

    def _run_validators(
        self,
        validators,
        request: ExecutionRequest,
        *,
        error_type: type[Exception] = SchemaValidationError,
    ) -> None:
        for validator in validators:
            try:
                validator(request)
            except Exception as exc:
                raise error_type(str(exc)) from exc

    def _run_result_validators(self, validators, result: ExecutionResult) -> None:
        for validator in validators:
            validator(result)

    def _validate_required_state(self, spec: SkillSpec, request: ExecutionRequest) -> None:
        missing = [key for key in spec.required_state if key not in request.context]
        if missing:
            joined = ", ".join(missing)
            raise PreconditionsFailedError(
                f"Skill '{spec.name}' missing required context state: {joined}"
            )

    def _raise_for_failed_output(self, output: OutputEnvelope) -> None:
        if output.exit_code in (None, 0):
            return
        message = output.stderr or output.stdout or f"Execution failed with exit code {output.exit_code}"
        if output.metadata.get("retryable"):
            raise RetryableExecutionError(message)
        raise NonRetryableExecutionError(message)

    def _combine_outputs(
        self,
        outputs: list[OutputEnvelope],
        step_effects: list[dict[str, Any]],
        skill_name: str,
    ) -> OutputEnvelope:
        stdout_parts = [output.stdout for output in outputs if output.stdout]
        stderr_parts = [output.stderr for output in outputs if output.stderr]
        return OutputEnvelope(
            stdout="\n".join(stdout_parts),
            stderr="\n".join(stderr_parts),
            exit_code=0 if not stderr_parts else None,
            metadata={
                "skill": skill_name,
                "step_count": len(outputs),
                "step_effects": step_effects,
            },
        )

    def _failure_result(
        self,
        *,
        request: ExecutionRequest,
        attempts: int,
        output: OutputEnvelope,
        artifacts,
        error_message: str,
    ) -> ExecutionResult:
        return ExecutionResult(
            request_id=request.request_id,
            target_name=request.target_name,
            action_kind=request.action_kind,
            status="failed",
            output=output,
            artifacts=tuple(artifacts),
            attempts=attempts,
            error_message=error_message,
            completed_at=datetime.now(UTC),
        )
