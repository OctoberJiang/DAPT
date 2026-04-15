# 2_8_mode-aware-objectives-and-success-termination

## Status

Completed, implemented and awaiting audit.

## Goal

Implement explicit objective modes and success semantics for the planner so campaigns can run under:

- `ctf` mode, where success means capturing the flag, and
- `real-world` mode, where success means obtaining root.

This sub-plan should make objective handling first-class in the planner, rather than treating success as ad hoc graph-condition checks.

## Repo Facts

1. The user explicitly wants two supported campaign modes: CTF and real-world.
2. The current planner supports generic `success_conditions`, but not mode-aware objective contracts.
3. The current stop logic in `src/dapt/planner/service.py` is still generic and does not differentiate objective semantics by campaign mode.
4. The search tree, dependency graph, and future memory system all need to understand objective progress and termination state.

## Planned Work

- Define objective-mode contracts covering:
  - campaign mode,
  - objective specification,
  - success indicators,
  - partial progress markers,
  - failure/dead-end semantics.
- Implement planner-side objective tracking for:
  - `ctf` flag capture signals,
  - `real-world` root-level success signals.
- Define how success evidence is recognized from planner/perceptor state, including:
  - retrieved flag artifacts or explicit flag observations,
  - root shell / root access / administrator-equivalent signals where applicable,
  - contradiction cases where a path no longer supports the objective.
- Update planner stop-condition logic so termination is objective-aware rather than purely frontier-aware.
- Persist objective progress and termination reasoning as repo-local planner artifacts.
- Add deterministic tests covering:
  - CTF objective completion,
  - real-world root objective completion,
  - partial progress without premature termination,
  - objective-aware dead-end handling.

## Boundaries

- No report-generation expansion beyond minimal objective outcome recording.
- No objective inference from hidden heuristics that are not tied to explicit evidence.
- No changes to executor semantics beyond what planner/perceptor evidence interpretation requires.

## Deliverables

- Objective-mode contracts and planner runtime updates.
- Objective-aware stop-condition handling.
- Deterministic tests for CTF and real-world mode success behavior.

## Dependencies

- Builds on `2_5_planner-orchestration-loop-and-stop-conditions`.
- Should remain compatible with `4_1_structured-and-retrieval-memory`.

## Implementation Notes

- Added explicit planner objective contracts and progress tracking for `ctf` and `real-world` campaign modes.
- Implemented objective-aware completion checks based on explicit observation evidence such as captured flags or root / administrator-equivalent indicators.
- Persisted objective-progress artifacts alongside the existing planner session, tree, and dependency-graph artifacts.
- Added deterministic tests covering CTF completion, real-world root completion, partial progress without premature termination, and objective-aware frontier-stop behavior.

## Audit Request

Please audit the implemented objective-mode contracts, explicit evidence matching rules, and objective-progress artifacts.
