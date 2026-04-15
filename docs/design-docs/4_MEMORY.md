# Memory

The memory layer is repo-local, planner-owned state built on top of Perceptor memory staging.

## Responsibilities

- Persist structured memory records for:
  - facts,
  - hypotheses,
  - execution outcomes,
  - contradictions,
  - objective progress.
- Maintain a deterministic retrieval index over those records.
- Preserve provenance back to planner nodes, request ids, candidate ids, and artifact paths.

## Current Runtime

- `src/dapt/memory/models.py` defines structured memory records, retrieval documents, queries, and search hits.
- `src/dapt/memory/runtime.py` provides session-scoped ingestion and deterministic retrieval ranking.
- `src/dapt/memory/storage.py` persists:
  - `artifacts/memory/<session-target>/store.json`
  - `artifacts/memory/<session-target>/retrieval-index.json`

## Integration Boundary

- The Perceptor still emits append-only `MemoryStagingRecord` values.
- The planner-owned memory layer ingests those staged records plus planner hypotheses, outcomes, contradictions, and objective progress.
- Planner-side LLM synthesis may read retrieval hits as prompt context, but memory remains fully inspectable in-repo.

## Sub-Plans

> Naming Criteria: `4_X_<plan-name>`
