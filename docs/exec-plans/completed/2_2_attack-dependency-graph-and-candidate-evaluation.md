# 2_2_attack-dependency-graph-and-candidate-evaluation

## Status

Completed, awaiting user audit before any repository push.

## Goal

Define the planner-side attack dependency graph and the candidate-evaluation machinery that ranks expansion options using dependency-aware reasoning, aligned with:

- `AGENTS.md`
- `docs/design-docs/0_OVERALL_DESIGN.md`
- `docs/design-docs/2_PLAN.md`

This sub-plan should establish how the planner records prerequisites, effects, contradictions, and downstream unlock structure before a full planner runtime is implemented.

## Repo Facts

1. `docs/design-docs/2_PLAN.md` assigns attack decision making to the attack dependency graph rather than to isolated vulnerability ranking.
2. The design doc defines four required evaluation dimensions: prerequisite satisfaction, downstream unlock value, dependency centrality, and contradiction penalty.
3. The same design doc assigns graph updates to the Planner whenever new observations, execution outcomes, or newly discovered weaknesses arrive.
4. There is no current graph model, candidate scoring implementation, or planner package under `src/dapt/`.
5. The existing executor and perceptor layers already produce the raw execution outputs and planner feedback that the future graph updater must consume.

## Planned Work

- Define typed graph models covering:
  - candidate nodes,
  - prerequisite conditions,
  - produced effects,
  - supporting and contradicting evidence,
  - directed dependency edges.
- Define the linkage contract between search-tree nodes and dependency-graph candidates so the two structures share stable identifiers without duplicating planner state arbitrarily.
- Implement graph update rules for planner events, including:
  - new observation ingestion,
  - hypothesis creation,
  - action success,
  - action failure,
  - contradiction/evidence updates.
- Implement deterministic candidate-evaluation outputs that expose:
  - satisfied vs unsatisfied prerequisites,
  - estimated downstream unlock set,
  - structural dependency importance,
  - contradiction penalties,
  - final planner-facing score components.
- Define repo-local serialization and artifact conventions for graph snapshots and scored candidate views.
- Add deterministic proofs/tests for:
  - graph construction from planner events,
  - prerequisite satisfaction computation,
  - contradiction handling,
  - downstream unlock propagation,
  - candidate ranking stability under controlled fixtures.

## Boundaries

- No executor invocation or Perceptor summarization changes in this sub-plan.
- No mutable memory subsystem beyond planner-owned graph state.
- No opaque scoring heuristics without inspectable intermediate components.
- No full turn-by-turn planner orchestration yet beyond the graph update and evaluation boundaries.

## Deliverables

- Attack dependency graph contracts and models.
- Candidate-evaluation contract with inspectable score components.
- Graph persistence/storage convention.
- Deterministic tests for graph updates and scoring behavior.

## Dependencies

- Depends on `2_1_search-tree-contracts-and-state` for stable planner node identities and search-tree linkage.
- Should remain compatible with current executor result and Perceptor feedback contracts.

## Completed Work

- Added dependency-graph candidate, edge, and evaluation contracts under `src/dapt/planner/`.
- Implemented a deterministic `AttackDependencyGraph` with:
  - observation-driven condition updates,
  - candidate registration,
  - action-outcome updates,
  - dependency edge derivation,
  - inspectable score components for prerequisite satisfaction, downstream unlock value, dependency centrality, and contradiction penalty.
- Added repo-local persistence for dependency-graph snapshots and candidate rankings under `artifacts/planner/`.
- Added deterministic tests covering gateway candidate ranking, contradiction handling, unlock propagation, and persisted ranking views.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'`

## Audit Request

Please audit this completed sub-plan before additional planner work continues.
