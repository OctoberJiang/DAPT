from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dapt.executor import ExecutionResult, OutputEnvelope, build_pentest_registry
from dapt.knowledge import load_knowledge_manifest
from dapt.perceptor import (
    EvidenceRecord,
    FakeConversationLLM,
    Perceptor,
    PerceptorArtifactStore,
    PlannerFeedback,
)
from dapt.planner import (
    AttackDependencyGraph,
    BootstrapPolicy,
    CandidateSynthesizer,
    Planner,
    PlannerArtifactStore,
    PlannerBudgetLimits,
    PlannerLLMCompletion,
    PlannerLLMUsage,
    SearchTreeState,
    enrich_state_from_observation,
    normalize_planner_llm_config,
    state_to_conditions,
)


class SearchTreeStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.tree = SearchTreeState.initialize(
            session_id="sess-1",
            target_name="demo-target",
            target_summary="https://example.test",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_tree_path_and_feedback_ingestion(self) -> None:
        hypothesis = self.tree.add_hypothesis(
            parent_id=self.tree.root_node_id,
            title="Enumerate web surface",
            hypothesis="The HTTP service likely exposes a reachable login or admin path.",
        )
        action = self.tree.add_action(
            parent_id=hypothesis.node_id,
            title="Run gobuster",
            action="Enumerate common directories with gobuster.",
            request_id="req-1",
        )
        feedback = PlannerFeedback(
            request_id="req-1",
            planner_node_id=action.node_id,
            target_name="gobuster",
            action_kind="tool",
            execution_status="succeeded",
            summary="Found /admin with HTTP 200",
            evidence=EvidenceRecord(
                urls=("https://example.test/admin",),
                status_codes=(200,),
                file_paths=("/admin",),
            ),
            source="tool",
            source_artifact_paths=("artifacts/executor/req-1-demo/stdout.txt",),
        )

        observation = self.tree.ingest_planner_feedback(action_node_id=action.node_id, feedback=feedback)
        path = self.tree.path_to_node(observation.node_id)

        self.assertEqual([node.kind for node in path], ["observation", "hypothesis", "action", "observation"])
        self.assertEqual(self.tree.nodes[action.node_id].status, "succeeded")
        self.assertEqual(observation.evidence.file_paths, ("/admin",))
        self.assertEqual(observation.request_id, "req-1")
        self.assertIn("artifacts/executor/req-1-demo/stdout.txt", observation.source_artifact_paths)

    def test_search_tree_persistence_writes_snapshot(self) -> None:
        store = PlannerArtifactStore(repo_root=self.repo_root)
        hypothesis = self.tree.add_hypothesis(
            parent_id=self.tree.root_node_id,
            title="Seed hypothesis",
            hypothesis="Initial hypothesis.",
        )
        artifact = store.persist_search_tree(self.tree)

        snapshot = json.loads((self.repo_root / artifact.relative_path).read_text(encoding="utf-8"))

        self.assertEqual(snapshot["root_node_id"], "obs-0001")
        self.assertIn(hypothesis.node_id, snapshot["nodes"])
        self.assertEqual(snapshot["nodes"][hypothesis.node_id]["kind"], "hypothesis")


class AttackDependencyGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.graph = AttackDependencyGraph(session_id="sess-1", target_name="demo-target")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_gateway_candidate_scores_above_blocked_followup(self) -> None:
        self.graph.ingest_observation(
            observation_node_id="obs-0002",
            satisfied_conditions=("port:80",),
        )
        gateway = self.graph.register_candidate(
            hypothesis_node_id="hyp-0001",
            summary="Enumerate the web root for hidden paths.",
            prerequisites=("port:80",),
            effects=("path:/admin",),
        )
        followup = self.graph.register_candidate(
            hypothesis_node_id="hyp-0002",
            summary="Probe the /admin panel for weak authentication.",
            prerequisites=("path:/admin",),
            effects=("cred:admin",),
        )

        gateway_eval = self.graph.evaluate_candidate(gateway.candidate_id)
        followup_eval = self.graph.evaluate_candidate(followup.candidate_id)
        ranked = self.graph.rank_candidates()

        self.assertEqual(gateway.status, "available")
        self.assertEqual(followup.status, "blocked")
        self.assertEqual(gateway_eval.downstream_unlock_candidates, (followup.candidate_id,))
        self.assertGreater(gateway_eval.dependency_centrality, followup_eval.dependency_centrality)
        self.assertGreater(gateway_eval.final_score, followup_eval.final_score)
        self.assertEqual(ranked[0].candidate_id, gateway.candidate_id)

    def test_contradicted_prerequisite_penalizes_candidate(self) -> None:
        self.graph.ingest_observation(
            observation_node_id="obs-0003",
            contradicted_conditions=("service:ssh",),
        )
        candidate = self.graph.register_candidate(
            hypothesis_node_id="hyp-0003",
            summary="Attempt SSH login with default credentials.",
            prerequisites=("service:ssh",),
            effects=("access:shell",),
        )

        evaluation = self.graph.evaluate_candidate(candidate.candidate_id)

        self.assertEqual(self.graph.candidates[candidate.candidate_id].status, "contradicted")
        self.assertEqual(evaluation.contradicted_prerequisites, ("service:ssh",))
        self.assertEqual(evaluation.contradiction_penalty, 1.0)

    def test_successful_candidate_unlocks_downstream_candidate(self) -> None:
        first = self.graph.register_candidate(
            hypothesis_node_id="hyp-0004",
            summary="Enumerate common web directories.",
            prerequisites=("port:80",),
            effects=("path:/admin",),
        )
        second = self.graph.register_candidate(
            hypothesis_node_id="hyp-0005",
            summary="Inspect the discovered admin panel.",
            prerequisites=("path:/admin",),
            effects=("auth:weak-login",),
        )
        self.graph.ingest_observation(
            observation_node_id="obs-0004",
            satisfied_conditions=("port:80",),
        )

        updated = self.graph.record_action_outcome(
            candidate_id=first.candidate_id,
            action_node_id="act-0001",
            status="succeeded",
        )

        self.assertEqual(updated.status, "succeeded")
        self.assertIn("path:/admin", self.graph.satisfied_conditions)
        self.assertEqual(self.graph.candidates[second.candidate_id].status, "available")

    def test_graph_persistence_writes_snapshot_and_rankings(self) -> None:
        store = PlannerArtifactStore(repo_root=self.repo_root)
        self.graph.ingest_observation(
            observation_node_id="obs-0005",
            satisfied_conditions=("port:443",),
        )
        candidate = self.graph.register_candidate(
            hypothesis_node_id="hyp-0006",
            summary="Enumerate HTTPS content.",
            prerequisites=("port:443",),
            effects=("url:https://example.test",),
        )

        graph_artifact = store.persist_dependency_graph(self.graph)
        rankings_artifact = store.persist_candidate_rankings(self.graph)

        graph_snapshot = json.loads((self.repo_root / graph_artifact.relative_path).read_text(encoding="utf-8"))
        ranking_snapshot = json.loads((self.repo_root / rankings_artifact.relative_path).read_text(encoding="utf-8"))

        self.assertIn(candidate.candidate_id, graph_snapshot["candidates"])
        self.assertEqual(ranking_snapshot["rankings"][0]["candidate_id"], candidate.candidate_id)

class _FakePlannerExecutor:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.requests = []

    def execute(self, request) -> ExecutionResult:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError(f"No fake response prepared for {request.target_name}")
        prepared = self.responses.pop(0)
        expected_target = prepared["target_name"]
        if request.target_name != expected_target:
            raise AssertionError(f"Expected {expected_target}, got {request.target_name}")
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
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def complete(self, *, config, system_prompt: str, user_prompt: str) -> str:
        self.calls.append(
            {
                "provider": config.provider,
                "model": config.model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
        )
        if not self.responses:
            raise AssertionError("No fake planner LLM response prepared")
        return self.responses.pop(0)


class PlannerLLMConfigTests(unittest.TestCase):
    def test_normalize_reads_repo_visible_env_boundary(self) -> None:
        config = normalize_planner_llm_config(
            {"provider": "openai", "api_key_env_var": "CUSTOM_PLANNER_KEY"},
            env={
                "DAPT_PLANNER_MODEL": "gpt-test",
                "DAPT_PLANNER_API_BASE_URL": "https://example.invalid/v1",
                "CUSTOM_PLANNER_KEY": "secret-token",
            },
        )

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.model, "gpt-test")
        self.assertEqual(config.api_base_url, "https://example.invalid/v1")
        self.assertEqual(config.api_key, "secret-token")
        self.assertEqual(config.api_key_env_var, "CUSTOM_PLANNER_KEY")

    def test_normalize_reads_cny_pricing(self) -> None:
        config = normalize_planner_llm_config(
            {
                "provider": "openai",
                "model": "gpt-test",
                "api_base_url": "https://example.invalid/v1",
                "api_key": "secret-token",
                "pricing": {
                    "input_cost_cny_per_1k_tokens": 0.5,
                    "output_cost_cny_per_1k_tokens": 1.5,
                },
            }
        )

        self.assertIsNotNone(config)
        assert config is not None
        self.assertIsNotNone(config.pricing)
        assert config.pricing is not None
        self.assertEqual(config.pricing.input_cost_cny_per_1k_tokens, 0.5)
        self.assertEqual(config.pricing.output_cost_cny_per_1k_tokens, 1.5)


class CandidateSynthesizerLLMTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.manifest = load_knowledge_manifest(self.repo_root)
        self.tree = SearchTreeState.initialize(
            session_id="sess-llm",
            target_name="example.test",
            target_summary="https://example.test",
        )
        self.graph = AttackDependencyGraph(session_id="sess-llm", target_name="example.test")
        self.current_state = {
            "target_url": "https://example.test",
            "target_host": "example.test",
        }
        self.graph.ingest_observation(
            observation_node_id=self.tree.root_node_id,
            satisfied_conditions=("state:target-url", "state:target-host"),
        )

    def _add_action_observation(self, *, title: str, observation: str, evidence: EvidenceRecord):
        hypothesis = self.tree.add_hypothesis(
            parent_id=self.tree.root_node_id,
            title=f"Hypothesis for {title}",
            hypothesis="Trace the observation under test.",
        )
        action = self.tree.add_action(
            parent_id=hypothesis.node_id,
            title=f"Action for {title}",
            action="Collect a deterministic test observation.",
            request_id=f"req-{title.lower().replace(' ', '-')}",
        )
        return self.tree.add_observation(
            parent_id=action.node_id,
            title=title,
            observation=observation,
            evidence=evidence,
        )

    def test_enrich_state_reconstructs_candidate_url_from_discovered_web_path(self) -> None:
        observation = self._add_action_observation(
            title="Dashboard found",
            observation="Discovered /dashboard",
            evidence=EvidenceRecord(
                status_codes=(302,),
                file_paths=("/dashboard",),
            ),
        )

        enriched = enrich_state_from_observation(self.current_state, observation)

        self.assertEqual(enriched["observed_urls"], ["https://example.test/dashboard"])
        self.assertEqual(enriched["sqli_candidate_url"], "https://example.test/dashboard")
        self.assertIn("signal:sqli-candidate", state_to_conditions(enriched))

    def test_enrich_state_ignores_irrelevant_or_non_web_paths_for_sqli_candidates(self) -> None:
        observation = self._add_action_observation(
            title="Irrelevant paths",
            observation="Observed a favicon and a filesystem path",
            evidence=EvidenceRecord(
                status_codes=(200,),
                file_paths=("/etc/passwd", "/favicon.ico"),
            ),
        )

        enriched = enrich_state_from_observation(self.current_state, observation)

        self.assertNotIn("sqli_candidate_url", enriched)
        self.assertNotIn("signal:sqli-candidate", state_to_conditions(enriched))

    def test_generate_emits_executable_sqli_candidate_for_reconstructed_path(self) -> None:
        synthesizer = CandidateSynthesizer(self.manifest)
        observation = self._add_action_observation(
            title="Dashboard found",
            observation="Content discovery found /dashboard after a redirect.",
            evidence=EvidenceRecord(
                status_codes=(302,),
                file_paths=("/dashboard",),
            ),
        )
        enriched_state = enrich_state_from_observation(self.current_state, observation)
        self.graph.ingest_observation(
            observation_node_id=observation.node_id,
            evidence=observation.evidence,
            satisfied_conditions=state_to_conditions(enriched_state),
        )

        result = synthesizer.generate(
            tree=self.tree,
            graph=self.graph,
            current_state=enriched_state,
            observation=observation,
        )

        sqli_candidate = next(
            proposal for proposal in result.proposals if proposal.target_name == "sqli-verification"
        )
        self.assertEqual(result.trace.generation_mode, "fallback")
        self.assertEqual(sqli_candidate.request_context["target_url"], "https://example.test/dashboard")
        self.assertEqual(sqli_candidate.prerequisites, ("state:target-url", "signal:sqli-candidate"))

    def test_ingest_accepts_grounded_llm_candidate_and_persists_metadata(self) -> None:
        synthesizer = CandidateSynthesizer(
            self.manifest,
            llm=_FakePlannerLLM(
                responses=[
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "title": "Map the reachable web surface",
                                    "hypothesis": "The target URL should be mapped before deeper web follow-ups.",
                                    "action_kind": "skill",
                                    "target_name": "web-surface-mapping",
                                    "goal": "Confirm the reachable web surface and collect baseline findings.",
                                    "knowledge_doc_ids": ["web-surface-mapping"],
                                    "supporting_evidence": ["state:target_url"],
                                    "prerequisites": ["state:target-url", "state:target-host"],
                                    "effects": ["effect:web-surface-confirmed"],
                                    "priority": 90,
                                }
                            ]
                        }
                    )
                ]
            ),
            llm_config={
                "provider": "openai",
                "model": "gpt-test",
                "api_base_url": "https://example.invalid/v1",
                "api_key": "secret",
            },
        )

        result = synthesizer.ingest(
            tree=self.tree,
            graph=self.graph,
            current_state=self.current_state,
            observation=self.tree.nodes[self.tree.root_node_id],
        )

        llm_hypotheses = [
            node
            for node in self.tree.nodes.values()
            if node.kind == "hypothesis" and node.metadata.get("generation_mode") == "llm"
        ]

        self.assertEqual(result.trace.generation_mode, "llm+fallback")
        self.assertTrue(llm_hypotheses)
        self.assertEqual(llm_hypotheses[0].metadata["action_target_name"], "web-surface-mapping")
        self.assertEqual(llm_hypotheses[0].metadata["supporting_evidence"], ("state:target_url",))
        self.assertIn("candidate_id", llm_hypotheses[0].metadata)

    def test_generate_falls_back_when_llm_output_is_malformed(self) -> None:
        synthesizer = CandidateSynthesizer(
            self.manifest,
            llm=_FakePlannerLLM(responses=["not-json"]),
            llm_config={
                "provider": "openai",
                "model": "gpt-test",
                "api_base_url": "https://example.invalid/v1",
                "api_key": "secret",
            },
        )

        result = synthesizer.generate(
            tree=self.tree,
            graph=self.graph,
            current_state=self.current_state,
            observation=self.tree.nodes[self.tree.root_node_id],
        )

        self.assertEqual(result.trace.generation_mode, "fallback")
        self.assertEqual(result.trace.fallback_reason, "llm-response-unusable")
        self.assertTrue(result.proposals)
        self.assertTrue(any("JSON object" in issue for issue in result.trace.validation_issues))

    def test_generate_rejects_ungrounded_llm_candidate(self) -> None:
        synthesizer = CandidateSynthesizer(
            self.manifest,
            llm=_FakePlannerLLM(
                responses=[
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "title": "Invented action",
                                    "hypothesis": "Use an unrelated capability.",
                                    "action_kind": "skill",
                                    "target_name": "web-surface-mapping",
                                    "goal": "Run an ungrounded action.",
                                    "knowledge_doc_ids": ["service-enumeration"],
                                    "supporting_evidence": ["state:target_url"],
                                }
                            ]
                        }
                    )
                ]
            ),
            llm_config={
                "provider": "openai",
                "model": "gpt-test",
                "api_base_url": "https://example.invalid/v1",
                "api_key": "secret",
            },
        )

        result = synthesizer.generate(
            tree=self.tree,
            graph=self.graph,
            current_state=self.current_state,
            observation=self.tree.nodes[self.tree.root_node_id],
        )

        self.assertEqual(result.trace.generation_mode, "fallback")
        self.assertTrue(result.proposals)
        self.assertTrue(any("not supported by the selected knowledge docs" in issue for issue in result.trace.validation_issues))

    def test_generate_records_llm_usage_and_cny_cost(self) -> None:
        synthesizer = CandidateSynthesizer(
            self.manifest,
            llm=_FakePlannerLLM(
                responses=[
                    PlannerLLMCompletion(
                        content=json.dumps(
                            {
                                "candidates": [
                                    {
                                        "title": "Map the reachable web surface",
                                        "hypothesis": "The target URL should be mapped before deeper web follow-ups.",
                                        "action_kind": "skill",
                                        "target_name": "web-surface-mapping",
                                        "goal": "Confirm the reachable web surface and collect baseline findings.",
                                        "knowledge_doc_ids": ["web-surface-mapping"],
                                        "supporting_evidence": ["state:target_url"],
                                        "prerequisites": ["state:target-url", "state:target-host"],
                                        "effects": ["effect:web-surface-confirmed"],
                                    }
                                ]
                            }
                        ),
                        usage=PlannerLLMUsage(
                            prompt_tokens=100,
                            completion_tokens=50,
                            total_tokens=150,
                        ),
                    )
                ]
            ),
            llm_config={
                "provider": "openai",
                "model": "gpt-test",
                "api_base_url": "https://example.invalid/v1",
                "api_key": "secret",
                "pricing": {
                    "input_cost_cny_per_1k_tokens": 0.5,
                    "output_cost_cny_per_1k_tokens": 1.5,
                },
            },
        )

        result = synthesizer.generate(
            tree=self.tree,
            graph=self.graph,
            current_state=self.current_state,
            observation=self.tree.nodes[self.tree.root_node_id],
        )

        self.assertEqual(result.trace.llm_prompt_tokens, 100)
        self.assertEqual(result.trace.llm_completion_tokens, 50)
        self.assertEqual(result.trace.llm_total_tokens, 150)
        self.assertAlmostEqual(result.trace.llm_cost_cny or 0.0, 0.125, places=6)

    def test_generate_surfaces_ctf_benchmark_context_in_prompt(self) -> None:
        llm = _FakePlannerLLM(responses=[json.dumps({"candidates": []})])
        synthesizer = CandidateSynthesizer(
            self.manifest,
            llm=llm,
            llm_config={
                "provider": "openai",
                "model": "gpt-test",
                "api_base_url": "https://example.invalid/v1",
                "api_key": "secret",
            },
        )

        synthesizer.generate(
            tree=self.tree,
            graph=self.graph,
            current_state={
                **self.current_state,
                "benchmark_metadata": {
                    "benchmark_id": "XBEN-001-24",
                    "name": "Benchmark Demo",
                    "description": "Example challenge metadata.",
                    "level": 2,
                    "win_condition": "flag",
                    "tags": ["web"],
                },
            },
            observation=self.tree.nodes[self.tree.root_node_id],
        )

        prompt_payload = json.loads(llm.calls[0]["user_prompt"])

        self.assertEqual(prompt_payload["benchmark_context"]["benchmark_id"], "XBEN-001-24")
        self.assertEqual(prompt_payload["benchmark_context"]["description"], "Example challenge metadata.")
        self.assertEqual(prompt_payload["current_state"]["benchmark_metadata"]["name"], "Benchmark Demo")


class PlannerRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.registry = build_pentest_registry()
        self.fake_executor = _FakePlannerExecutor(
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
        )
        self.perceptor = Perceptor(
            llm=FakeConversationLLM(responses=["yes", "mapped-web-surface", "found-admin-paths"]),
            artifact_store=PerceptorArtifactStore(repo_root=self.repo_root),
        )
        self.knowledge_repo_root = Path(__file__).resolve().parents[1]
        self.planner = Planner(
            repo_root=self.repo_root,
            registry=self.registry,
            executor=self.fake_executor,  # type: ignore[arg-type]
            perceptor=self.perceptor,
            artifact_store=PlannerArtifactStore(repo_root=self.repo_root),
            knowledge_manifest=load_knowledge_manifest(self.knowledge_repo_root),
            bootstrap_policy=BootstrapPolicy(repo_root=self.knowledge_repo_root),
            max_turns=4,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_candidate_synthesis_is_grounded_and_deduplicated(self) -> None:
        session = self.planner.start_session(
            session_id="planner-sess-1",
            target_url="https://example.test",
        )

        created = self.planner.synthesize_candidates(session)
        created_again = self.planner.synthesize_candidates(session)

        target_names = {
            session.tree.nodes[candidate.hypothesis_node_id].metadata["action_target_name"]
            for candidate in session.graph.candidates.values()
        }

        self.assertGreaterEqual(created, 2)
        self.assertEqual(created_again, 0)
        self.assertIn("web-surface-mapping", target_names)
        self.assertIn("content-discovery", target_names)

    def test_start_session_bootstraps_repo_wordlist_and_trace(self) -> None:
        session = self.planner.start_session(
            session_id="planner-sess-bootstrap",
            target_url="https://example.test",
        )

        bootstrap_trace = session.tree.nodes[session.tree.root_node_id].metadata["bootstrap_trace_artifact"]

        self.assertEqual(session.current_state["target_host"], "example.test")
        self.assertTrue(session.current_state["wordlist_path"].endswith("docs/references/pentest/wordlists/web-content-common.txt"))
        self.assertTrue(Path(session.current_state["wordlist_path"]).exists())
        self.assertTrue((self.repo_root / bootstrap_trace).exists())

    def test_start_session_keeps_benchmark_metadata_for_ctf_only(self) -> None:
        benchmark_metadata = {
            "benchmark_id": "XBEN-001-24",
            "name": "Benchmark Demo",
            "description": "Recover the flag from the demo service.",
            "level": 2,
            "win_condition": "flag",
            "tags": ["web"],
        }

        ctf_session = self.planner.start_session(
            session_id="planner-sess-ctf-metadata",
            target_url="https://example.test",
            campaign_mode="ctf",
            benchmark_metadata=benchmark_metadata,
        )
        real_world_session = self.planner.start_session(
            session_id="planner-sess-real-metadata",
            target_url="https://example.test",
            campaign_mode="real-world",
            initial_context={"benchmark_metadata": {"name": "should-not-leak"}},
            benchmark_metadata=benchmark_metadata,
        )

        self.assertEqual(ctf_session.current_state["benchmark_metadata"], benchmark_metadata)
        self.assertNotIn("benchmark_metadata", real_world_session.current_state)

    def test_selection_builds_execution_request_for_best_candidate(self) -> None:
        session = self.planner.start_session(
            session_id="planner-sess-2",
            target_url="https://example.test",
        )
        self.planner.synthesize_candidates(session)

        request, record = self.planner.plan_next_action(session)

        self.assertIsNotNone(request)
        self.assertIsNotNone(record)
        self.assertEqual(request.target_name, "web-surface-mapping")
        self.assertEqual(request.action_kind, "skill")
        self.assertEqual(request.planner_node_id, record.action_node_id)
        self.assertIn("target_url", request.context)

    def test_run_executes_multi_turn_web_chain(self) -> None:
        session = self.planner.start_session(
            session_id="planner-sess-3",
            target_url="https://example.test",
            success_conditions=("effect:content-discovered",),
        )

        completed = self.planner.run(session)

        self.assertTrue(completed.completed)
        self.assertEqual(completed.termination_reason, "success-condition-met")
        self.assertEqual(len(completed.turns), 2)
        self.assertEqual(self.fake_executor.requests[0].target_name, "web-surface-mapping")
        self.assertEqual(self.fake_executor.requests[1].target_name, "content-discovery")
        self.assertIn("effect:web-surface-confirmed", completed.graph.satisfied_conditions)
        self.assertIn("effect:content-discovered", completed.graph.satisfied_conditions)
        self.assertTrue((self.repo_root / "artifacts/planner/planner-sess-3-example-test/session.json").exists())
        self.assertTrue((self.repo_root / "artifacts/planner/planner-sess-3-example-test/turn-0001.json").exists())
        self.assertTrue((self.repo_root / "artifacts/planner/planner-sess-3-example-test/bootstrap-obs-0001.json").exists())
        self.assertTrue((self.repo_root / "artifacts/planner/planner-sess-3-example-test/hypothesis-trace-obs-0001.json").exists())
        self.assertTrue((self.repo_root / "artifacts/planner/planner-sess-3-example-test/budget.json").exists())

    def test_budget_limit_stops_after_first_execution(self) -> None:
        planner = Planner(
            repo_root=self.repo_root,
            registry=self.registry,
            executor=_FakePlannerExecutor(
                responses=[
                    {
                        "target_name": "web-surface-mapping",
                        "stdout": "80/tcp open http nginx 1.24.0\nVisit https://example.test/ (Status: 200)",
                        "metadata": {"source_type": "web"},
                    }
                ]
            ),  # type: ignore[arg-type]
            perceptor=self.perceptor,
            artifact_store=PlannerArtifactStore(repo_root=self.repo_root),
            knowledge_manifest=load_knowledge_manifest(self.knowledge_repo_root),
            bootstrap_policy=BootstrapPolicy(repo_root=self.knowledge_repo_root),
            budget_limits=PlannerBudgetLimits(max_tool_calls=1),
            max_turns=4,
        )
        session = planner.start_session(
            session_id="planner-sess-budget-tool",
            target_url="https://example.test",
        )

        record = planner.run_turn(session)
        budget_snapshot = json.loads(
            (self.repo_root / "artifacts/planner/planner-sess-budget-tool-example-test/budget.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(record.status, "executed")
        self.assertTrue(session.completed)
        self.assertEqual(session.termination_reason, "budget-limit-reached")
        self.assertEqual(budget_snapshot["usage"]["tool_calls"], 1)
        self.assertEqual(budget_snapshot["limit_hit"]["limit_name"], "tool_calls")

    def test_budget_limit_stops_before_execution_when_llm_cost_reaches_cap(self) -> None:
        synthesizer = CandidateSynthesizer(
            load_knowledge_manifest(self.knowledge_repo_root),
            llm=_FakePlannerLLM(
                responses=[
                    PlannerLLMCompletion(
                        content=json.dumps(
                            {
                                "candidates": [
                                    {
                                        "title": "Map the reachable web surface",
                                        "hypothesis": "The target URL should be mapped before deeper web follow-ups.",
                                        "action_kind": "skill",
                                        "target_name": "web-surface-mapping",
                                        "goal": "Confirm the reachable web surface and collect baseline findings.",
                                        "knowledge_doc_ids": ["web-surface-mapping"],
                                        "supporting_evidence": ["state:target_url"],
                                        "prerequisites": ["state:target-url", "state:target-host"],
                                        "effects": ["effect:web-surface-confirmed"],
                                    }
                                ]
                            }
                        ),
                        usage=PlannerLLMUsage(
                            prompt_tokens=100,
                            completion_tokens=50,
                            total_tokens=150,
                        ),
                    )
                ]
            ),
            llm_config={
                "provider": "openai",
                "model": "gpt-test",
                "api_base_url": "https://example.invalid/v1",
                "api_key": "secret",
                "pricing": {
                    "input_cost_cny_per_1k_tokens": 0.5,
                    "output_cost_cny_per_1k_tokens": 1.5,
                },
            },
        )
        fake_executor = _FakePlannerExecutor(
            responses=[
                {
                    "target_name": "web-surface-mapping",
                    "stdout": "should-not-run",
                    "metadata": {"source_type": "web"},
                }
            ]
        )
        planner = Planner(
            repo_root=self.repo_root,
            registry=self.registry,
            executor=fake_executor,  # type: ignore[arg-type]
            perceptor=self.perceptor,
            artifact_store=PlannerArtifactStore(repo_root=self.repo_root),
            knowledge_manifest=load_knowledge_manifest(self.knowledge_repo_root),
            synthesizer=synthesizer,
            bootstrap_policy=BootstrapPolicy(repo_root=self.knowledge_repo_root),
            budget_limits=PlannerBudgetLimits(max_llm_cost_cny=0.1),
            max_turns=4,
        )
        session = planner.start_session(
            session_id="planner-sess-budget-llm",
            target_url="https://example.test",
        )

        record = planner.run_turn(session)
        budget_snapshot = json.loads(
            (self.repo_root / "artifacts/planner/planner-sess-budget-llm-example-test/budget.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(record.status, "stopped")
        self.assertEqual(record.termination_reason, "budget-limit-reached")
        self.assertTrue(session.completed)
        self.assertEqual(session.termination_reason, "budget-limit-reached")
        self.assertFalse(fake_executor.requests)
        self.assertAlmostEqual(budget_snapshot["usage"]["llm_cost_cny"], 0.125, places=6)
        self.assertEqual(budget_snapshot["limit_hit"]["limit_name"], "llm_cost_cny")

    def test_ctf_mode_stops_when_flag_is_observed(self) -> None:
        planner = Planner(
            repo_root=self.repo_root,
            registry=self.registry,
            executor=_FakePlannerExecutor(
                responses=[
                    {
                        "target_name": "web-surface-mapping",
                        "stdout": "flag captured",
                        "metadata": {"source_type": "web"},
                    }
                ]
            ),  # type: ignore[arg-type]
            perceptor=Perceptor(
                llm=FakeConversationLLM(responses=["yes", "Captured FLAG{demo} from the target"]),
                artifact_store=PerceptorArtifactStore(repo_root=self.repo_root),
            ),
            artifact_store=PlannerArtifactStore(repo_root=self.repo_root),
            knowledge_manifest=load_knowledge_manifest(self.knowledge_repo_root),
            bootstrap_policy=BootstrapPolicy(repo_root=self.knowledge_repo_root),
            max_turns=2,
        )
        session = planner.start_session(
            session_id="planner-sess-ctf",
            target_url="https://example.test",
            campaign_mode="ctf",
        )

        record = planner.run_turn(session)

        self.assertEqual(record.status, "executed")
        self.assertTrue(session.completed)
        self.assertEqual(session.termination_reason, "objective-met")
        self.assertTrue((self.repo_root / "artifacts/planner/planner-sess-ctf-example-test/objective-progress.json").exists())

    def test_real_world_mode_requires_explicit_root_evidence(self) -> None:
        planner = Planner(
            repo_root=self.repo_root,
            registry=self.registry,
            executor=_FakePlannerExecutor(
                responses=[
                    {
                        "target_name": "web-surface-mapping",
                        "stdout": "shell foothold established",
                        "metadata": {"source_type": "web"},
                    }
                ]
            ),  # type: ignore[arg-type]
            perceptor=Perceptor(
                llm=FakeConversationLLM(responses=["yes", "Obtained a low-priv shell as www-data"]),
                artifact_store=PerceptorArtifactStore(repo_root=self.repo_root),
            ),
            artifact_store=PlannerArtifactStore(repo_root=self.repo_root),
            knowledge_manifest=load_knowledge_manifest(self.knowledge_repo_root),
            bootstrap_policy=BootstrapPolicy(repo_root=self.knowledge_repo_root),
            max_turns=2,
        )
        session = planner.start_session(
            session_id="planner-sess-real",
            target_url="https://example.test",
            initial_context={"local_shell": True, "platform": "linux"},
            campaign_mode="real-world",
        )

        planner.run_turn(session)

        self.assertFalse(session.completed)
        objective_progress = json.loads(
            (self.repo_root / "artifacts/planner/planner-sess-real-example-test/objective-progress.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("shell-access", objective_progress["partial_progress_markers"])

    def test_real_world_mode_stops_when_root_is_observed(self) -> None:
        planner = Planner(
            repo_root=self.repo_root,
            registry=self.registry,
            executor=_FakePlannerExecutor(
                responses=[
                    {
                        "target_name": "web-surface-mapping",
                        "stdout": "privilege escalation complete",
                        "metadata": {"source_type": "web"},
                    }
                ]
            ),  # type: ignore[arg-type]
            perceptor=Perceptor(
                llm=FakeConversationLLM(responses=["yes", "uid=0(root) gid=0(root) groups=0(root)"]),
                artifact_store=PerceptorArtifactStore(repo_root=self.repo_root),
            ),
            artifact_store=PlannerArtifactStore(repo_root=self.repo_root),
            knowledge_manifest=load_knowledge_manifest(self.knowledge_repo_root),
            bootstrap_policy=BootstrapPolicy(repo_root=self.knowledge_repo_root),
            max_turns=2,
        )
        session = planner.start_session(
            session_id="planner-sess-root",
            target_url="https://example.test",
            campaign_mode="real-world",
        )

        planner.run_turn(session)

        self.assertTrue(session.completed)
        self.assertEqual(session.termination_reason, "objective-met")

    def test_objective_mode_keeps_frontier_stop_when_unsatisfied(self) -> None:
        session = self.planner.start_session(
            session_id="planner-sess-frontier",
            target_url="https://example.test",
            campaign_mode="ctf",
        )
        session.processed_observation_ids.add(session.tree.root_node_id)

        request, record = self.planner.plan_next_action(session)

        self.assertIsNone(request)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.termination_reason, "no-actionable-candidates")


if __name__ == "__main__":
    unittest.main()
