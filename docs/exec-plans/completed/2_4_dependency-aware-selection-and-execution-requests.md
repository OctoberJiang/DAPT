# 2_4_dependency-aware-selection-and-execution-requests

## Status

Completed, awaiting user audit before any repository push.

## Goal

Implement the planner decision layer that selects the next candidate node to expand using the dependency graph, then materializes that decision into executor-ready action requests and action nodes.

This sub-plan should make the planner capable of converting scored opportunities into concrete next actions, while preserving the design boundary that the Planner decides and the Executor executes.

## Repo Facts

1. `docs/design-docs/2_PLAN.md` defines candidate selection as a dependency-aware decision problem rather than simple isolated ranking.
2. `src/dapt/planner/` already computes inspectable score components for candidates, but does not yet convert rankings into committed planner actions.
3. `src/dapt/executor/models.py` already defines `ExecutionRequest`, including planner node linkage through `planner_node_id`.
4. There is currently no planner-side policy for:
  - ranking tie-breaks,
  - blocked-candidate handling,
  - action generation,
  - request emission.

## Planned Work

- Define planner selection-policy contracts covering:
  - eligible candidate filtering,
  - score-based ranking,
  - tie-break rules,
  - contradiction/blocking behavior,
  - terminal/no-op conditions when nothing reasonable is executable.
- Implement planner-side action-generation logic that maps selected candidates to:
  - concrete action descriptions,
  - executor tool or skill targets,
  - parameters/context,
  - `ExecutionRequest` objects linked back to planner nodes.
- Implement tree updates for committed planning decisions, including:
  - selected hypothesis marking,
  - action node creation,
  - request metadata capture,
  - path-state updates.
- Add deterministic tests covering:
  - available-candidate selection,
  - tie-break stability,
  - blocked/contradicted candidate exclusion,
  - action-node creation,
  - `ExecutionRequest` generation with correct planner linkage.

## Boundaries

- No full campaign loop in this sub-plan.
- No Executor dispatch implementation changes.
- No Perceptor summarization changes.
- No hidden heuristics that cannot be explained from persisted planner state.

## Deliverables

- Candidate-selection policy and action-generation helpers under `src/dapt/planner/`.
- Planner-to-Executor request emission contract.
- Deterministic tests for selection and request creation.

## Dependencies

- Depends on `2_3_candidate-synthesis-and-graph-ingestion`.
- Should land before `2_5_planner-orchestration-loop-and-stop-conditions`.

## Completed Work

- Added planner-side candidate selection and executor handoff logic under `src/dapt/planner/selection.py`.
- Implemented deterministic candidate filtering and tie-break rules using:
  - dependency-graph score,
  - planner-side priority metadata,
  - contradiction and blocked-state exclusion,
  - registry-backed action availability checks.
- Implemented action-node creation in the search tree plus `ExecutionRequest` emission linked back to the planner node id.
- Added planner tests covering selection stability and request generation.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'`

## Audit Request

Please audit this completed sub-plan before additional planner work continues.
