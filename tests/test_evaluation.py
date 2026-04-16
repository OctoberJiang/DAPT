from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dapt.evaluation import (
    CampaignRunResult,
    EvaluationArtifactStore,
    discover_benchmarks,
    parse_benchmark_selection,
    resolve_selected_benchmarks,
    run_benchmark,
    run_evaluation,
)
from dapt.evaluation.cli import main as evaluation_main
from dapt.evaluation.models import LifecycleCommandResult


def _write_benchmark(root: Path, benchmark_id: str, *, target_url: str) -> None:
    benchmark_dir = root / benchmark_id
    (benchmark_dir / "benchmark").mkdir(parents=True)
    (benchmark_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (benchmark_dir / "benchmark" / "benchmark-config.json").write_text(
        json.dumps(
            {
                "name": f"Benchmark {benchmark_id}",
                "description": "Example challenge",
                "level": 1,
                "win_condition": "flag",
                "tags": ["web"],
            }
        ),
        encoding="utf-8",
    )
    (benchmark_dir / "benchmark" / "dapt-target.json").write_text(
        json.dumps(
            {
                "target_url": target_url,
                "objective_summary": "Capture the benchmark flag.",
                "initial_context": {"target_url": target_url},
            }
        ),
        encoding="utf-8",
    )


class EvaluationRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.benchmark_root = self.repo_root / "benchmarks"
        self.benchmark_root.mkdir()
        _write_benchmark(self.benchmark_root, "001", target_url="http://127.0.0.1:8001")
        _write_benchmark(self.benchmark_root, "002", target_url="http://127.0.0.1:8002")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_parse_selection_supports_all_one_and_list(self) -> None:
        self.assertEqual(parse_benchmark_selection("all").mode, "all")
        single = parse_benchmark_selection("1")
        multiple = parse_benchmark_selection("1,2,2")

        self.assertEqual(single.mode, "one")
        self.assertEqual(single.benchmark_ids, ("1",))
        self.assertEqual(multiple.mode, "many")
        self.assertEqual(multiple.benchmark_ids, ("1", "2"))

    def test_discovery_and_selection_accept_zero_padded_ids(self) -> None:
        specs = discover_benchmarks(self.benchmark_root)
        selected = resolve_selected_benchmarks(specs, parse_benchmark_selection("1,2"))

        self.assertEqual([spec.benchmark_id for spec in selected], ["001", "002"])

    def test_run_benchmark_persists_result_with_teardown(self) -> None:
        spec = discover_benchmarks(self.benchmark_root)[0]

        def fake_command_runner(*, name: str, command: tuple[str, ...], cwd: Path) -> LifecycleCommandResult:
            return LifecycleCommandResult(
                name=name,
                command=command,
                cwd=str(cwd),
                status="succeeded",
                returncode=0,
                stdout=f"{name}-ok",
            )

        def fake_campaign_runner(**kwargs) -> CampaignRunResult:
            return CampaignRunResult(
                session_id="eval-run-bench-1",
                target_name="benchmark-1",
                completed=True,
                termination_reason="objective-met",
                objective_met=True,
                turn_count=3,
                artifact_paths=("artifacts/planner/eval-run-bench-1-benchmark-1",),
            )

        result = run_benchmark(
            repo_root=self.repo_root,
            benchmark=spec,
            run_id="eval-run",
            session_prefix="eval-run-bench",
            command_runner=fake_command_runner,
            campaign_runner=fake_campaign_runner,  # type: ignore[arg-type]
            max_turns=4,
        )
        run_dir = EvaluationArtifactStore(repo_root=self.repo_root).run_dir("eval-run")
        persisted = json.loads((run_dir / "benchmark-001.json").read_text(encoding="utf-8"))

        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.objective_met)
        self.assertEqual(len(result.lifecycle_results), 3)
        self.assertEqual(result.lifecycle_results[-1].name, "down")
        self.assertEqual(persisted["campaign"]["session_id"], "eval-run-bench-1")

    def test_run_evaluation_persists_summary(self) -> None:
        def fake_command_runner(*, name: str, command: tuple[str, ...], cwd: Path) -> LifecycleCommandResult:
            return LifecycleCommandResult(
                name=name,
                command=command,
                cwd=str(cwd),
                status="succeeded",
                returncode=0,
            )

        def fake_campaign_runner(**kwargs) -> CampaignRunResult:
            benchmark = kwargs["benchmark"]
            objective_met = benchmark.benchmark_id == "001"
            return CampaignRunResult(
                session_id=f"session-{benchmark.benchmark_id}",
                target_name=f"target-{benchmark.benchmark_id}",
                completed=True,
                termination_reason="objective-met" if objective_met else "max-turns-reached",
                objective_met=objective_met,
                turn_count=2,
                artifact_paths=(f"artifacts/planner/session-{benchmark.benchmark_id}",),
            )

        summary = run_evaluation(
            repo_root=self.repo_root,
            benchmark_root=self.benchmark_root,
            selection=parse_benchmark_selection("1,2"),
            run_id="eval-suite",
            command_runner=fake_command_runner,
            campaign_runner=fake_campaign_runner,  # type: ignore[arg-type]
            max_turns=5,
        )
        summary_path = EvaluationArtifactStore(repo_root=self.repo_root).run_dir("eval-suite") / "summary.json"
        persisted = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(summary.total_benchmarks, 2)
        self.assertEqual(summary.succeeded, 1)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(persisted["succeeded"], 1)

    def test_cli_prints_summary_path(self) -> None:
        with (
            patch("dapt.evaluation.cli.Path.cwd", return_value=self.repo_root),
            patch("dapt.evaluation.cli.run_evaluation") as run_mock,
            patch("builtins.print") as print_mock,
        ):
            run_mock.return_value = run_evaluation(
                repo_root=self.repo_root,
                benchmark_root=self.benchmark_root,
                selection=parse_benchmark_selection("1"),
                run_id="eval-cli",
                command_runner=lambda **kwargs: LifecycleCommandResult(
                    name=kwargs["name"],
                    command=kwargs["command"],
                    cwd=str(kwargs["cwd"]),
                    status="skipped",
                ),
                campaign_runner=lambda **kwargs: CampaignRunResult(
                    session_id="session-001",
                    target_name="target-001",
                    completed=False,
                    termination_reason="max-turns-reached",
                    objective_met=False,
                    turn_count=0,
                ),
                build=False,
                bring_up=False,
                tear_down=False,
            )

            exit_code = evaluation_main(
                ["--benchmarks", "1", "--benchmark-root", str(self.benchmark_root), "--run-id", "eval-cli"]
            )

        self.assertEqual(exit_code, 0)
        print_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
