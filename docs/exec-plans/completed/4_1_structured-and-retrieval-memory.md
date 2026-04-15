# 4_1_structured-and-retrieval-memory

## Status

Completed, implemented and awaiting audit.

## Goal

Implement the actual memory subsystem as both:

- a structured planner-owned memory store for facts, hypotheses, outcomes, and contradictions, and
- a retrieval-oriented long-term memory over repo-local artifacts and observations.

This sub-plan should replace the current append-only memory staging with a real memory layer that the planner and perceptor can both use without hidden state.

## Repo Facts

1. `docs/design-docs/4_MEMORY.md` is still effectively empty.
2. The current Perceptor only emits append-only `memory-staging` artifacts.
3. The user explicitly wants both structured memory and retrieval-oriented long-term memory.
4. The planner already persists rich repo-local artifacts:
  - search-tree snapshots,
  - dependency-graph snapshots,
  - candidate rankings,
  - turn records.
5. The repository already enforces that state must remain in-repo and inspectable.

## Planned Work

- Define memory-layer contracts covering:
  - atomic fact records,
  - hypothesis memory entries,
  - execution outcomes,
  - contradictions and invalidations,
  - objective progress markers,
  - retrieval documents and indexes.
- Implement a structured memory store that can ingest:
  - Perceptor memory-staging records,
  - planner turn results,
  - executor artifact references,
  - contradiction and success signals.
- Implement a retrieval-oriented memory view over repo-local artifacts with explicit indexing rules for:
  - observations,
  - extracted facts,
  - tool/skill outcomes,
  - candidate history,
  - relevant historical artifacts.
- Define reconciliation rules between:
  - append-only staged memory,
  - current planner state,
  - contradictions,
  - superseded hypotheses.
- Define planner and Perceptor integration boundaries so:
  - the Perceptor writes memory candidates,
  - the memory layer ingests and indexes them,
  - the planner retrieves relevant memory context during later turns.
- Persist the memory store and retrieval indexes as repo-local artifacts with auditable provenance.
- Add deterministic tests covering:
  - memory ingestion,
  - contradiction handling,
  - retrieval ranking/filtering,
  - planner-side memory lookup integration.

## Boundaries

- No hidden vector DB or external hosted memory service in this phase.
- No mutation that erases provenance of prior observations.
- No coupling that bypasses the planner or Perceptor contracts already in place.

## Deliverables

- Concrete memory models and runtime under `src/dapt/`.
- Repo-local memory store and retrieval-index persistence.
- Planner/Perceptor integration with the new memory layer.
- Deterministic tests for structured and retrieval memory behavior.

## Dependencies

- Builds on `1_3_planner-feedback-and-memory-staging`.
- Should remain compatible with the current planner turn artifacts and future evaluation work.

## Implementation Notes

- Added a concrete `dapt.memory` package with structured memory records, retrieval documents, deterministic queries, and repo-local persistence helpers.
- Integrated planner memory ingestion for:
  - Perceptor memory-staging records,
  - planner-generated hypotheses,
  - executed turn outcomes,
  - contradicted candidates,
  - objective-progress snapshots.
- Persisted per-session memory store and retrieval-index artifacts under `artifacts/memory/`.
- Extended planner synthesis so LLM prompts can include retrieved memory context, while deterministic fallback behavior remains unchanged.
- Added deterministic tests for memory ingestion, contradiction indexing, retrieval ranking/filtering, memory artifact persistence, and planner-side memory prompt integration.

## Audit Request

Please audit the implemented structured memory contracts, retrieval-index rules, and planner/Perceptor memory integration.
