from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dapt.executor import ExecutionArtifact, ExecutionResult, OutputEnvelope
from dapt.perceptor import FakeConversationLLM, ParsingConfig, Perceptor, PerceptorArtifactStore


class PerceptorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.llm = FakeConversationLLM(responses=["yes", "summary-1", "summary-2", "summary-3"])
        self.perceptor = Perceptor(
            llm=self.llm,
            artifact_store=PerceptorArtifactStore(repo_root=self.repo_root),
            config=ParsingConfig(wrap_width_chars=10),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_source_aware_prompt_uses_web_hint(self) -> None:
        prompt = self.perceptor.build_chunk_prompt(chunk="login page", source="web", chunk_count=1)
        self.assertIn("from web pages", prompt)
        self.assertIn("less than 10.0 words", prompt)

    def test_summarize_with_trace_flattens_newlines_and_chunks(self) -> None:
        summary, trace = self.perceptor.summarize_with_trace(raw_text="alpha\nbeta gamma", source="tool")

        self.assertEqual(summary, "summary-1summary-2")
        self.assertEqual(trace.normalized_text, "alpha beta gamma")
        self.assertEqual(trace.chunks, ("alpha beta", "gamma"))
        self.assertEqual(len(trace.prompts), 2)
        self.assertEqual(len(self.llm.messages), 3)
        self.assertIn("security testing tool", self.llm.messages[1][1])

    def test_perceive_persists_summary_feedback_and_memory_artifacts(self) -> None:
        llm = FakeConversationLLM(responses=["yes", "web-summary"])
        perceptor = Perceptor(
            llm=llm,
            artifact_store=PerceptorArtifactStore(repo_root=self.repo_root),
        )
        executor_artifact = ExecutionArtifact(
            request_id="req-1",
            name="stdout",
            relative_path="artifacts/executor/req-1-demo/stdout.txt",
            media_type="text/plain",
        )
        result = ExecutionResult(
            request_id="req-1",
            target_name="nmap",
            action_kind="tool",
            status="succeeded",
            output=OutputEnvelope(
                stdout="80/tcp open http nginx 1.24.0\nVisit https://example.test/admin (Status: 200)",
                metadata={"source_type": "web", "planner_node_id": "node-7"},
            ),
            artifacts=(executor_artifact,),
            attempts=1,
        )

        perception = perceptor.perceive(result)

        self.assertEqual(perception.summary, "web-summary")
        self.assertEqual(perception.planner_feedback.planner_node_id, "node-7")
        self.assertEqual(perception.planner_feedback.source, "web")
        self.assertEqual(perception.planner_feedback.evidence.urls, ("https://example.test/admin",))
        self.assertEqual(perception.planner_feedback.evidence.ports, (80,))
        self.assertEqual(perception.planner_feedback.evidence.status_codes, (200,))
        self.assertIn("artifacts/executor/req-1-demo/stdout.txt", perception.memory_record.source_artifact_paths)
        self.assertEqual(len(perception.artifacts), 4)
        for artifact in perception.artifacts:
            self.assertTrue((self.repo_root / artifact.relative_path).exists(), artifact.relative_path)

    def test_perceive_reads_text_artifacts_when_output_is_missing(self) -> None:
        artifact_dir = self.repo_root / "artifacts/executor/req-2-gobuster"
        artifact_dir.mkdir(parents=True)
        raw_path = artifact_dir / "attempt-01-gobuster-stdout.txt"
        raw_path.write_text("/admin (Status: 403)\n/login (Status: 200)\n", encoding="utf-8")
        artifact = ExecutionArtifact(
            request_id="req-2",
            name="stdout",
            relative_path=raw_path.relative_to(self.repo_root).as_posix(),
            media_type="text/plain",
        )
        llm = FakeConversationLLM(responses=["yes", "artifact-summary"])
        perceptor = Perceptor(
            llm=llm,
            artifact_store=PerceptorArtifactStore(repo_root=self.repo_root),
        )
        result = ExecutionResult(
            request_id="req-2",
            target_name="gobuster",
            action_kind="tool",
            status="succeeded",
            output=None,
            artifacts=(artifact,),
            attempts=1,
        )

        perception = perceptor.perceive(result, source="tool")

        self.assertEqual(perception.summary, "artifact-summary")
        self.assertEqual(perception.planner_feedback.evidence.status_codes, (200, 403))
        self.assertIn("/admin", perception.planner_feedback.evidence.file_paths)

    def test_perceive_reconstructs_absolute_urls_from_relative_paths(self) -> None:
        llm = FakeConversationLLM(responses=["yes", "dashboard-summary"])
        perceptor = Perceptor(
            llm=llm,
            artifact_store=PerceptorArtifactStore(repo_root=self.repo_root),
        )
        result = ExecutionResult(
            request_id="req-3",
            target_name="content-discovery",
            action_kind="skill",
            status="succeeded",
            output=OutputEnvelope(
                stdout="/dashboard (Status: 302)\n/favicon.ico (Status: 200)\n",
                metadata={
                    "source_type": "tool",
                    "request_target_url": "https://example.test",
                },
            ),
            attempts=1,
        )

        perception = perceptor.perceive(result, source="tool")

        self.assertEqual(
            perception.planner_feedback.evidence.urls,
            ("https://example.test/dashboard", "https://example.test/favicon.ico"),
        )
        self.assertEqual(perception.planner_feedback.evidence.file_paths, ("/dashboard", "/favicon.ico"))

    def test_session_init_is_only_sent_once(self) -> None:
        llm = FakeConversationLLM(responses=["yes", "first", "second"])
        perceptor = Perceptor(
            llm=llm,
            artifact_store=PerceptorArtifactStore(repo_root=self.repo_root),
        )

        perceptor.summarize_with_trace(raw_text="one", source="tool")
        perceptor.summarize_with_trace(raw_text="two", source="tool")

        self.assertEqual(len(llm.messages), 3)
        self.assertEqual(llm.messages[0][0], "perceptor-parsing-session")


if __name__ == "__main__":
    unittest.main()
