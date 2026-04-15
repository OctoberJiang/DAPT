"""Repo-local knowledge retrieval and observation-to-candidate synthesis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha1
from time import perf_counter
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from dapt.knowledge import KnowledgeLookupRequest, KnowledgeManifest
from dapt.knowledge.contracts import KnowledgeDocument
from dapt.memory import MemorySearchHit

from .llm import (
    OpenAICompatiblePlannerLLM,
    PlannerLLMCompletion,
    PlannerLLM,
    PlannerLLMConfig,
    PlannerLLMError,
    normalize_planner_llm_config,
)
from .models import CandidateProposal, KnowledgeHit, PlannerNode
from .runtime import AttackDependencyGraph, SearchTreeState


@dataclass(frozen=True, slots=True)
class _RuleSpec:
    doc_id: str
    action_kind: str
    target_name: str
    title: str


@dataclass(frozen=True, slots=True)
class KnowledgeExcerpt:
    """Prompt-ready knowledge reference for planner hypothesis generation."""

    doc_id: str
    title: str
    kind: str
    path: str
    related_tools: tuple[str, ...]
    related_skills: tuple[str, ...]
    excerpt: str


@dataclass(frozen=True, slots=True)
class HypothesisTrace:
    """Auditable record of one synthesis attempt for a single observation."""

    observation_node_id: str
    generation_mode: str
    provider: str | None
    model: str | None
    prompt: str | None
    raw_response: str | None
    llm_prompt_tokens: int | None
    llm_completion_tokens: int | None
    llm_total_tokens: int | None
    llm_cost_cny: float | None
    llm_latency_seconds: float | None
    parsed_payload: dict[str, Any] | None
    validation_issues: tuple[str, ...]
    fallback_reason: str | None
    knowledge_excerpts: tuple[KnowledgeExcerpt, ...]
    memory_hits: tuple[dict[str, Any], ...]
    proposal_keys: tuple[str, ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "observation_node_id": self.observation_node_id,
            "generation_mode": self.generation_mode,
            "provider": self.provider,
            "model": self.model,
            "prompt": self.prompt,
            "raw_response": self.raw_response,
            "llm_prompt_tokens": self.llm_prompt_tokens,
            "llm_completion_tokens": self.llm_completion_tokens,
            "llm_total_tokens": self.llm_total_tokens,
            "llm_cost_cny": self.llm_cost_cny,
            "llm_latency_seconds": self.llm_latency_seconds,
            "parsed_payload": self.parsed_payload,
            "validation_issues": list(self.validation_issues),
            "fallback_reason": self.fallback_reason,
            "knowledge_excerpts": [
                {
                    "doc_id": excerpt.doc_id,
                    "title": excerpt.title,
                    "kind": excerpt.kind,
                    "path": excerpt.path,
                    "related_tools": list(excerpt.related_tools),
                    "related_skills": list(excerpt.related_skills),
                    "excerpt": excerpt.excerpt,
                }
                for excerpt in self.knowledge_excerpts
            ],
            "memory_hits": list(self.memory_hits),
            "proposal_keys": list(self.proposal_keys),
        }


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """Returned proposals plus the auditable trace that produced them."""

    proposals: tuple[CandidateProposal, ...]
    trace: HypothesisTrace


_RULES: dict[str, _RuleSpec] = {
    "service-enumeration": _RuleSpec(
        doc_id="service-enumeration",
        action_kind="skill",
        target_name="service-enumeration",
        title="Enumerate exposed services",
    ),
    "web-surface-mapping": _RuleSpec(
        doc_id="web-surface-mapping",
        action_kind="skill",
        target_name="web-surface-mapping",
        title="Map the reachable web surface",
    ),
    "content-discovery": _RuleSpec(
        doc_id="content-discovery",
        action_kind="skill",
        target_name="content-discovery",
        title="Enumerate hidden web content",
    ),
    "sqli-verification": _RuleSpec(
        doc_id="sqli-verification",
        action_kind="skill",
        target_name="sqli-verification",
        title="Verify suspected SQL injection",
    ),
    "credential-reuse-check": _RuleSpec(
        doc_id="credential-reuse-check",
        action_kind="skill",
        target_name="credential-reuse-check",
        title="Validate recovered credentials",
    ),
    "asrep-roast-collection": _RuleSpec(
        doc_id="asrep-roast-collection",
        action_kind="skill",
        target_name="asrep-roast-collection",
        title="Collect AS-REP roast hashes",
    ),
    "kerberoast-collection": _RuleSpec(
        doc_id="kerberoast-collection",
        action_kind="skill",
        target_name="kerberoast-collection",
        title="Collect Kerberoast service tickets",
    ),
    "local-privesc-enum": _RuleSpec(
        doc_id="local-privesc-enum",
        action_kind="skill",
        target_name="local-privesc-enum",
        title="Enumerate local privilege-escalation paths",
    ),
}

_SYSTEM_PROMPT = """You are the DAPT planner hypothesis generator.

