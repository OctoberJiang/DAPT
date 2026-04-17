# 8_9_rerun-benchmark-01-after-sqli-candidate-fix

## Status

Completed.

## Goal

Rerun XBOW benchmark 01 after the `8_8_primary-fix-sqli-candidate-reconstruction` change and inspect whether the planner now progresses past the former blocked SQLi frontier.

## Repo Facts

1. `python3 -m dapt.evaluation --benchmarks 1` is the repo-visible evaluation entrypoint for benchmark 01.
2. The last documented rerun in `8_6_rerun-benchmark-01-and-inspect-final-output` completed the lifecycle successfully but ended with `termination_reason: frontier-blocked`.
3. `8_8_primary-fix-sqli-candidate-reconstruction` was completed and pushed, and it changed the planner/perceptor path so discovered web paths can now yield a reachable `signal:sqli-candidate`.
4. Prior benchmark reruns in this repo required escalated Docker access because sandbox execution could not access the local Docker daemon socket.
5. The current worktree still contains many unrelated modified and generated files, so this rerun should avoid reverting or folding in unrelated changes.

## Planned Work

- Run benchmark 01 with a fresh post-fix `run_id` in the sandbox first:
  - `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m dapt.evaluation --benchmarks 1 --run-id <fresh-run-id>`
- If sandbox execution fails due to Docker daemon access, rerun the same command with escalated permissions.
- Inspect the resulting evaluation artifacts:
  - `artifacts/evaluation/<run-id>/summary.json`
  - `artifacts/evaluation/<run-id>/benchmark-*.json`
  - the referenced planner session directory under `artifacts/planner/`
- Confirm whether the planner now:
  - emits an executable `sqli-verification` step,
  - advances beyond the former blocked `/dashboard` frontier,
  - or fails/stops for a new reason.
- Record the rerun outcome in this plan and move it to `completed` or `failed`.
- Update `docs/exec-plans/index.md`.
- Commit and push the rerun bookkeeping updates with a concise message.

## Boundaries

- No code changes unless the rerun is blocked by a newly discovered repo-local defect that must be fixed first.
- Do not expose secrets from config or environment.
- Do not revert unrelated local changes or generated artifacts.

## Deliverables

- A fresh benchmark-01 post-fix evaluation artifact set.
- A concise repo-local summary of whether the SQLi-candidate reconstruction fix changed the benchmark outcome.

## Dependencies

- Builds on `8_6_rerun-benchmark-01-and-inspect-final-output`.
- Builds on `8_8_primary-fix-sqli-candidate-reconstruction`.

## Completed Work

- Ran benchmark 01 in the sandbox with:
  - `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m dapt.evaluation --benchmarks 1 --run-id eval-20260417-bench-1-post-8-8-fix`
- Confirmed the sandbox run again failed during lifecycle startup because `docker compose up` could not access `/Users/jyj/.docker/run/docker.sock`.
- Re-ran benchmark 01 with escalated Docker access using:
  - `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m dapt.evaluation --benchmarks 1 --run-id eval-20260417-bench-1-post-8-8-fix-escalated`
- Inspected the resulting post-fix evaluation artifacts:
  - `artifacts/evaluation/eval-20260417-bench-1-post-8-8-fix/summary.json`
  - `artifacts/evaluation/eval-20260417-bench-1-post-8-8-fix-escalated/summary.json`
  - `artifacts/evaluation/eval-20260417-bench-1-post-8-8-fix-escalated/benchmark-xben-001-24.json`
  - `artifacts/planner/eval-20260417-bench-1-post-8-8-fix-escalated-bench-1-127-0-0-1/session.json`
  - `artifacts/planner/eval-20260417-bench-1-post-8-8-fix-escalated-bench-1-127-0-0-1/objective-progress.json`
  - `artifacts/planner/eval-20260417-bench-1-post-8-8-fix-escalated-bench-1-127-0-0-1/hypothesis-trace-obs-0004.json`
  - `artifacts/planner/eval-20260417-bench-1-post-8-8-fix-escalated-bench-1-127-0-0-1/hypothesis-trace-obs-0005.json`
- Confirmed the post-fix planner progressed past the former blocked frontier:
  - content discovery still found `/dashboard`,
  - planner state now recorded `observed_urls=["http://127.0.0.1:51448/dashboard"]`,
  - planner state now recorded `sqli_candidate_url="http://127.0.0.1:51448/dashboard"`,
  - turn 3 executed `sqli-verification` instead of stopping with `frontier-blocked`.
- Confirmed the executed SQLi verification failed because `sqlmap` was unavailable in the environment:
  - `Executable not found on PATH: sqlmap`
  - the skill targeted `request_target_url: "http://127.0.0.1:51448/dashboard"`, which confirms the `8_8` handoff fix was exercised.
- Confirmed the campaign then ran one more fallback step:
  - turn 4 executed `service-enumeration`,
  - turn 5 stopped with `termination_reason: no-actionable-candidates`.
- Confirmed the final escalated benchmark result:
  - lifecycle `build`, `up`, and `down` all succeeded,
  - campaign completed with `turn_count: 5`,
  - final benchmark `status: failed`,
  - `objective_met: false`,
  - `termination_reason: no-actionable-candidates`.
- Confirmed the secondary `nmap` parsing defect remains visible in the service-enumeration metadata:
  - the parsed open-port entries still collapse `3306/tcp` into the `445` record and `51448/tcp http` into the `5432` record.

## Outcome

- The primary `8_8` fix changed benchmark-01 behavior in the intended way:
  - the planner no longer stops on an unreachable SQLi prerequisite,
  - it now reconstructs the `/dashboard` candidate URL and executes `sqli-verification`.
- Benchmark 01 still does not succeed end-to-end.
- The new immediate blocker is executor capability/environmental:
  - `sqlmap` is not available on PATH for the SQLi verification step.
- After the SQLi step failed, the planner exhausted the remaining available fallback and terminated with `no-actionable-candidates` rather than the former `frontier-blocked`.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m dapt.evaluation --benchmarks 1 --run-id eval-20260417-bench-1-post-8-8-fix`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m dapt.evaluation --benchmarks 1 --run-id eval-20260417-bench-1-post-8-8-fix-escalated`
