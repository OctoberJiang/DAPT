from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dapt.executor import ExecutionResult, OutputEnvelope, build_pentest_registry
from dapt.memory import MemoryQuery, MemoryStore
from dapt.perceptor import EvidenceRecord, FakeConversationLLM, MemoryStagingRecord, Perceptor, PerceptorArtifactStore
from dapt.planner import AttackDependencyGraph, BootstrapPolicy, CandidateSynthesizer, Planner, PlannerArtifactStore, SearchTreeState
from dapt.knowledge import load_knowledge_manifest


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


class _FakePlannerLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def complete(self, *, config, system_prompt: str, user_prompt: str) -> str:
        self.calls.append(user_prompt)
        return self.responses.pop(0)


class MemoryStoreTests(unittest.TestCase):
    def test_memory_store_indexes_and_retrieves_records(self) -> None:
        store = MemoryStore(session_id="sess-1", target_name="example.test")
        store.ingest_memory_staging(
            MemoryStagingRecord(
                request_id="req-1",
                planner_node_id="obs-0001",
                observation="Found FLAG{demo} on /admin",
                evidence=EvidenceRecord(urls=("https://example.test/admin",), file_paths=("/admin",)),
            )
        )
        store.add_record(
            kind="hypothesis",
            summary="Probe admin panel",
            content="The discovered /admin path is worth testing.",
            source_key="candidate:cand-1",
            tags=("hypothesis", "admin"),
            candidate_id="cand-1",
        )

        hits = store.search(MemoryQuery(goal="admin flag", limit=5))
        filtered = store.search(MemoryQuery(goal="admin", kinds=("hypothesis",), limit=5))

        self.assertEqual(len(store.records), 2)
        self.assertTrue(hits)
        self.assertEqual(hits[0].kind, "fact")
        self.assertEqual(filtered[0].kind, "hypothesis")

    def test_contradictions_are_indexed_without_erasing_history(self) -> None:
        store = MemoryStore(session_id="sess-2", target_name="example.test")
        graph = AttackDependencyGraph(session_id="sess-2", target_name="example.test")
        graph.ingest_observation(observation_node_id="obs-1", contradicted_conditions=("service:ssh",))
        candidate = graph.register_candidate(
            hypothesis_node_id="hyp-1",
            summary="Attempt SSH login",
            prerequisites=("service:ssh",),
            effects=("access:shell",),
        )

        records = store.ingest_contradictions(graph=graph)

        self.assertEqual(candidate.status, "contradicted")
        self.assertEqual(records[0].kind, "contradiction")
        self.assertEqual(records[0].candidate_id, candidate.candidate_id)


class MemoryPlannerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.knowledge_repo_root = Path(__file__).resolve().parents[1]
        self.registry = build_pentest_registry()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_planner_persists_memory_store_and_retrieval_index(self) -> None:
        planner = Planner(
            repo_root=self.repo_root,
            registry=self.registry,
            executor=_FakePlannerExecutor(
                responses=[
                    {
                        "stdout": "Found admin page",
                        "metadata": {"source_type": "web"},
                    }
                ]
            ),  # type: ignore[arg-type]
            perceptor=Perceptor(
                llm=FakeConversationLLM(responses=["yes", "Captured FLAG{demo} from /admin"]),
                artifact_store=PerceptorArtifactStore(repo_root=self.repo_root),
            ),
            artifact_store=PlannerArtifactStore(repo_root=self.repo_root),
            knowledge_manifest=load_knowledge_manifest(self.knowledge_repo_root),
            bootstrap_policy=BootstrapPolicy(repo_root=self.knowledge_repo_root),
            max_turns=2,
        )
        session = planner.start_session(
            session_id="mem-planner-1",
            target_url="https://example.test",
            campaign_mode="ctf",
        )

        planner.run_turn(session)

        store_path = self.repo_root / "artifacts/memory/mem-planner-1-example-test/store.json"
        index_path = self.repo_root / "artifacts/memory/mem-planner-1-example-test/retrieval-index.json"
        store_snapshot = json.loads(store_path.read_text(encoding="utf-8"))

        kinds = {record["kind"] for record in store_snapshot["records"].values()}

        self.assertTrue(store_path.exists())
        self.assertTrue(index_path.exists())
        self.assertIn("fact", kinds)
        self.assertIn("hypothesis", kinds)
        self.assertIn("outcome", kinds)
        self.assertIn("objective", kinds)

    def test_candidate_synthesizer_prompt_includes_memory_hits(self) -> None:
        manifest = load_knowledge_manifest(self.knowledge_repo_root)
        store = MemoryStore(session_id="sess-3", target_name="example.test")
        store.add_record(
            kind="fact",
            summary="Observed /admin path",
            content="The /admin path responded with HTTP 200.",
            source_key="fact:admin",
            tags=("admin",),
            evidence_refs=("path:/admin",),
        )
        tree = SearchTreeState.initialize(
            session_id="sess-3",
            target_name="example.test",
            target_summary="https://example.test",
        )
        graph = AttackDependencyGraph(session_id="sess-3", target_name="example.test")
        graph.ingest_observation(
            observation_node_id=tree.root_node_id,
            satisfied_conditions=("state:target-url", "state:target-host"),
        )
        fake_llm = _FakePlannerLLM(
            responses=[
                json.dumps(
                    {
                        "candidates": [
                            {
                                "title": "Map web surface",
                                "hypothesis": "Baseline mapping remains useful.",
                                "action_kind": "skill",
                                "target_name": "web-surface-mapping",
                                "goal": "Confirm the web surface.",
                                "knowledge_doc_ids": ["web-surface-mapping"],
                                "supporting_evidence": ["state:target_url"],
                            }
                        ]
                    }
                )
            ]
        )
        synthesizer = CandidateSynthesizer(
            manifest,
            llm=fake_llm,
            llm_config={
                "provider": "openai",
                "model": "gpt-test",
                "api_base_url": "https://example.invalid/v1",
                "api_key": "secret",
            },
        )

        synthesizer.generate(
            tree=tree,
            graph=graph,
            current_state={"target_url": "https://example.test", "target_host": "example.test"},
            observation=tree.nodes[tree.root_node_id],
            memory_hits=store.search(MemoryQuery(goal="admin", limit=3)),
        )

        self.assertIn('"memory_context"', fake_llm.calls[0])


if __name__ == "__main__":
    unittest.main()
