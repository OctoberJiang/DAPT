# 2_5_planner-orchestration-loop-and-stop-conditions

## Status

Completed, awaiting user audit before any repository push.

## Goal

Implement the top-level planner service that orchestrates the planning turn loop end-to-end: initialize state, ingest new observations, synthesize candidates, select the next action, hand off execution, receive Perceptor feedback, and decide whether to continue or stop.

This sub-plan should make the Planner operational as the orchestrator described in the design docs.

## Repo Facts

1. `docs/design-docs/0_OVERALL_DESIGN.md` describes the Planner as the component that constructs the search tree and attack dependency graph each turn, delegates execution, and responds to Perceptor feedback.
2. The repository now has the main lower-level pieces needed for that loop:
  - executor runtime,
  - perceptor runtime and planner feedback,
  - planner tree state,
  - dependency graph state,
  - candidate scoring.
3. The repository still lacks a top-level planner runtime/service that coordinates those pieces into a turn-by-turn workflow.
4. There is no explicit stop-condition model yet for:
  - exhaustion,
  - contradiction dead-end,
  - success objective reached,
  - max-turn / safety limit.

## Planned Work

- Define planner runtime contracts covering:
  - planner session state,
  - per-turn inputs and outputs,
  - orchestration steps,
  - termination reasons,
  - persisted planner artifacts for each turn.
- Implement a top-level planner service that:
  - initializes campaign state from the target,
  - ingests new Perceptor feedback,
  - synthesizes/updates candidates,
  - ranks and selects the next candidate,
  - emits an execution request,
  - ingests the resulting feedback into the next planner state.
- Implement stop-condition and failure-handling logic for:
  - no viable candidates,
  - fully contradicted frontier,
  - explicit success criteria,
  - iteration safety bounds.
- Persist planner turn artifacts so the whole decision trail remains inspectable in-repo.
- Add deterministic end-to-end tests covering:
  - multi-turn progression,
  - successful unlock chains,
  - dead-end termination,
  - stable replay of the same fixture.

## Boundaries

- No memory-system redesign in this sub-plan.
- No report-generation subsystem unless required only as a minimal planner output contract.
- No network-backed or hidden orchestration state.

## Deliverables

- Top-level planner runtime/service under `src/dapt/planner/`.
- Turn-loop and stop-condition contracts.
- Deterministic end-to-end planner tests spanning executor/perceptor/planner integration boundaries as needed.

## Dependencies

- Depends on `2_3_candidate-synthesis-and-graph-ingestion`.
- Depends on `2_4_dependency-aware-selection-and-execution-requests`.
- Should remain forward-compatible with later memory and evaluation work.

## Completed Work

- Added the top-level planner runtime in `src/dapt/planner/service.py`.
- Implemented planner session initialization, turn execution, stop conditions, and end-to-end orchestration across:
  - search-tree state,
  - dependency-graph state,
  - executor handoff,
  - Perceptor feedback ingestion.
- Added repo-local persistence for planner session snapshots and per-turn records.
- Added deterministic end-to-end planner tests covering a multi-turn web unlock chain and success-condition termination.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'`

## Audit Request

Please audit this completed sub-plan before additional planner work continues.
