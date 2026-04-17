"""Executor runtime that dispatches tools and skills and persists raw outputs."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from inspect import signature
from time import perf_counter
from typing import Any

from .contracts import FieldSpec, SkillSpec, ToolSpec
from .errors import (
    NonRetryableExecutionError,
    PreconditionsFailedError,
    RetryableExecutionError,
    SchemaValidationError,
    UnknownActionError,
)
from .models import ExecutionRequest, ExecutionResult, ExecutionUsage, OutputEnvelope, SkillStepRecord
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
        started_at = perf_counter()
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
            error_output = self._augment_output_metadata(
                request=request,
                output=OutputEnvelope(
                    stderr=str(exc),
                    metadata={"retryable": False, "error_type": type(exc).__name__},
                ),
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
                usage=ExecutionUsage(
                    tool_invocations=0,
                    elapsed_seconds=self._elapsed_since(started_at),
                ),
            )

        while attempts <= self.max_retries:
            attempts += 1
            try:
                output = self._augment_output_metadata(request=request, output=spec.executor(request))
            except RetryableExecutionError as exc:
                error_output = self._augment_output_metadata(
                    request=request,
                    output=OutputEnvelope(
                        stderr=str(exc),
                        metadata={"retryable": True, "error_type": type(exc).__name__},
                    ),
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
                        usage=ExecutionUsage(
                            tool_invocations=attempts,
                            elapsed_seconds=self._elapsed_since(started_at),
                        ),
                    )
                continue
            except (SchemaValidationError, PreconditionsFailedError, NonRetryableExecutionError) as exc:
                error_output = self._augment_output_metadata(
                    request=request,
                    output=OutputEnvelope(
                        stderr=str(exc),
                        metadata={"retryable": False, "error_type": type(exc).__name__},
                    ),
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
                    usage=ExecutionUsage(
                        tool_invocations=attempts,
                        elapsed_seconds=self._elapsed_since(started_at),
                    ),
                )
            except Exception as exc:
                error_output = self._augment_output_metadata(
                    request=request,
                    output=OutputEnvelope(
                        stderr=str(exc),
                        metadata={"retryable": False, "error_type": type(exc).__name__},
                    ),
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
                    usage=ExecutionUsage(
                        tool_invocations=attempts,
                        elapsed_seconds=self._elapsed_since(started_at),
                    ),
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
                    usage=ExecutionUsage(
                        tool_invocations=attempts,
                        elapsed_seconds=self._elapsed_since(started_at),
                    ),
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
                        usage=ExecutionUsage(
                            tool_invocations=attempts,
                            elapsed_seconds=self._elapsed_since(started_at),
                        ),
                    )
                continue
            except (SchemaValidationError, PreconditionsFailedError, NonRetryableExecutionError) as exc:
                return self._failure_result(
                    request=request,
                    attempts=attempts,
                    output=output,
                    artifacts=persisted_artifacts,
                    error_message=str(exc),
                    usage=ExecutionUsage(
                        tool_invocations=attempts,
                        elapsed_seconds=self._elapsed_since(started_at),
                    ),
                )
            except Exception as exc:
                return self._failure_result(
                    request=request,
                    attempts=attempts,
                    output=output,
                    artifacts=persisted_artifacts,
                    error_message=str(exc),
                    usage=ExecutionUsage(
                        tool_invocations=attempts,
                        elapsed_seconds=self._elapsed_since(started_at),
                    ),
                )

        unreachable_error = "Executor exhausted retry loop unexpectedly"
        return self._failure_result(
            request=request,
            attempts=attempts,
            output=OutputEnvelope(stderr=unreachable_error),
            artifacts=persisted_artifacts,
            error_message=unreachable_error,
            usage=ExecutionUsage(
                tool_invocations=attempts,
                elapsed_seconds=self._elapsed_since(started_at),
            ),
        )

    def _execute_skill(self, *, spec: SkillSpec, request: ExecutionRequest) -> ExecutionResult:
        started_at = perf_counter()
        try:
            self._run_validators(spec.validators, request)
            self._validate_required_state(spec, request)
        except (SchemaValidationError, PreconditionsFailedError, NonRetryableExecutionError) as exc:
            output = self._augment_output_metadata(
                request=request,
                output=OutputEnvelope(
                    stderr=str(exc),
                    metadata={"skill": spec.name, "step_records": []},
                ),
            )
            artifacts = self.artifact_store.persist_output(
                request=request,
                output=output,
                artifact_name=spec.name,
                attempt=1,
            )
            return self._failure_result(
                request=request,
                attempts=1,
                output=output,
                artifacts=artifacts,
                error_message=str(exc),
                usage=ExecutionUsage(
                    tool_invocations=0,
                    elapsed_seconds=self._elapsed_since(started_at),
                ),
            )

        step_outputs: list[OutputEnvelope] = []
        all_artifacts = []
        step_records: list[SkillStepRecord] = []
        total_tool_invocations = 0

        for step in spec.step_sequence:
            if step.run_if is not None and not self._call_with_step_records(
                step.run_if,
                request,
                step_records,
            ):
                step_records.append(
                    SkillStepRecord(
                        name=step.name,
                        tool_name=step.tool_name,
                        status="skipped",
                    )
                )
                continue

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
                parameters=self._call_with_step_records(
                    step.parameter_builder,
                    request,
                    step_records,
                ),
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
            if step_result.usage is not None:
                total_tool_invocations += step_result.usage.tool_invocations
            step_records.append(
                SkillStepRecord(
                    name=step.name,
                    tool_name=step.tool_name,
                    status=step_result.status,
                    effects=step_result.effects,
                    error_message=step_result.error_message,
                )
            )
            if step_result.status != "succeeded" and step.on_failure != "continue":
                combined_output = self._augment_output_metadata(
                    request=request,
                    output=self._combine_outputs(step_outputs, step_records, spec.name),
                )
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
                    usage=ExecutionUsage(
                        tool_invocations=total_tool_invocations,
                        elapsed_seconds=self._elapsed_since(started_at),
                    ),
                )

        combined_output = self._augment_output_metadata(
            request=request,
            output=self._combine_outputs(step_outputs, step_records, spec.name),
        )
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
            usage=ExecutionUsage(
                tool_invocations=total_tool_invocations,
                elapsed_seconds=self._elapsed_since(started_at),
            ),
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
            if field.name in parameters and parameters[field.name] is None and not field.required:
                continue
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
        step_records: list[SkillStepRecord],
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
                "step_effects": [record.effects for record in step_records if record.effects],
                "step_records": [asdict(record) for record in step_records],
            },
        )

    def _call_with_step_records(
        self,
        callable_obj,
        request: ExecutionRequest,
        step_records: list[SkillStepRecord],
    ):
        if len(signature(callable_obj).parameters) <= 1:
            return callable_obj(request)
        return callable_obj(request, tuple(step_records))

    def _failure_result(
        self,
        *,
        request: ExecutionRequest,
        attempts: int,
        output: OutputEnvelope,
        artifacts,
        error_message: str,
        usage: ExecutionUsage,
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
            usage=usage,
        )

    def _elapsed_since(self, started_at: float) -> float:
        return perf_counter() - started_at

    def _augment_output_metadata(self, *, request: ExecutionRequest, output: OutputEnvelope) -> OutputEnvelope:
        metadata = dict(output.metadata)
        if request.context.get("target_url") and "request_target_url" not in metadata:
            metadata["request_target_url"] = request.context["target_url"]
        if request.context.get("target_host") and "request_target_host" not in metadata:
            metadata["request_target_host"] = request.context["target_host"]
        return replace(output, metadata=metadata)
