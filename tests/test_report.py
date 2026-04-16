from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dapt.executor import ExecutionResult, OutputEnvelope, build_pentest_registry
from dapt.knowledge import load_knowledge_manifest
from dapt.perceptor import FakeConversationLLM, Perceptor, PerceptorArtifactStore
from dapt.planner import BootstrapPolicy, Planner, PlannerArtifactStore
from dapt.report import assemble_report, write_report
from dapt.report.cli import main as report_main


class _FakePlannerExecutor:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)

    def execute(self, request) -> ExecutionResult:
        prepared = self.responses.pop(0)
        return ExecutionResult(
            request_id=request.request_id,
            target_name=request.target_name,
            action_kind=request.action_kind,
            status=prepared.get("status", "succeeded"),
            output=OutputEnvelope(
                stdout=str(prepared.get("stdout", "")),
                stderr=str(prepared.get("stderr", "")),
                metadata=dict(prepared.get("metadata", {})),
            ),
            attempts=1,
        )


class ReportRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.knowledge_repo_root = Path(__file__).resolve().parents[1]
        planner = Planner(
            repo_root=self.repo_root,
            registry=build_pentest_registry(),
            executor=_FakePlannerExecutor(
                responses=[
                    {
                        "target_name": "web-surface-mapping",
                        "stdout": "80/tcp open http nginx 1.24.0\nVisit https://example.test/ (Status: 200)",
                        "metadata": {"source_type": "web"},
                    },
                    {
                        "target_name": "content-discovery",
                        "stdout": "/admin (Status: 200)\n/login (Status: 200)\n",
                        "metadata": {"source_type": "tool"},
                    },
                ]
            ),  # type: ignore[arg-type]
            perceptor=Perceptor(
                llm=FakeConversationLLM(responses=["yes", "mapped-web-surface", "found-admin-paths"]),
                artifact_store=PerceptorArtifactStore(repo_root=self.repo_root),
            ),
            artifact_store=PlannerArtifactStore(repo_root=self.repo_root),
            knowledge_manifest=load_knowledge_manifest(self.knowledge_repo_root),
            bootstrap_policy=BootstrapPolicy(repo_root=self.knowledge_repo_root),
            max_turns=4,
        )
        session = planner.start_session(
            session_id="report-sess-1",
            target_url="https://example.test",
            success_conditions=("effect:content-discovered",),
        )
        planner.run(session)
        self.session_dir = PlannerArtifactStore(repo_root=self.repo_root).session_dir(
            session.session_id,
            session.target_name,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_assemble_report_reads_planner_artifacts(self) -> None:
        report = assemble_report(repo_root=self.repo_root, session_dir=self.session_dir)

        self.assertEqual(report.session_id, "report-sess-1")
        self.assertEqual(report.termination_reason, "success-condition-met")
        self.assertEqual(len(report.findings), 2)
        self.assertEqual(len(report.attack_chain), 2)
        self.assertEqual(report.findings[0].severity, "info")
        self.assertEqual(report.findings[1].severity, "low")

    def test_write_report_supports_json_and_markdown(self) -> None:
        report = assemble_report(repo_root=self.repo_root, session_dir=self.session_dir)

        rendered_json = write_report(repo_root=self.repo_root, report=report, report_format="json")
        rendered_md = write_report(repo_root=self.repo_root, report=report, report_format="markdown")

        self.assertTrue(Path(rendered_json.output_path).exists())
        self.assertTrue(Path(rendered_md.output_path).exists())
        self.assertIn('"session_id": "report-sess-1"', rendered_json.content)
        self.assertIn("# DAPT Report: example.test", rendered_md.content)

    def test_cli_writes_report_to_default_location(self) -> None:
        with (
            patch("dapt.report.cli.Path.cwd", return_value=self.repo_root),
            patch("builtins.print") as print_mock,
        ):
            exit_code = report_main(["--session-dir", str(self.session_dir), "--format", "markdown"])

        output_path = self.repo_root / "artifacts" / "report" / self.session_dir.name / "report.md"

        self.assertEqual(exit_code, 0)
        self.assertTrue(output_path.exists())
        self.assertIn("## Findings", output_path.read_text(encoding="utf-8"))
        print_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
