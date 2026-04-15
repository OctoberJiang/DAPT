# 2_1_search-tree-contracts-and-state

## Status

Completed, awaiting user audit before any repository push.

## Goal

Define the planner-side search tree as the primary state structure for DAPT turns, aligned with:

- `AGENTS.md`
- `docs/design-docs/0_OVERALL_DESIGN.md`
- `docs/design-docs/2_PLAN.md`
- `docs/references/pentestgpt-v2-tree-nodes.md`

This sub-plan should establish the typed contracts, state transitions, and repo-local persistence conventions for the search tree before any planner decision runtime is implemented.

## Repo Facts

1. `docs/design-docs/0_OVERALL_DESIGN.md` requires the Planner to construct the search tree on each turn and delegate execution from selected nodes.
2. `docs/design-docs/2_PLAN.md` defines the tree as root/branch/node based, with node-level reasoning units spanning observation, hypothesis, action, and effect.
3. `docs/references/pentestgpt-v2-tree-nodes.md` currently defines three concrete node types to preserve in the implementation boundary: observation, hypothesis, and action.
4. `src/dapt/` currently contains executor, perceptor, and knowledge packages, but no planner package or search-tree implementation.
5. The Perceptor already emits planner-facing feedback, but there is no in-repo planner state model that can ingest that feedback yet.

## Planned Work

- Create the base planner package layout under `src/dapt/planner/`.
- Define typed search-tree models covering:
  - planner session / campaign root state,
  - node identity and parent-child relationships,
  - node kinds aligned with the reference and design docs,
  - node status and expansion state,
  - evidence and artifact references,
  - links from action outcomes back into subsequent observations.
- Define legal search-tree transitions so the planner can extend paths without hidden state, including:
  - observation to hypothesis,
  - hypothesis to action,
  - action to follow-up observation or failure state.
- Define repo-local serialization and artifact conventions for planner state snapshots so tree state remains inspectable in-repo.
- Add deterministic proofs/tests for:
  - node construction,
  - path extension,
  - ancestry/path queries,
  - Perceptor feedback ingestion into new observation nodes.

## Boundaries

- No candidate scoring or attack-dependency prioritization in this sub-plan beyond the fields needed to support later graph linkage.
- No executor dispatch logic inside the planner state layer.
- No memory-layer design or mutation beyond planner-owned tree state.
- No hidden or implicit state outside repo-local planner artifacts.

## Deliverables

- `src/dapt/planner/` package skeleton.
- Search-tree contracts and models.
- Search-tree persistence/storage convention.
- Deterministic tests for planner tree state and transitions.

## Dependencies

- Should land before `2_2_attack-dependency-graph-and-candidate-evaluation`, or at minimum establish the stable node identifiers and state contracts that plan depends on.
- Should remain forward-compatible with existing executor and perceptor contracts.

## Completed Work

- Added a new `src/dapt/planner/` package and exported it from `src/dapt/__init__.py`.
- Added immutable planner node records plus a mutable `SearchTreeState` container with:
  - deterministic node identifiers,
  - observation/hypothesis/action transitions,
  - ancestry/path queries,
  - planner-feedback ingestion from the Perceptor.
- Added repo-local planner artifact persistence under `artifacts/planner/`.
- Added deterministic tests covering search-tree construction, Perceptor-feedback ingestion, and snapshot persistence.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'`

## Audit Request

Please audit this completed sub-plan before additional planner work continues.
