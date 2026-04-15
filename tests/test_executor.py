from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

from dapt.executor import (
    ArtifactStoreLayout,
    ExecutionRequest,
    Executor,
    FieldSpec,
    OutputEnvelope,
    RetryableExecutionError,
    SpecRegistry,
    ToolSpec,
    build_pentest_registry,
    build_pentest_tool_registry,
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


class PentestToolCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.wordlist_path = self.repo_root / "wordlist.txt"
        self.wordlist_path.write_text("admin\nlogin\n", encoding="utf-8")
        self.rules_path = self.repo_root / "zap-rules.conf"
        self.rules_path.write_text("10021\tWARN\tIGNORE\n", encoding="utf-8")
        self.registry = build_pentest_tool_registry()
        self.executor = Executor(
            registry=self.registry,
            artifact_store=ArtifactStoreLayout(repo_root=self.repo_root),
            max_retries=1,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_nmap_missing_target_raises_schema_validation(self) -> None:
        request = ExecutionRequest(
            request_id="nmap-missing-target",
            target_name="nmap",
            action_kind="tool",
            parameters={},
        )

        with self.assertRaisesRegex(Exception, "Missing required parameter: target"):
            self.executor.execute(request)

    def test_ffuf_validator_rejects_missing_fuzz_marker(self) -> None:
        request = ExecutionRequest(
            request_id="ffuf-no-fuzz",
            target_name="ffuf",
            action_kind="tool",
            parameters={
                "target_url": "https://example.test/admin",
                "wordlist_path": str(self.wordlist_path),
            },
        )

        with patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/ffuf"):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "failed")
        self.assertIn("must include the FUZZ marker", result.error_message or "")

    def test_gobuster_precondition_failure_for_missing_wordlist(self) -> None:
        request = ExecutionRequest(
            request_id="gobuster-missing-wordlist",
            target_name="gobuster",
            action_kind="tool",
            parameters={
                "target_url": "https://example.test",
                "wordlist_path": str(self.repo_root / "missing.txt"),
            },
        )

        with patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/gobuster"):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "failed")
        self.assertIn("File does not exist", result.error_message or "")

    def test_nmap_command_assembly_and_parser(self) -> None:
        request = ExecutionRequest(
            request_id="nmap-success",
            target_name="nmap",
            action_kind="tool",
            parameters={
                "target": "scanme.nmap.org",
                "ports": "22,80",
                "scripts": "default",
            },
        )
        stdout = "\n".join(
            [
                "Nmap scan report for scanme.nmap.org",
                "PORT   STATE SERVICE VERSION",
                "22/tcp open  ssh     OpenSSH 8.9p1 Ubuntu",
                "80/tcp open  http    nginx 1.24.0",
            ]
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/nmap"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(args=["nmap"], returncode=0, stdout=stdout, stderr=""),
            ) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.effects["open_port_count"], 2)
        self.assertEqual(result.effects["open_ports"][0]["port"], 22)
        command = run_mock.call_args.args[0]
        self.assertIn("-sV", command)
        self.assertIn("-p", command)
        self.assertIn("--script", command)

    def test_gobuster_command_assembly_and_parser(self) -> None:
        request = ExecutionRequest(
            request_id="gobuster-success",
            target_name="gobuster",
            action_kind="tool",
            parameters={
                "target_url": "https://example.test",
                "wordlist_path": str(self.wordlist_path),
                "extensions": ["php", "txt"],
                "status_codes": [200, 204],
            },
        )
        stdout = "\n".join(
            [
                "/admin (Status: 200) [Size: 123]",
                "/health (Status: 204) [Size: 0]",
            ]
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/gobuster"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(args=["gobuster"], returncode=0, stdout=stdout, stderr=""),
            ) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.effects["finding_count"], 2)
        command = run_mock.call_args.args[0]
        self.assertIn("-x", command)
        self.assertIn("php,txt", command)
        self.assertIn("-s", command)
        self.assertIn("200,204", command)

    def test_ffuf_command_assembly_parser_and_artifacts(self) -> None:
        request = ExecutionRequest(
            request_id="ffuf-success",
            target_name="ffuf",
            action_kind="tool",
            parameters={
                "target_url": "https://example.test/FUZZ",
                "wordlist_path": str(self.wordlist_path),
                "match_codes": [200, 302],
                "follow_redirects": True,
            },
        )
        stdout = "\n".join(
            [
                '{"input":{"FUZZ":"admin"},"status":200,"length":512,"words":40,"url":"https://example.test/admin"}',
                '{"input":{"FUZZ":"login"},"status":302,"length":0,"words":0,"url":"https://example.test/login"}',
            ]
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/ffuf"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(args=["ffuf"], returncode=0, stdout=stdout, stderr=""),
            ) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.effects["result_count"], 2)
        command = run_mock.call_args.args[0]
        self.assertIn("-json", command)
        self.assertIn("-mc", command)
        self.assertIn("-r", command)
        artifact_paths = [self.repo_root / artifact.relative_path for artifact in result.artifacts]
        for artifact_path in artifact_paths:
            self.assertTrue(artifact_path.exists())

    def test_sqlmap_parser_detects_vulnerability_and_dbms(self) -> None:
        request = ExecutionRequest(
            request_id="sqlmap-success",
            target_name="sqlmap",
            action_kind="tool",
            parameters={
                "target_url": "https://example.test/item?id=1",
                "technique": "BEU",
                "level": 3,
                "risk": 2,
            },
        )
        stdout = "\n".join(
            [
                "[INFO] parameter 'id' appears to be injectable",
                "[INFO] sql injection vulnerability has been detected",
                "back-end DBMS: PostgreSQL",
                "Type: boolean-based blind",
            ]
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/sqlmap"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(args=["sqlmap"], returncode=0, stdout=stdout, stderr=""),
            ) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.effects["vulnerable"])
        self.assertEqual(result.effects["dbms"], "PostgreSQL")
        command = run_mock.call_args.args[0]
        self.assertIn("--technique", command)
        self.assertIn("--batch", command)

    def test_zap_parser_counts_alert_prefixes(self) -> None:
        request = ExecutionRequest(
            request_id="zap-success",
            target_name="zap-baseline",
            action_kind="tool",
            parameters={
                "target_url": "https://example.test",
                "rules_file_path": str(self.rules_path),
            },
        )
        stdout = "\n".join(
            [
                "PASS: Cookie No HttpOnly Flag [10010]",
                "WARN-NEW: X-Frame-Options Header Not Set [10020] x 1",
                "INFO: Scan completed",
            ]
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/zap-baseline.py"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(args=["zap-baseline.py"], returncode=0, stdout=stdout, stderr=""),
            ) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.effects["alert_counts"]["warn"], 1)
        self.assertEqual(result.effects["alert_counts"]["pass"], 1)
        command = run_mock.call_args.args[0]
        self.assertIn("-c", command)
        self.assertIn(str(self.rules_path), command)

    def test_cli_timeout_is_retryable_and_succeeds_after_retry(self) -> None:
        request = ExecutionRequest(
            request_id="nmap-retry",
            target_name="nmap",
            action_kind="tool",
            parameters={"target": "scanme.nmap.org"},
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/nmap"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                side_effect=[
                    TimeoutExpired(cmd=["nmap"], timeout=300),
                    CompletedProcess(
                        args=["nmap"],
                        returncode=0,
                        stdout="Nmap scan report for scanme.nmap.org\n80/tcp open http nginx",
                        stderr="",
                    ),
                ],
            ),
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.attempts, 2)


class PentestWebSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.wordlist_path = self.repo_root / "wordlist.txt"
        self.wordlist_path.write_text("admin\nhealth\n", encoding="utf-8")
        self.rules_path = self.repo_root / "zap-rules.conf"
        self.rules_path.write_text("10020\tWARN\tIGNORE\n", encoding="utf-8")
        self.registry = build_pentest_registry()
        self.executor = Executor(
            registry=self.registry,
            artifact_store=ArtifactStoreLayout(repo_root=self.repo_root),
            max_retries=1,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_service_enumeration_requires_target_host_context(self) -> None:
        request = ExecutionRequest(
            request_id="service-enum-missing-context",
            target_name="service-enumeration",
            action_kind="skill",
            parameters={},
        )

        result = self.executor.execute(request)

        self.assertEqual(result.status, "failed")
        self.assertIn("missing required context state: target_host", result.error_message or "")

    def test_web_surface_mapping_runs_steps_in_order_and_aggregates_effects(self) -> None:
        request = ExecutionRequest(
            request_id="web-surface-success",
            target_name="web-surface-mapping",
            action_kind="skill",
            parameters={"rules_file_path": str(self.rules_path), "minutes": 2},
            context={
                "target_host": "scanme.nmap.org",
                "target_url": "https://example.test",
            },
        )

        def fake_run(command, **_kwargs):
            if command[0] == "nmap":
                return CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout=(
                        "Nmap scan report for scanme.nmap.org\n"
                        "80/tcp open  http  nginx 1.24.0\n"
                        "443/tcp open https nginx 1.24.0"
                    ),
                    stderr="",
                )
            if command[0] == "zap-baseline.py":
                return CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout="WARN-NEW: X-Frame-Options Header Not Set [10020] x 1\nPASS: done",
                    stderr="",
                )
            raise AssertionError(f"Unexpected command: {command}")

        with (
            patch("dapt.executor.pentest.cli.shutil.which", side_effect=lambda executable: f"/usr/bin/{executable}"),
            patch("dapt.executor.pentest.cli.subprocess.run", side_effect=fake_run) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.effects["steps_run"], ["discover-http-services", "baseline-web-scan"])
        self.assertTrue(result.effects["http_exposed"])
        self.assertEqual(result.effects["zap_alert_counts"]["warn"], 1)
        executed_tools = [call.args[0][0] for call in run_mock.call_args_list]
        self.assertEqual(executed_tools, ["nmap", "zap-baseline.py"])

    def test_content_discovery_falls_back_from_gobuster_to_ffuf(self) -> None:
        request = ExecutionRequest(
            request_id="content-fallback",
            target_name="content-discovery",
            action_kind="skill",
            parameters={"wordlist_path": str(self.wordlist_path)},
            context={"target_url": "https://example.test"},
        )

        def fake_run(command, **_kwargs):
            if command[0] == "gobuster":
                return CompletedProcess(
                    args=command,
                    returncode=1,
                    stdout="",
                    stderr="transient gobuster failure",
                )
            if command[0] == "ffuf":
                return CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout=(
                        '{"input":{"FUZZ":"admin"},"status":200,"length":321,"words":12,'
                        '"url":"https://example.test/admin"}'
                    ),
                    stderr="",
                )
            raise AssertionError(f"Unexpected command: {command}")

        with (
            patch("dapt.executor.pentest.cli.shutil.which", side_effect=lambda executable: f"/usr/bin/{executable}"),
            patch("dapt.executor.pentest.cli.subprocess.run", side_effect=fake_run) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.effects["fallback_used"])
        self.assertEqual(result.effects["selected_tool"], "ffuf")
        self.assertEqual(result.effects["finding_count"], 1)
        executed_tools = [call.args[0][0] for call in run_mock.call_args_list]
        self.assertEqual(executed_tools, ["gobuster", "ffuf"])

    def test_content_discovery_stops_when_fallback_is_disabled(self) -> None:
        request = ExecutionRequest(
            request_id="content-stop",
            target_name="content-discovery",
            action_kind="skill",
            parameters={
                "wordlist_path": str(self.wordlist_path),
                "allow_fallback": False,
            },
            context={"target_url": "https://example.test"},
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", side_effect=lambda executable: f"/usr/bin/{executable}"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(
                    args=["gobuster"],
                    returncode=1,
                    stdout="",
                    stderr="permanent gobuster failure",
                ),
            ) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertFalse(result.effects["fallback_used"])
        self.assertEqual(result.effects["selected_tool"], None)
        self.assertEqual(len(run_mock.call_args_list), 1)

    def test_web_surface_mapping_stop_policy_propagates_failed_primary_step(self) -> None:
        request = ExecutionRequest(
            request_id="web-surface-stop",
            target_name="web-surface-mapping",
            action_kind="skill",
            parameters={},
            context={
                "target_host": "scanme.nmap.org",
                "target_url": "https://example.test",
            },
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", side_effect=lambda executable: f"/usr/bin/{executable}"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(
                    args=["nmap"],
                    returncode=1,
                    stdout="",
                    stderr="nmap failed",
                ),
            ) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "failed")
        self.assertIn("nmap failed", result.error_message or "")
        self.assertEqual(len(run_mock.call_args_list), 1)

    def test_sqli_verification_aggregates_sqlmap_result(self) -> None:
        request = ExecutionRequest(
            request_id="sqli-success",
            target_name="sqli-verification",
            action_kind="skill",
            parameters={"technique": "BEU", "level": 2, "risk": 2},
            context={"target_url": "https://example.test/item?id=1"},
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", side_effect=lambda executable: f"/usr/bin/{executable}"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(
                    args=["sqlmap"],
                    returncode=0,
                    stdout=(
                        "[INFO] parameter 'id' appears to be injectable\n"
                        "[INFO] sql injection vulnerability has been detected\n"
                        "back-end DBMS: MySQL\n"
                        "Type: boolean-based blind"
                    ),
                    stderr="",
                ),
            ),
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.effects["vulnerable"])
        self.assertEqual(result.effects["dbms"], "MySQL")


class PentestCredentialCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.usernames_path = self.repo_root / "users.txt"
        self.usernames_path.write_text("alice\nbob\n", encoding="utf-8")
        self.passwords_path = self.repo_root / "passwords.txt"
        self.passwords_path.write_text("Spring2024!\n", encoding="utf-8")
        self.hashes_path = self.repo_root / "hashes.txt"
        self.hashes_path.write_text("alice:$krb5asrep$23$alice@test.local:deadbeef\n", encoding="utf-8")
        self.registry = build_pentest_tool_registry()
        self.executor = Executor(
            registry=self.registry,
            artifact_store=ArtifactStoreLayout(repo_root=self.repo_root),
            max_retries=1,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_hydra_rejects_multiple_password_sources(self) -> None:
        request = ExecutionRequest(
            request_id="hydra-bad-secret",
            target_name="hydra",
            action_kind="tool",
            parameters={
                "target_host": "10.0.0.10",
                "service": "ssh",
                "port": 22,
                "username_list_path": str(self.usernames_path),
                "password": "Spring2024!",
                "password_list_path": str(self.passwords_path),
            },
        )

        with patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/hydra"):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "failed")
        self.assertIn("exactly one of 'password' or 'password_list_path'", result.error_message or "")

    def test_netexec_command_assembly_and_parser(self) -> None:
        request = ExecutionRequest(
            request_id="netexec-success",
            target_name="netexec",
            action_kind="tool",
            parameters={
                "protocol": "smb",
                "target_host": "10.0.0.15",
                "username": "alice",
                "password": "Spring2024!",
                "domain": "test.local",
            },
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/netexec"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(
                    args=["netexec"],
                    returncode=0,
                    stdout="SMB 10.0.0.15 445 HOST [*] Windows 10\nSMB 10.0.0.15 445 HOST [+] test.local\\alice:Spring2024!",
                    stderr="",
                ),
            ) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.effects["authenticated"])
        command = run_mock.call_args.args[0]
        self.assertIn("smb", command)
        self.assertIn("-d", command)

    def test_impacket_getnpusers_parses_hash_lines(self) -> None:
        request = ExecutionRequest(
            request_id="getnpusers-success",
            target_name="impacket-getnpusers",
            action_kind="tool",
            parameters={
                "domain": "test.local",
                "dc_host": "10.0.0.20",
                "usernames_file_path": str(self.usernames_path),
            },
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/GetNPUsers.py"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(
                    args=["GetNPUsers.py"],
                    returncode=0,
                    stdout="$krb5asrep$23$alice@test.local:deadbeef",
                    stderr="",
                ),
            ),
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.effects["hash_count"], 1)

    def test_linpeas_persists_nontrivial_output_artifacts(self) -> None:
        request = ExecutionRequest(
            request_id="linpeas-success",
            target_name="linpeas",
            action_kind="tool",
            parameters={},
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", return_value="/usr/bin/linpeas.sh"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(
                    args=["linpeas.sh"],
                    returncode=0,
                    stdout="Interesting writable service\nCVE-2024-0001 candidate\nPassword found in config",
                    stderr="",
                ),
            ),
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertGreaterEqual(result.effects["finding_count"], 2)
        artifact_paths = [self.repo_root / artifact.relative_path for artifact in result.artifacts]
        for artifact_path in artifact_paths:
            self.assertTrue(artifact_path.exists())


class PentestCredentialSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.usernames_path = self.repo_root / "users.txt"
        self.usernames_path.write_text("alice\nbob\n", encoding="utf-8")
        self.registry = build_pentest_registry()
        self.executor = Executor(
            registry=self.registry,
            artifact_store=ArtifactStoreLayout(repo_root=self.repo_root),
            max_retries=1,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_password_spray_validation_requires_username_list_context(self) -> None:
        request = ExecutionRequest(
            request_id="spray-missing-context",
            target_name="password-spray-validation",
            action_kind="skill",
            parameters={"password": "Spring2024!"},
            context={"target_host": "10.0.0.10"},
        )

        result = self.executor.execute(request)

        self.assertEqual(result.status, "failed")
        self.assertIn("username_list_path", result.error_message or "")

    def test_credential_reuse_check_runs_netexec_then_evil_winrm(self) -> None:
        request = ExecutionRequest(
            request_id="cred-reuse-success",
            target_name="credential-reuse-check",
            action_kind="skill",
            parameters={"protocol": "winrm", "password": "Spring2024!", "domain": "test.local"},
            context={"target_host": "10.0.0.30", "username": "alice"},
        )

        def fake_run(command, **_kwargs):
            if command[0] == "netexec":
                return CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout="WINRM 10.0.0.30 5985 HOST [+] test.local\\alice:Spring2024!",
                    stderr="",
                )
            if command[0] == "evil-winrm":
                return CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout="Evil-WinRM shell v3.5\n*Evil-WinRM* PS C:\\Users\\alice> whoami",
                    stderr="",
                )
            raise AssertionError(f"Unexpected command: {command}")

        with (
            patch("dapt.executor.pentest.cli.shutil.which", side_effect=lambda executable: f"/usr/bin/{executable}"),
            patch("dapt.executor.pentest.cli.subprocess.run", side_effect=fake_run) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.effects["authenticated"])
        self.assertTrue(result.effects["winrm_connected"])
        self.assertEqual([call.args[0][0] for call in run_mock.call_args_list], ["netexec", "evil-winrm"])

    def test_asrep_roast_collection_aggregates_hashes(self) -> None:
        request = ExecutionRequest(
            request_id="asrep-success",
            target_name="asrep-roast-collection",
            action_kind="skill",
            parameters={},
            context={
                "domain": "test.local",
                "dc_host": "10.0.0.20",
                "usernames_file_path": str(self.usernames_path),
            },
        )

        def fake_run(command, **_kwargs):
            if command[0] == "kerbrute":
                return CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout="VALID USERNAME: alice@test.local",
                    stderr="",
                )
            if command[0] == "GetNPUsers.py":
                return CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout="$krb5asrep$23$alice@test.local:deadbeef",
                    stderr="",
                )
            raise AssertionError(f"Unexpected command: {command}")

        with (
            patch("dapt.executor.pentest.cli.shutil.which", side_effect=lambda executable: f"/usr/bin/{executable}"),
            patch("dapt.executor.pentest.cli.subprocess.run", side_effect=fake_run),
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.effects["hash_count"], 1)

    def test_kerberoast_collection_propagates_validation_failure(self) -> None:
        request = ExecutionRequest(
            request_id="kerberoast-failure",
            target_name="kerberoast-collection",
            action_kind="skill",
            parameters={"password": "WrongPassword!"},
            context={
                "domain": "test.local",
                "dc_host": "10.0.0.20",
                "username": "alice",
            },
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", side_effect=lambda executable: f"/usr/bin/{executable}"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(
                    args=["netexec"],
                    returncode=1,
                    stdout="",
                    stderr="ldap auth failed",
                ),
            ) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "failed")
        self.assertIn("ldap auth failed", result.error_message or "")
        self.assertEqual(len(run_mock.call_args_list), 1)

    def test_local_privesc_enum_selects_platform_tool_and_persists_artifacts(self) -> None:
        request = ExecutionRequest(
            request_id="privesc-linux",
            target_name="local-privesc-enum",
            action_kind="skill",
            parameters={},
            context={"platform": "linux"},
        )

        with (
            patch("dapt.executor.pentest.cli.shutil.which", side_effect=lambda executable: f"/usr/bin/{executable}"),
            patch(
                "dapt.executor.pentest.cli.subprocess.run",
                return_value=CompletedProcess(
                    args=["linpeas.sh"],
                    returncode=0,
                    stdout="Interesting writable service\nPassword found in config",
                    stderr="",
                ),
            ) as run_mock,
        ):
            result = self.executor.execute(request)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.effects["selected_tool"], "linpeas")
        self.assertEqual(len(run_mock.call_args_list), 1)
        artifact_paths = [self.repo_root / artifact.relative_path for artifact in result.artifacts]
        for artifact_path in artifact_paths:
            self.assertTrue(artifact_path.exists())
