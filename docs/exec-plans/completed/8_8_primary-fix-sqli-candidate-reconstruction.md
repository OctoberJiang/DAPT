# 8_8_primary-fix-sqli-candidate-reconstruction

## Status

Completed.

## Goal

Implement the primary fix for the benchmark-01 frontier block by preserving or reconstructing absolute candidate URLs from discovered web paths so the planner can derive an executable SQLi-candidate signal.

This fix should remove the current mismatch where the planner can synthesize `sqli-verification` but cannot satisfy its `signal:sqli-candidate` prerequisite from the available observation data.

## Repo Facts

1. The benchmark-01 trace in `8_7_trace-benchmark-01-frontier-block` confirmed that content discovery currently emits relative findings like `/dashboard` rather than absolute URLs.
2. The Perceptor currently extracts `file_paths` and `urls` only from raw text in `src/dapt/perceptor/runtime.py`; it does not reconstruct URLs from `target_url + file_path`.
3. The planner currently derives `sqli_candidate_url` only from observed URLs containing `?` or `=` in `src/dapt/planner/synthesis.py`.
4. The planner fallback rule for `sqli-verification` currently uses `current_state.get("sqli_candidate_url") or current_state.get("target_url")`, but still requires `signal:sqli-candidate`, which makes the candidate blockable by construction.
5. The primary fix point identified by the trace is the planner/perceptor boundary, not the benchmark config or evaluation runner.

## Planned Work

- Introduce repo-visible URL reconstruction for discovered web paths so planner observations can carry absolute candidate URLs when:
  - the current session already has `target_url`, and
  - an observation contributes relative `file_paths`.
- Update planner state enrichment so it can derive candidate URLs from reconstructed observation URLs or equivalent explicit state, instead of relying only on raw query-string URLs.
- Tighten SQLi-candidate derivation so it remains explicit and auditable:
  - preserve the strongest existing rule for URLs with `?` or `=`,
  - add a bounded path-based candidate rule suitable for benchmark cases like `/dashboard`,
  - avoid promoting arbitrary non-web paths.
- Align `sqli-verification` fallback synthesis with the reachable prerequisite state so the planner does not emit inherently blocked candidates when the SQLi-candidate signal is absent.
- Add deterministic tests covering:
  - URL reconstruction from `target_url` plus discovered relative paths,
  - state enrichment that produces `sqli_candidate_url` and `signal:sqli-candidate`,
  - planner synthesis that yields an executable `sqli-verification` candidate in the benchmark-style path-discovery case,
  - non-web or irrelevant path observations that must not trigger SQLi-candidate state.

## Boundaries

- No benchmark-specific hardcoding for `/dashboard` or benchmark 01 ids.
- No changes to evaluation orchestration unless tests show the planner/perceptor boundary is insufficient by itself.
- No unrelated report-generation or executor catalog work in this slice.
- The secondary `nmap` parsing defect is out of scope for this primary fix unless it blocks verification directly.

## Deliverables

- Repo-local planner/perceptor changes that preserve enough URL context for SQLi-candidate inference.
- Updated planner SQLi-candidate synthesis logic that no longer dead-ends on unreachable prerequisites.
- Regression tests for the benchmark-style path-discovery flow.

## Dependencies

- Builds on `8_7_trace-benchmark-01-frontier-block`.
- Must remain compatible with `6_2_ctf-benchmark-metadata-planner-bootstrap`.

## Completed Work

- Added a shared repo-local web-target helper in `src/dapt/web_targets.py` to:
  - reconstruct absolute HTTP(S) URLs from relative discovered paths using the session target root,
  - keep the strongest SQLi-candidate rule for query-bearing URLs,
  - add a bounded path-based candidate rule for app-like paths such as `/dashboard`,
  - reject obvious filesystem roots and static-resource paths from SQLi-candidate promotion.
- Updated `src/dapt/executor/runtime.py` so execution outputs preserve repo-visible `request_target_url` and `request_target_host` metadata when present in planner context.
- Updated `src/dapt/perceptor/runtime.py` to:
  - reconstruct absolute URLs from relative path findings when `request_target_url` is available,
  - tighten raw `file_paths` extraction so URL hosts and `80/tcp` style fragments do not become fake discovered paths.
- Updated `src/dapt/planner/synthesis.py` to:
  - enrich `observed_urls` from reconstructed path URLs,
  - derive `sqli_candidate_url` from either explicit query-string URLs or bounded reconstructed path candidates,
  - surface SQLi retrieval keywords when a candidate URL is derivable,
  - emit fallback `sqli-verification` only when `sqli_candidate_url` is actually present,
  - pass the candidate URL into `request_context["target_url"]` so the executor verifies the intended endpoint instead of the session root,
  - include `request_context` in deterministic candidate deduplication/signature logic.
- Added deterministic regression coverage in:
  - `tests/test_perceptor.py` for relative-path URL reconstruction,
  - `tests/test_planner.py` for state enrichment, non-web-path rejection, and executable SQLi-candidate synthesis from a benchmark-style `/dashboard` observation,
  - `tests/test_executor.py` for executor-side propagation of `request_target_url`.
- Verified the repo with:
  - `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_perceptor tests.test_planner tests.test_executor`
  - `/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'"`

## Outcome

- The planner now preserves enough web-path context to derive a reachable `signal:sqli-candidate` from benchmark-style relative findings.
- Fallback `sqli-verification` no longer dead-ends on an unreachable prerequisite, and when it is emitted it targets the reconstructed candidate URL rather than the root URL.
- The Perceptor no longer fabricates candidate paths from URL hosts or `nmap` port notation, which prevented false-positive SQLi candidates during normal web-surface observations.
