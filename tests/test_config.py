from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dapt.config import RuntimeConfigError, load_runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_missing_config_returns_defaults(self) -> None:
        config = load_runtime_config(self.repo_root)

        self.assertEqual(config.config_version, 1)
        self.assertEqual(config.evaluation.benchmark_root, "XBOW-benchmarks/benchmarks")
        self.assertEqual(config.evaluation.max_turns, 10)
        self.assertFalse(config.planner_llm.enabled)
        self.assertIsNone(config.planner_budget.max_tool_calls)

    def test_loads_llm_budget_evaluation_and_report_sections(self) -> None:
        (self.repo_root / "dapt.config.json").write_text(
            json.dumps(
                {
                    "config_version": 1,
                    "planner": {
                        "llm": {
                            "enabled": True,
                            "provider": "openai",
                            "model": "gpt-test",
                            "api_base_url": "https://example.invalid/v1",
                            "api_key_env_var": "CUSTOM_KEY",
                            "temperature": 0.5,
                            "max_output_tokens": 333,
                            "timeout_seconds": 12.5,
                            "extra_headers": {"X-Test": "1"},
                            "pricing": {
                                "input_cost_cny_per_1k_tokens": 0.5,
                                "output_cost_cny_per_1k_tokens": 1.5,
                            },
                        },
                        "budget": {
                            "max_runtime_seconds": 600.0,
                            "max_tool_calls": 9,
                            "max_llm_cost_cny": 3.2,
                        },
                    },
                    "evaluation": {
                        "benchmarks": "1,2",
                        "benchmark_root": "custom-benchmarks",
                        "run_id": "eval-config",
                        "max_turns": 6,
                        "build": False,
                        "bring_up": True,
                        "tear_down": False,
                    },
                    "report": {
                        "session_dir": "artifacts/planner/demo",
                        "format": "json",
                        "output": "tmp/report.json",
                    },
                    "pentest": {
                        "tool_commands": {
                            "sqlmap": ["python3", "tools/sqlmap.py"],
                            "netexec": "nxc",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        config = load_runtime_config(self.repo_root)

        self.assertTrue(config.planner_llm.enabled)
        self.assertEqual(config.planner_llm.provider, "openai")
        self.assertEqual(config.planner_llm.api_key_env_var, "CUSTOM_KEY")
        self.assertEqual(config.planner_llm.extra_headers, {"X-Test": "1"})
        self.assertEqual(config.planner_llm.input_cost_cny_per_1k_tokens, 0.5)
        self.assertEqual(config.planner_budget.max_tool_calls, 9)
        self.assertEqual(config.evaluation.benchmarks, "1,2")
        self.assertEqual(config.evaluation.max_turns, 6)
        self.assertEqual(config.report.report_format, "json")
        self.assertEqual(config.report.output, "tmp/report.json")
        self.assertEqual(config.pentest.tool_commands["sqlmap"], ("python3", "tools/sqlmap.py"))
        self.assertEqual(config.pentest.tool_commands["netexec"], ("nxc",))

    def test_rejects_invalid_shapes(self) -> None:
        (self.repo_root / "dapt.config.json").write_text(
            json.dumps({"planner": {"llm": {"enabled": "yes"}}}),
            encoding="utf-8",
        )

        with self.assertRaises(RuntimeConfigError):
            load_runtime_config(self.repo_root)

    def test_allows_direct_api_key_with_null_env_var(self) -> None:
        (self.repo_root / "dapt.config.json").write_text(
            json.dumps(
                {
                    "planner": {
                        "llm": {
                            "enabled": True,
                            "provider": "deepseek",
                            "model": "deepseek-reasoner",
                            "api_base_url": "https://api.deepseek.com/v1",
                            "api_key": "secret",
                            "api_key_env_var": None,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        config = load_runtime_config(self.repo_root)

        self.assertEqual(config.planner_llm.api_key, "secret")
        self.assertEqual(config.planner_llm.api_key_env_var, "DAPT_PLANNER_API_KEY")

    def test_rejects_invalid_pentest_tool_command_shape(self) -> None:
        (self.repo_root / "dapt.config.json").write_text(
            json.dumps(
                {
                    "pentest": {
                        "tool_commands": {
                            "sqlmap": [],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaises(RuntimeConfigError):
            load_runtime_config(self.repo_root)


if __name__ == "__main__":
    unittest.main()