Use only the provided observation, planner state, dependency-graph state, and repo-local knowledge excerpts.
Do not invent hosts, ports, paths, credentials, or tools that are not present in the prompt.
Return strict JSON with the top-level shape {"candidates": [...]} and no markdown.
Each candidate must reference supplied knowledge_doc_ids and supporting_evidence values from the prompt.
Each candidate must use only action_kind/target_name pairs that are allowed by the supplied knowledge excerpts.
Prefer candidates that are grounded, feasible, and useful for downstream unlocks.
"""


class KnowledgeRetriever:
    """Manifest-backed deterministic retrieval over repo-local pentest knowledge."""

    def __init__(self, manifest: KnowledgeManifest) -> None:
        self.manifest = manifest

    def lookup(self, request: KnowledgeLookupRequest) -> tuple[KnowledgeHit, ...]:
        """Return deterministic ranked knowledge hits for the request."""

        scored: list[KnowledgeHit] = []
        normalized_keywords = {keyword.lower() for keyword in request.keywords}
        candidate_tools = set(request.candidate_tools)
        candidate_skills = set(request.candidate_skills)
        goal_text = request.goal.lower()
        for document in self.manifest.all_documents():
            score = self._score_document(
                document,
                preferred_kind=request.preferred_kind,
                candidate_tools=candidate_tools,
                candidate_skills=candidate_skills,
                keywords=normalized_keywords,
                goal_text=goal_text,
            )
            if score <= 0:
                continue
            scored.append(
                KnowledgeHit(
                    doc_id=document.doc_id,
                    kind=document.kind,
                    title=document.title,
                    path=document.path,
                    keywords=document.keywords,
                    related_tools=document.related_tools,
                    related_skills=document.related_skills,
                    score=score,
                )
            )
        scored.sort(key=lambda hit: (-hit.score, hit.kind, hit.doc_id))
        return tuple(scored)

    def _score_document(
        self,
        document: KnowledgeDocument,
        *,
        preferred_kind: str | None,
        candidate_tools: set[str],
        candidate_skills: set[str],
        keywords: set[str],
        goal_text: str,
    ) -> float:
        score = 0.0
        if preferred_kind and preferred_kind == document.kind:
            score += 3.0
        if candidate_tools:
            score += 2.0 * len(candidate_tools & set(document.related_tools))
        if candidate_skills:
            score += 2.0 * len(candidate_skills & set(document.related_skills))
        doc_terms = {
            document.doc_id.lower(),
            document.title.lower(),
            *(keyword.lower() for keyword in document.keywords),
        }
        score += sum(1.0 for keyword in keywords if any(keyword in term for term in doc_terms))
        score += sum(0.5 for keyword in document.keywords if keyword.lower() in goal_text)
        return score


class CandidateSynthesizer:
    """Convert observations into grounded planner candidates."""

    def __init__(
        self,
        manifest: KnowledgeManifest,
        *,
        llm: PlannerLLM | None = None,
        llm_config: PlannerLLMConfig | Mapping[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
        max_knowledge_hits: int = 4,
        max_excerpt_chars: int = 500,
    ) -> None:
        self.manifest = manifest
        self.retriever = KnowledgeRetriever(manifest)
        self.llm_config = normalize_planner_llm_config(llm_config, env=env)
        self.llm = llm or (OpenAICompatiblePlannerLLM() if self.llm_config is not None else None)
        self.max_knowledge_hits = max_knowledge_hits
        self.max_excerpt_chars = max_excerpt_chars

    def synthesize(
        self,
        *,
        tree: SearchTreeState,
        graph: AttackDependencyGraph,
        current_state: dict[str, Any],
        observation: PlannerNode,
        memory_hits: tuple[MemorySearchHit, ...] = (),
    ) -> tuple[CandidateProposal, ...]:
        """Create grounded candidate proposals for a single observation."""

        return self.generate(
            tree=tree,
            graph=graph,
            current_state=current_state,
            observation=observation,
            memory_hits=memory_hits,
        ).proposals

    def generate(
        self,
        *,
        tree: SearchTreeState,
        graph: AttackDependencyGraph,
        current_state: dict[str, Any],
        observation: PlannerNode,
        memory_hits: tuple[MemorySearchHit, ...] = (),
    ) -> SynthesisResult:
        """Generate candidate proposals and the auditable trace for one observation."""

        request = self._build_lookup_request(observation=observation, current_state=current_state, graph=graph)
        hits = self.retriever.lookup(request)
        knowledge_hits = hits[: self.max_knowledge_hits]
        excerpts = self._build_knowledge_excerpts(knowledge_hits)
        fallback = self._fallback_proposals(
            knowledge_hits=knowledge_hits,
            observation=observation,
            current_state=current_state,
        )
        if self.llm is None or self.llm_config is None or not self.llm_config.enabled:
            filtered_fallback = self._merge_proposals(graph=graph, primary=(), fallback=fallback)
            return SynthesisResult(
                proposals=filtered_fallback,
                trace=HypothesisTrace(
                    observation_node_id=observation.node_id,
                    generation_mode="fallback",
                    provider=self.llm_config.provider if self.llm_config is not None else None,
                    model=self.llm_config.model if self.llm_config is not None else None,
                    prompt=None,
                    raw_response=None,
                    llm_prompt_tokens=None,
                    llm_completion_tokens=None,
                    llm_total_tokens=None,
                    llm_cost_cny=None,
                    llm_latency_seconds=None,
                    parsed_payload=None,
                    validation_issues=(),
                    fallback_reason="llm-disabled-or-unconfigured",
                    knowledge_excerpts=excerpts,
                    memory_hits=_memory_hit_payloads(memory_hits),
                    proposal_keys=tuple(proposal.candidate_key for proposal in filtered_fallback),
                ),
            )

        prompt = self._build_prompt(
            graph=graph,
            current_state=current_state,
            observation=observation,
            knowledge_excerpts=excerpts,
            memory_hits=memory_hits,
        )
        raw_response: str | None = None
        completion: PlannerLLMCompletion | None = None
        parsed_payload: dict[str, Any] | None = None
        issues: list[str] = []
        llm_proposals: tuple[CandidateProposal, ...] = ()
        fallback_reason: str | None = None
        llm_latency_seconds: float | None = None
        llm_cost_cny: float | None = None
        try:
            started_at = perf_counter()
            llm_response = self.llm.complete(
                config=self.llm_config,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=prompt,
            )
            llm_latency_seconds = perf_counter() - started_at
            completion = _normalize_completion(llm_response)
            raw_response = completion.content
            if completion.usage is not None and self.llm_config.pricing is not None:
                llm_cost_cny = self.llm_config.pricing.estimate_cost_cny(completion.usage)
            parsed_payload = _extract_json_payload(raw_response)
            llm_proposals, issues = self._validate_llm_candidates(
                payload=parsed_payload,
                graph=graph,
                current_state=current_state,
                observation=observation,
                knowledge_hits=knowledge_hits,
            )
        except (PlannerLLMError, ValueError, TypeError, json.JSONDecodeError) as exc:
            issues.append(str(exc))
            fallback_reason = "llm-response-unusable"
        if llm_proposals:
            merged = self._merge_proposals(graph=graph, primary=llm_proposals, fallback=fallback)
            mode = "llm+fallback" if len(merged) > len(llm_proposals) else "llm"
        else:
            merged = self._merge_proposals(graph=graph, primary=(), fallback=fallback)
            mode = "fallback"
            if fallback_reason is None:
                fallback_reason = "no-valid-llm-candidates"
        return SynthesisResult(
            proposals=merged,
            trace=HypothesisTrace(
                observation_node_id=observation.node_id,
                generation_mode=mode,
                provider=self.llm_config.provider,
                model=self.llm_config.model,
                prompt=prompt,
                raw_response=raw_response,
                llm_prompt_tokens=None if completion is None or completion.usage is None else completion.usage.prompt_tokens,
                llm_completion_tokens=None
                if completion is None or completion.usage is None
                else completion.usage.completion_tokens,
                llm_total_tokens=None if completion is None or completion.usage is None else completion.usage.total_tokens,
                llm_cost_cny=llm_cost_cny,
                llm_latency_seconds=llm_latency_seconds,
                parsed_payload=parsed_payload,
                validation_issues=tuple(issues),
                fallback_reason=fallback_reason,
                knowledge_excerpts=excerpts,
                memory_hits=_memory_hit_payloads(memory_hits),
                proposal_keys=tuple(proposal.candidate_key for proposal in merged),
            ),
        )
    def ingest(
        self,
        *,
        tree: SearchTreeState,
        graph: AttackDependencyGraph,
        current_state: dict[str, Any],
        observation: PlannerNode,
        memory_hits: tuple[MemorySearchHit, ...] = (),
    ) -> SynthesisResult:
        """Synthesize candidates, insert them into the tree and graph, and return the trace."""

        result = self.generate(
            tree=tree,
            graph=graph,
            current_state=current_state,
            observation=observation,
            memory_hits=memory_hits,
        )
        for proposal in result.proposals:
            hypothesis = tree.add_hypothesis(
                parent_id=observation.node_id,
                title=proposal.title,
                hypothesis=proposal.hypothesis,
                metadata={
                    "candidate_key": proposal.candidate_key,
                    "action_kind": proposal.action_kind,
                    "action_target_name": proposal.target_name,
                    "goal": proposal.goal,
                    "request_parameters": proposal.request_parameters,
                    "request_context": proposal.request_context,
                    "effects": proposal.effects,
                    "knowledge_doc_ids": tuple(hit.doc_id for hit in proposal.knowledge_hits),
                    "knowledge_paths": tuple(str(hit.path) for hit in proposal.knowledge_hits),
                    "supporting_evidence": proposal.supporting_evidence,
                    "contradiction_signals": proposal.contradiction_signals,
                    "source_observation_id": proposal.source_observation_id,
                    **proposal.metadata,
                },
            )
            contradicting_node_ids = proposal.contradicting_node_ids
            if not contradicting_node_ids and set(proposal.contradiction_signals) & graph.contradicted_conditions:
                contradicting_node_ids = (observation.node_id,)
            candidate = graph.register_candidate(
                hypothesis_node_id=hypothesis.node_id,
                summary=proposal.hypothesis,
                candidate_key=proposal.candidate_key,
                prerequisites=proposal.prerequisites,
                effects=proposal.effects,
                supporting_node_ids=proposal.supporting_node_ids or (observation.node_id,),
                contradicting_node_ids=contradicting_node_ids,
            )
            tree.update_metadata(hypothesis.node_id, candidate_id=candidate.candidate_id)
        tree.update_metadata(
            observation.node_id,
            synthesized=True,
            synthesized_candidate_keys=tuple(proposal.candidate_key for proposal in result.proposals),
            synthesis_mode=result.trace.generation_mode,
        )
        return result

    def _build_lookup_request(
        self,
        *,
        observation: PlannerNode,
        current_state: dict[str, Any],
        graph: AttackDependencyGraph,
    ) -> KnowledgeLookupRequest:
        text = observation.content.lower()
        keywords: set[str] = set()
        if current_state.get("target_url"):
            keywords.update({"http", "surface mapping"})
        if current_state.get("target_host"):
            keywords.update({"reconnaissance", "services"})
        if current_state.get("wordlist_path") or "effect:web-surface-confirmed" in graph.satisfied_conditions:
            keywords.update({"directory enumeration", "content discovery"})
        if current_state.get("username") and (current_state.get("password") or current_state.get("ntlm_hash")):
            keywords.update({"credential reuse", "winrm"})
        if current_state.get("domain"):
            keywords.update({"kerberos"})
        if current_state.get("platform") and current_state.get("local_shell"):
            keywords.update({"privesc"})
        if "sql" in text or "inject" in text:
            keywords.update({"sql injection", "verification"})
        if observation.evidence.file_paths:
            keywords.update({"content discovery"})
        if observation.evidence.urls:
            keywords.update({"http"})
            if any("?" in url or "=" in url for url in observation.evidence.urls):
                keywords.update({"sql injection", "verification"})
        if any(port in {80, 443, 8080, 8443} for port in observation.evidence.ports):
            keywords.update({"http", "surface mapping"})
        return KnowledgeLookupRequest(
            goal=observation.content,
            current_state=current_state,
            preferred_kind="playbook",
            keywords=tuple(sorted(keywords)),
        )

    def _build_knowledge_excerpts(self, hits: Iterable[KnowledgeHit]) -> tuple[KnowledgeExcerpt, ...]:
        excerpts: list[KnowledgeExcerpt] = []
        for hit in hits:
            snippet = hit.path.read_text(encoding="utf-8").strip()
            snippet = " ".join(snippet.split())
            excerpts.append(
                KnowledgeExcerpt(
                    doc_id=hit.doc_id,
                    title=hit.title,
                    kind=hit.kind,
                    path=str(hit.path),
                    related_tools=hit.related_tools,
                    related_skills=hit.related_skills,
                    excerpt=snippet[: self.max_excerpt_chars],
                )
            )
        return tuple(excerpts)

    def _build_prompt(
        self,
        *,
        graph: AttackDependencyGraph,
        current_state: dict[str, Any],
        observation: PlannerNode,
        knowledge_excerpts: tuple[KnowledgeExcerpt, ...],
        memory_hits: tuple[MemorySearchHit, ...],
    ) -> str:
        allowed_targets = {
            "tool": sorted({tool for excerpt in knowledge_excerpts for tool in excerpt.related_tools}),
            "skill": sorted({skill for excerpt in knowledge_excerpts for skill in excerpt.related_skills}),
        }
        payload = {
            "objective": "Generate grounded planner hypotheses for the current observation.",
            "observation": {
                "node_id": observation.node_id,
                "title": observation.title,
                "content": observation.content,
                "evidence": {
                    "urls": list(observation.evidence.urls),
                    "ports": list(observation.evidence.ports),
                    "status_codes": list(observation.evidence.status_codes),
                    "file_paths": list(observation.evidence.file_paths),
                },
            },
            "current_state": _json_ready_mapping(current_state),
            "graph_state": {
                "satisfied_conditions": sorted(graph.satisfied_conditions),
                "contradicted_conditions": sorted(graph.contradicted_conditions),
                "existing_candidate_keys": sorted(
                    candidate.candidate_key
                    for candidate in graph.candidates.values()
                    if candidate.candidate_key is not None
                ),
            },
            "allowed_supporting_evidence": sorted(_allowed_supporting_evidence(observation, current_state)),
            "memory_context": _memory_hit_payloads(memory_hits),
            "knowledge_excerpts": [
                {
                    "doc_id": excerpt.doc_id,
                    "title": excerpt.title,
                    "kind": excerpt.kind,
                    "path": excerpt.path,
                    "related_tools": list(excerpt.related_tools),
                    "related_skills": list(excerpt.related_skills),
                    "excerpt": excerpt.excerpt,
                }
                for excerpt in knowledge_excerpts
            ],
            "allowed_targets": allowed_targets,
            "output_contract": {
                "candidates": [
                    {
                        "title": "string",
                        "hypothesis": "string",
                        "action_kind": "tool|skill",
                        "target_name": "one of the allowed targets",
                        "goal": "string",
                        "knowledge_doc_ids": ["subset of provided doc_ids"],
                        "supporting_evidence": ["subset of allowed_supporting_evidence"],
                        "prerequisites": ["condition strings"],
                        "effects": ["condition strings"],
                        "request_parameters": {"optional": "json object"},
                        "request_context": {"optional": "json object"},
                        "contradiction_signals": ["optional condition strings"],
                        "priority": 0,
                    }
                ]
            },
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    def _validate_llm_candidates(
        self,
        *,
        payload: dict[str, Any],
        graph: AttackDependencyGraph,
        current_state: dict[str, Any],
        observation: PlannerNode,
        knowledge_hits: tuple[KnowledgeHit, ...],
    ) -> tuple[tuple[CandidateProposal, ...], list[str]]:
        records = payload.get("candidates")
        if not isinstance(records, list):
            raise ValueError("LLM output must contain a top-level 'candidates' list.")
        allowed_evidence = _allowed_supporting_evidence(observation, current_state)
        allowed_hit_by_id = {hit.doc_id: hit for hit in knowledge_hits}
        manifest_tool_ids = self.manifest.tool_ids()
        manifest_skill_ids = self.manifest.skill_ids()
        proposals: list[CandidateProposal] = []
        issues: list[str] = []
        for index, raw_candidate in enumerate(records):
            if not isinstance(raw_candidate, Mapping):
                issues.append(f"candidate[{index}] is not an object")
                continue
            try:
                title = _required_string(raw_candidate, "title")
                hypothesis = _required_string(raw_candidate, "hypothesis")
                action_kind = _required_string(raw_candidate, "action_kind")
                target_name = _required_string(raw_candidate, "target_name")
                goal = _required_string(raw_candidate, "goal")
                knowledge_doc_ids = _string_sequence(raw_candidate.get("knowledge_doc_ids", ()))
                supporting_evidence = _string_sequence(raw_candidate.get("supporting_evidence", ()))
                prerequisites = _string_sequence(raw_candidate.get("prerequisites", ()))
                effects = _string_sequence(raw_candidate.get("effects", ()))
                contradiction_signals = _string_sequence(raw_candidate.get("contradiction_signals", ()))
                priority = int(raw_candidate.get("priority", 0))
                request_parameters = _json_ready_mapping(raw_candidate.get("request_parameters", {}))
                request_context = _json_ready_mapping(raw_candidate.get("request_context", {}))
            except (TypeError, ValueError) as exc:
                issues.append(f"candidate[{index}] rejected: {exc}")
                continue
            if action_kind == "skill":
                if target_name not in manifest_skill_ids:
                    issues.append(f"candidate[{index}] rejected: unknown skill {target_name!r}")
                    continue
            elif action_kind == "tool":
                if target_name not in manifest_tool_ids:
                    issues.append(f"candidate[{index}] rejected: unknown tool {target_name!r}")
                    continue
            else:
                issues.append(f"candidate[{index}] rejected: unsupported action_kind {action_kind!r}")
                continue
            if not knowledge_doc_ids:
                issues.append(f"candidate[{index}] rejected: knowledge_doc_ids is required")
                continue
            selected_hits: list[KnowledgeHit] = []
            related_targets: set[str] = set()
            for doc_id in knowledge_doc_ids:
                hit = allowed_hit_by_id.get(doc_id)
                if hit is None:
                    issues.append(f"candidate[{index}] rejected: unknown knowledge_doc_id {doc_id!r}")
                    selected_hits = []
                    break
                selected_hits.append(hit)
                related_targets.update(hit.related_skills if action_kind == "skill" else hit.related_tools)
            if not selected_hits:
                continue
            if target_name not in related_targets:
                issues.append(
                    f"candidate[{index}] rejected: target {target_name!r} is not supported by the selected knowledge docs"
                )
                continue
            if not supporting_evidence:
                issues.append(f"candidate[{index}] rejected: supporting_evidence is required")
                continue
            if any(reference not in allowed_evidence for reference in supporting_evidence):
                issues.append(f"candidate[{index}] rejected: supporting_evidence must come from the supplied context")
                continue
            proposal = CandidateProposal(
                candidate_key=_candidate_key(
                    observation_node_id=observation.node_id,
                    action_kind=action_kind,
                    target_name=target_name,
                    goal=goal,
                    request_parameters=request_parameters,
                ),
                title=title,
                hypothesis=hypothesis,
                source_observation_id=observation.node_id,
                action_kind=action_kind,  # type: ignore[arg-type]
                target_name=target_name,
                goal=goal,
                request_parameters=request_parameters,
                request_context=request_context,
                prerequisites=prerequisites,
                effects=effects,
                knowledge_hits=tuple(selected_hits),
                supporting_evidence=supporting_evidence,
                contradiction_signals=contradiction_signals,
                metadata={
                    "priority": priority,
                    "generation_mode": "llm",
                },
            )
            if graph.get_candidate_by_key(proposal.candidate_key) is not None:
                issues.append(f"candidate[{index}] skipped: duplicate candidate key {proposal.candidate_key}")
                continue
            if any(existing.candidate_key == proposal.candidate_key for existing in proposals):
                issues.append(f"candidate[{index}] skipped: duplicate candidate key {proposal.candidate_key}")
                continue
            proposals.append(proposal)
        return tuple(proposals), issues

    def _fallback_proposals(
        self,
        *,
        knowledge_hits: tuple[KnowledgeHit, ...],
        observation: PlannerNode,
        current_state: dict[str, Any],
    ) -> tuple[CandidateProposal, ...]:
        proposals: list[CandidateProposal] = []
        for hit in knowledge_hits:
            proposal = self._proposal_from_hit(
                hit=hit,
                observation=observation,
                current_state=current_state,
            )
            if proposal is None:
                continue
            if any(existing.candidate_key == proposal.candidate_key for existing in proposals):
                continue
            proposals.append(proposal)
        return tuple(proposals)

    def _merge_proposals(
        self,
        *,
        graph: AttackDependencyGraph,
        primary: tuple[CandidateProposal, ...],
        fallback: tuple[CandidateProposal, ...],
    ) -> tuple[CandidateProposal, ...]:
        merged: list[CandidateProposal] = []
        seen = {
            candidate.candidate_key
            for candidate in graph.candidates.values()
            if candidate.candidate_key is not None
        }
        for collection in (primary, fallback):
            for proposal in collection:
                if proposal.candidate_key in seen:
                    continue
                signature = _proposal_signature(proposal)
                if any(_proposal_signature(existing) == signature for existing in merged):
                    continue
                seen.add(proposal.candidate_key)
                merged.append(proposal)
        return tuple(merged)

    def _proposal_from_hit(
        self,
        *,
        hit: KnowledgeHit,
        observation: PlannerNode,
        current_state: dict[str, Any],
    ) -> CandidateProposal | None:
        rule = _RULES.get(hit.doc_id)
        if rule is None:
            return None
        if hit.doc_id == "service-enumeration":
            target_host = current_state.get("target_host")
            if not target_host:
                return None
            return CandidateProposal(
                candidate_key=f"skill:service-enumeration:{target_host}",
                title=rule.title,
                hypothesis=f"Enumerating services on {target_host} can establish the reachable attack surface.",
                source_observation_id=observation.node_id,
                action_kind="skill",
                target_name=rule.target_name,
                goal="Enumerate exposed services and confirm whether follow-up web actions are justified.",
                prerequisites=("state:target-host",),
                effects=("effect:service-enumerated", "signal:http-candidate"),
                knowledge_hits=(hit,),
                supporting_evidence=_fallback_supporting_evidence(
                    observation=observation,
                    current_state=current_state,
                    preferred_keys=("state:target_host",),
                ),
                metadata={"priority": 20, "generation_mode": "fallback"},
            )
        if hit.doc_id == "web-surface-mapping":
            target_url = current_state.get("target_url")
            target_host = current_state.get("target_host")
            if not target_url or not target_host:
                return None
            return CandidateProposal(
                candidate_key=f"skill:web-surface-mapping:{target_url}",
                title=rule.title,
                hypothesis=f"Mapping {target_url} can confirm the web surface and establish the next web follow-up steps.",
                source_observation_id=observation.node_id,
                action_kind="skill",
                target_name=rule.target_name,
                goal="Confirm the reachable web surface and gather a baseline observation.",
                prerequisites=("state:target-url", "state:target-host"),
                effects=("effect:web-surface-confirmed",),
                knowledge_hits=(hit,),
                supporting_evidence=_fallback_supporting_evidence(
                    observation=observation,
                    current_state=current_state,
                    preferred_keys=("state:target_url", "state:target_host"),
                ),
                metadata={"priority": 60, "generation_mode": "fallback"},
            )
        if hit.doc_id == "content-discovery":
            target_url = current_state.get("target_url")
            if not target_url:
                return None
            return CandidateProposal(
                candidate_key=f"skill:content-discovery:{target_url}",
                title=rule.title,
                hypothesis=f"Content discovery against {target_url} can reveal hidden paths or vhosts that unlock deeper attack paths.",
                source_observation_id=observation.node_id,
                action_kind="skill",
                target_name=rule.target_name,
                goal="Enumerate hidden content and capture interesting paths or vhosts.",
                request_parameters={
                    "wordlist_path": current_state.get("wordlist_path"),
                },
                prerequisites=("state:target-url", "state:wordlist-path", "effect:web-surface-confirmed"),
                effects=("effect:content-discovered",),
                knowledge_hits=(hit,),
                supporting_evidence=_fallback_supporting_evidence(
                    observation=observation,
                    current_state=current_state,
                    preferred_keys=("state:target_url", "state:wordlist_path"),
                ),
                metadata={"priority": 50, "generation_mode": "fallback"},
            )
        if hit.doc_id == "sqli-verification":
            target_url = current_state.get("sqli_candidate_url") or current_state.get("target_url")
            if not target_url:
                return None
            return CandidateProposal(
                candidate_key=f"skill:sqli-verification:{target_url}",
                title=rule.title,
                hypothesis=f"The current web evidence suggests {target_url} is worth verifying for SQL injection with constrained settings.",
                source_observation_id=observation.node_id,
                action_kind="skill",
                target_name=rule.target_name,
                goal="Verify whether the candidate endpoint is actually vulnerable to SQL injection.",
                request_parameters={},
                prerequisites=("state:target-url", "signal:sqli-candidate"),
                effects=("effect:sqli-verified",),
                knowledge_hits=(hit,),
                supporting_evidence=_fallback_supporting_evidence(
                    observation=observation,
                    current_state=current_state,
                    preferred_keys=("state:sqli_candidate_url", "state:target_url"),
                ),
                metadata={"priority": 55, "generation_mode": "fallback"},
            )
        if hit.doc_id == "credential-reuse-check":
            target_host = current_state.get("target_host")
            username = current_state.get("username")
            if not target_host or not username:
                return None
            parameters: dict[str, Any] = {
                "protocol": current_state.get("protocol", "winrm"),
            }
            prerequisites = ["state:target-host", "state:username"]
            if current_state.get("password"):
                parameters["password"] = current_state["password"]
                prerequisites.append("state:password")
            elif current_state.get("ntlm_hash"):
                parameters["ntlm_hash"] = current_state["ntlm_hash"]
                prerequisites.append("state:ntlm-hash")
            else:
                return None
            if current_state.get("domain"):
                parameters["domain"] = current_state["domain"]
            return CandidateProposal(
                candidate_key=f"skill:credential-reuse-check:{target_host}:{username}:{parameters['protocol']}",
                title=rule.title,
                hypothesis=f"Recovered credentials for {username} should be validated against {target_host} over {parameters['protocol']}.",
                source_observation_id=observation.node_id,
                action_kind="skill",
                target_name=rule.target_name,
                goal="Validate whether the recovered credential grants remote access.",
                request_parameters=parameters,
                prerequisites=tuple(prerequisites),
                effects=("effect:credential-reuse-validated",),
                knowledge_hits=(hit,),
                supporting_evidence=_fallback_supporting_evidence(
                    observation=observation,
                    current_state=current_state,
                    preferred_keys=("state:target_host", "state:username"),
                ),
                metadata={"priority": 60, "generation_mode": "fallback"},
            )
        if hit.doc_id == "asrep-roast-collection":
            if not _has_state(current_state, "domain", "dc_host", "usernames_file_path"):
                return None
            return CandidateProposal(
                candidate_key=f"skill:asrep-roast-collection:{current_state['domain']}:{current_state['dc_host']}",
                title=rule.title,
                hypothesis="The available domain context is sufficient to attempt AS-REP roast collection.",
                source_observation_id=observation.node_id,
                action_kind="skill",
                target_name=rule.target_name,
                goal="Collect AS-REP roastable hashes from accounts without pre-authentication.",
                request_parameters={},
                prerequisites=("state:domain", "state:dc-host", "state:usernames-file"),
                effects=("effect:asrep-roast-collected",),
                knowledge_hits=(hit,),
                supporting_evidence=_fallback_supporting_evidence(
                    observation=observation,
                    current_state=current_state,
                    preferred_keys=("state:domain", "state:dc_host"),
                ),
                metadata={"priority": 45, "generation_mode": "fallback"},
            )
        if hit.doc_id == "kerberoast-collection":
            if not _has_state(current_state, "domain", "dc_host", "username"):
                return None
            parameters = {}
            prerequisites = ["state:domain", "state:dc-host", "state:username"]
            if current_state.get("password"):
                parameters["password"] = current_state["password"]
                prerequisites.append("state:password")
            elif current_state.get("ntlm_hash"):
                parameters["ntlm_hash"] = current_state["ntlm_hash"]
                prerequisites.append("state:ntlm-hash")
            else:
                return None
            return CandidateProposal(
                candidate_key=f"skill:kerberoast-collection:{current_state['domain']}:{current_state['username']}",
                title=rule.title,
                hypothesis="The available domain credential can be used to request Kerberoastable service tickets.",
                source_observation_id=observation.node_id,
                action_kind="skill",
                target_name=rule.target_name,
                goal="Validate the domain credential and request Kerberoastable service tickets.",
                request_parameters=parameters,
                prerequisites=tuple(prerequisites),
                effects=("effect:kerberoast-collected",),
                knowledge_hits=(hit,),
                supporting_evidence=_fallback_supporting_evidence(
                    observation=observation,
                    current_state=current_state,
                    preferred_keys=("state:domain", "state:username"),
                ),
                metadata={"priority": 50, "generation_mode": "fallback"},
            )
        if hit.doc_id == "local-privesc-enum":
            platform = current_state.get("platform")
            if platform not in {"linux", "windows"} or not current_state.get("local_shell"):
                return None
            return CandidateProposal(
                candidate_key=f"skill:local-privesc-enum:{platform}",
                title=rule.title,
                hypothesis=f"The current {platform} foothold should be enumerated for privilege-escalation paths.",
                source_observation_id=observation.node_id,
                action_kind="skill",
                target_name=rule.target_name,
                goal="Run the platform-appropriate local privilege-escalation enumeration skill.",
                request_parameters={},
                prerequisites=("state:platform", "state:local-shell"),
                effects=("effect:local-privesc-enumerated",),
                knowledge_hits=(hit,),
                supporting_evidence=_fallback_supporting_evidence(
                    observation=observation,
                    current_state=current_state,
                    preferred_keys=("state:platform", "state:local_shell"),
                ),
                metadata={"priority": 55, "generation_mode": "fallback"},
            )
        return None


def state_to_conditions(current_state: dict[str, Any]) -> tuple[str, ...]:
    """Derive deterministic graph conditions from planner session state."""

    conditions: set[str] = set()
    if current_state.get("target_host"):
        conditions.add("state:target-host")
    target_url = current_state.get("target_url")
    if target_url:
        conditions.add("state:target-url")
        scheme = urlparse(target_url).scheme.lower()
        if scheme in {"http", "https"}:
            conditions.add("signal:http-candidate")
    if current_state.get("wordlist_path"):
        conditions.add("state:wordlist-path")
    if current_state.get("username"):
        conditions.add("state:username")
    if current_state.get("password"):
        conditions.add("state:password")
    if current_state.get("ntlm_hash"):
        conditions.add("state:ntlm-hash")
    if current_state.get("domain"):
        conditions.add("state:domain")
    if current_state.get("dc_host"):
        conditions.add("state:dc-host")
    if current_state.get("usernames_file_path"):
        conditions.add("state:usernames-file")
    if current_state.get("platform"):
        conditions.add("state:platform")
    if current_state.get("local_shell"):
        conditions.add("state:local-shell")
    if current_state.get("sqli_candidate_url"):
        conditions.add("signal:sqli-candidate")
    return tuple(sorted(conditions))


def enrich_state_from_observation(current_state: dict[str, Any], observation: PlannerNode) -> dict[str, Any]:
    """Merge structured state hints from a planner observation node."""

    updated = dict(current_state)
    if not updated.get("target_url") and observation.evidence.urls:
        updated["target_url"] = observation.evidence.urls[0]
    if not updated.get("target_host") and updated.get("target_url"):
        parsed = urlparse(updated["target_url"])
        if parsed.hostname:
            updated["target_host"] = parsed.hostname
    if observation.evidence.urls:
        updated["observed_urls"] = sorted(set(updated.get("observed_urls", [])) | set(observation.evidence.urls))
        for url in observation.evidence.urls:
            if "?" in url or "=" in url:
                updated.setdefault("sqli_candidate_url", url)
    if observation.evidence.file_paths:
        updated["observed_paths"] = sorted(set(updated.get("observed_paths", [])) | set(observation.evidence.file_paths))
    return updated


def _candidate_key(
    *,
    observation_node_id: str,
    action_kind: str,
    target_name: str,
    goal: str,
    request_parameters: dict[str, Any],
) -> str:
    stable_seed = json.dumps(
        {
            "observation_node_id": observation_node_id,
            "action_kind": action_kind,
            "target_name": target_name,
            "goal": goal,
            "request_parameters": request_parameters,
        },
        sort_keys=True,
    )
    return f"{action_kind}:{target_name}:{sha1(stable_seed.encode('utf-8')).hexdigest()[:12]}"


def _proposal_signature(proposal: CandidateProposal) -> str:
    return json.dumps(
        {
            "action_kind": proposal.action_kind,
            "target_name": proposal.target_name,
            "request_parameters": proposal.request_parameters,
        },
        sort_keys=True,
    )


def _normalize_completion(response: str | PlannerLLMCompletion) -> PlannerLLMCompletion:
    if isinstance(response, PlannerLLMCompletion):
        return response
    return PlannerLLMCompletion(content=response)


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    candidate = raw_text.strip()
    if candidate.startswith("```"):
        lines = [line for line in candidate.splitlines() if not line.startswith("```")]
        candidate = "\n".join(lines).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM output does not contain a JSON object.")
    payload = json.loads(candidate[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM output must be a JSON object.")
    return payload


def _json_ready_mapping(raw_value: Any) -> dict[str, Any]:
    if raw_value in (None, ""):
        return {}
    if not isinstance(raw_value, Mapping):
        raise TypeError("expected a JSON object mapping")
    normalized: dict[str, Any] = {}
    for key, value in raw_value.items():
        normalized[str(key)] = _json_ready_value(value)
    return normalized


def _json_ready_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_ready_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready_value(item) for item in value]
    return str(value)


def _string_sequence(raw_value: Any) -> tuple[str, ...]:
    if raw_value in (None, ""):
        return ()
    if not isinstance(raw_value, (list, tuple)):
        raise TypeError("expected a list of strings")
    values = [str(item).strip() for item in raw_value if str(item).strip()]
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def _required_string(mapping: Mapping[str, Any], key: str) -> str:
    value = str(mapping.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _fallback_supporting_evidence(
    *,
    observation: PlannerNode,
    current_state: dict[str, Any],
    preferred_keys: tuple[str, ...],
) -> tuple[str, ...]:
    allowed = _allowed_supporting_evidence(observation, current_state)
    selected = tuple(reference for reference in preferred_keys if reference in allowed)
    if selected:
        return selected
    if allowed:
        return (sorted(allowed)[0],)
    return ()


def _allowed_supporting_evidence(observation: PlannerNode, current_state: dict[str, Any]) -> set[str]:
    return _allowed_supporting_evidence_impl(observation, current_state)


def _allowed_supporting_evidence_impl(observation: PlannerNode, current_state: dict[str, Any]) -> set[str]:
    evidence_refs = {
        *(f"url:{url}" for url in observation.evidence.urls),
        *(f"port:{port}" for port in observation.evidence.ports),
        *(f"status:{status_code}" for status_code in observation.evidence.status_codes),
        *(f"path:{path}" for path in observation.evidence.file_paths),
    }
    state_mapping = {
        "target_url": "state:target_url",
        "target_host": "state:target_host",
        "wordlist_path": "state:wordlist_path",
        "username": "state:username",
        "password": "state:password",
        "ntlm_hash": "state:ntlm_hash",
        "domain": "state:domain",
        "dc_host": "state:dc_host",
        "usernames_file_path": "state:usernames_file_path",
        "platform": "state:platform",
        "local_shell": "state:local_shell",
        "sqli_candidate_url": "state:sqli_candidate_url",
    }
    for key, reference in state_mapping.items():
        if current_state.get(key):
            evidence_refs.add(reference)
    return evidence_refs


def _has_state(current_state: dict[str, Any], *keys: str) -> bool:
    return all(current_state.get(key) for key in keys)


def _memory_hit_payloads(memory_hits: tuple[MemorySearchHit, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "document_id": hit.document_id,
            "record_id": hit.record_id,
            "kind": hit.kind,
            "title": hit.title,
            "score": hit.score,
            "matched_terms": list(hit.matched_terms),
            "artifact_paths": list(hit.artifact_paths),
            "candidate_id": hit.candidate_id,
        }
        for hit in memory_hits
    )
