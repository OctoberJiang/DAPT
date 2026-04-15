# 1_2_reference-aligned-parsing-runtime

## Status

Completed, awaiting user audit before any repository push.

## Goal

Implement the core Perceptor parsing runtime that turns raw executor outputs into compact factual evidence, aligned with the legacy PentestGPT parsing module while adapted to DAPT's executor-artifact boundary.

## Repo Facts

1. The reference parsing module is a prompt-driven, LLM-backed summarization stage rather than a rule-based parser.
2. The reference behavior relies on:
   - source-aware prompt prefixes,
   - newline flattening,
   - fixed-width chunking,
   - persistent conversation state,
   - naive concatenation of chunk summaries.
3. DAPT's raw inputs come from executor artifacts and `ExecutionResult`, not directly from interactive user paste.

## Planned Work

- Define the Perceptor runtime entrypoint that accepts executor-produced raw outputs and artifact references.
- Add a conversation-LLM protocol and parsing-session abstraction compatible with persistent parsing context.
- Implement reference-aligned preprocessing and chunking, with explicit configuration instead of hidden constants.
- Map executor-originated sources into Perceptor parsing modes such as:
  - tool output,
  - web content,
  - analyst or system notes,
  - default fallback.
- Produce concise factual summaries that preserve important fields and values without making planning conclusions.
- Persist enough trace information to make chunking, prompts, and source attribution auditable in-repo.

## Boundaries

- No planner decisions, candidate ranking, or attack recommendations.
- No silent inference beyond factual compression and normalization.
- No dependency on external web sources or hidden prompt state outside the repository-defined runtime.

## Deliverables

- Perceptor parsing runtime and source-aware prompt builder.
- Artifact-to-parsing adapters for executor outputs.
- Repo-local trace or artifact persistence for Perceptor runs.

## Dependencies

- Depends on `1_1_perceptor-contracts-and-artifacts`.
- Should stay aligned with `docs/references/pentestgpt_parsing_module_extracted.py`.
- Should land before `1_3_planner-feedback-and-memory-staging`.

## Completed Work

- Added a Perceptor runtime that consumes executor results and raw artifacts.
- Added a persistent conversation-LLM boundary for reference-aligned parsing sessions.
- Implemented PentestGPT-aligned:
  - session bootstrap prompting,
  - source-aware prefixes,
  - newline flattening,
  - fixed-width chunking,
  - chunk-summary concatenation.
- Added deterministic evidence extraction for URLs, ports, status codes, and file paths to accompany the free-form summary.
- Added repo-local Perceptor trace persistence for later audit.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'`

## Audit Request

Please audit this completed sub-plan before any repository push.
