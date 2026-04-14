from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dapt.executor import (
    ArtifactStoreLayout,
    ExecutionRequest,
    Executor,
    FieldSpec,
    OutputEnvelope,
    RetryableExecutionError,
    SpecRegistry,
    ToolSpec,
    build_reference_registry,
)


class ExecutorProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.registry = build_reference_registry()
        self.executor = Executor(
            registry=self.registry,
            artifact_store=ArtifactStoreLayout(repo_root=self.repo_root),
            max_retries=1,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_tool_validation_rejects_missing_required_parameter(self) -> None:
        request = ExecutionRequest(
            request_id="missing-command",
            target_name="run-local-command",
            action_kind="tool",
            parameters={},
        )

        with self.assertRaisesRegex(Exception, "Missing required parameter: command"):
            self.executor.execute(request)

    def test_tool_precondition_failure_returns_failed_result(self) -> None:
        request = ExecutionRequest(
            request_id="bad-cwd",
            target_name="run-local-command",
            action_kind="tool",
            parameters={
                "command": ["pwd"],
                "cwd": str(self.repo_root / "does-not-exist"),
            },
        )

        result = self.executor.execute(request)

        self.assertEqual(result.status, "failed")
        self.assertIn("Working directory does not exist", result.error_message or "")
        self.assertGreaterEqual(len(result.artifacts), 3)

    def test_retryable_tool_succeeds_after_retry(self) -> None:
        calls = {"count": 0}

        def flaky_executor(_request: ExecutionRequest) -> OutputEnvelope:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RetryableExecutionError("temporary network hiccup")
            return OutputEnvelope(stdout="recovered", exit_code=0)

        registry = SpecRegistry()
        registry.register_tool(
            ToolSpec(
                name="flaky-tool",
                description="Test-only flaky tool.",
                input_schema=(FieldSpec(name="target", type_name="str", description="target"),),
                executor=flaky_executor,
            )
        )
        executor = Executor(
            registry=registry,
            artifact_store=ArtifactStoreLayout(repo_root=self.repo_root),
            max_retries=1,
        )

        result = executor.execute(
            ExecutionRequest(
                request_id="flaky",
                target_name="flaky-tool",
                action_kind="tool",
                parameters={"target": "demo"},
            )
        )

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.output.stdout, "recovered")
        self.assertEqual(calls["count"], 2)

    def test_artifact_persistence_writes_output_files(self) -> None:
        request = ExecutionRequest(
            request_id="artifact-check",
            target_name="run-local-command",
            action_kind="tool",
            parameters={
                "command": [
                    "python3",
                    "-c",
                    "import sys; print('hello'); print('warn', file=sys.stderr)",
                ]
            },
        )

        result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        artifact_paths = [self.repo_root / artifact.relative_path for artifact in result.artifacts]
        self.assertEqual(len(artifact_paths), 3)
        for artifact_path in artifact_paths:
            self.assertTrue(artifact_path.exists())
        stdout_contents = artifact_paths[0].read_text(encoding="utf-8")
        stderr_contents = artifact_paths[1].read_text(encoding="utf-8")
        self.assertIn("hello", stdout_contents)
        self.assertIn("warn", stderr_contents)

    def test_skill_execution_runs_all_steps(self) -> None:
        request = ExecutionRequest(
            request_id="skill-success",
            target_name="workspace-recon",
            action_kind="skill",
            parameters={"path": str(self.repo_root)},
        )

        result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.effects["step_count"], 2)
        self.assertIn("directory-listing", result.effects["produced_effects"])
        self.assertGreaterEqual(len(result.artifacts), 9)

    def test_skill_failure_propagates_failed_step(self) -> None:
        request = ExecutionRequest(
            request_id="skill-failure",
            target_name="workspace-recon",
            action_kind="skill",
            parameters={"path": str(self.repo_root / "missing-dir")},
        )

        result = self.executor.execute(request)

        self.assertEqual(result.status, "failed")
        self.assertIn("No such file", result.error_message or "")
        self.assertIsNotNone(result.output)
        self.assertGreaterEqual(len(result.artifacts), 9)


if __name__ == "__main__":
    unittest.main()
