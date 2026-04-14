# 3_2_executor-runtime

## Status

Completed, awaiting user audit before `3_3_reference-aligned-proofs`.

## Goal

Implement the executor runtime that receives planner requests, dispatches typed tools or skills, handles execution-level retries, and persists raw outputs for downstream Perceptor use.

## Planned Work

- Implement the `Executor` service that accepts a planner-issued execution request.
- Support dispatch to either:
  - a typed tool adapter,
  - a multi-step skill.
- Enforce execution-only boundaries:
  - no attack decision making,
  - no planner-side replanning,
  - no raw-output summarization.
- Implement execution-level retry logic for operational failures such as:
  - retryable command failure,
  - retryable environment failure,
  - recoverable missing/defaultable parameters.
- Persist raw execution outputs and return structured metadata pointing to those artifacts.
- Surface failure states without converting them into planning conclusions.

## Boundaries

- Retry logic must stay at the execution layer.
- If a failure requires changing the attack strategy, the executor should stop and return the failure, not improvise a new plan.

## Deliverables

- Runtime executor orchestration.
- Tool and skill dispatch flow.
- Retry policy implementation.
- Raw artifact persistence wiring.

## Completed Work

- Added executor runtime entrypoint and dispatch flow for both tools and skills.
- Added execution-layer error types to keep retryable and non-retryable failures explicit.
- Added a tool and skill spec registry.
- Implemented request normalization with schema/default handling.
- Implemented execution-level retry behavior for retryable failures.
- Wired raw stdout, stderr, and metadata persistence for each execution attempt.
- Added combined skill-output persistence and failure propagation rules.

## Verification

- `python3 -m compileall src`
- `PYTHONPATH=src python3 -c "...Executor smoke test..."`

## Dependencies

- Depends on `3_1_contracts-and-layout`.
- Should land before or alongside `3_3_reference-aligned-proofs`.

## Audit Request

Please audit this completed sub-plan before implementation continues.
