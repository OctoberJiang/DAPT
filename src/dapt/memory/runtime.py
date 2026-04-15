"""Structured memory store and deterministic retrieval index."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from dapt.perceptor import MemoryStagingRecord

from .models import MemoryQuery, MemoryRecord, MemoryRecordKind, MemorySearchHit, RetrievalDocument


class MemoryStore:
    """Session-scoped structured memory with a deterministic retrieval view."""

    def __init__(self, *, session_id: str, target_name: str) -> None:
        self.session_id = session_id
        self.target_name = target_name
        self.records: dict[str, MemoryRecord] = {}
        self.retrieval_documents: dict[str, RetrievalDocument] = {}
        self._source_index: dict[str, str] = {}
        self._record_counter = 0
        self._document_counter = 0

    def add_record(
        self,
        *,
        kind: MemoryRecordKind,
        summary: str,
        content: str,
        source_key: str,
        tags: Iterable[str] = (),
        artifact_paths: Iterable[str] = (),
        evidence_refs: Iterable[str] = (),
        planner_node_id: str | None = None,
        request_id: str | None = None,
        candidate_id: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        """Add a structured record if it has not already been indexed."""

        existing_id = self._source_index.get(source_key)
        if existing_id is not None:
            return self.records[existing_id]
        record_id = self._allocate_record_id()
        record = MemoryRecord(
            record_id=record_id,
            session_id=self.session_id,
            target_name=self.target_name,
            kind=kind,
            summary=summary,
            content=content,
            source_key=source_key,
            tags=tuple(sorted({tag for tag in tags if tag})),
            artifact_paths=tuple(sorted({path for path in artifact_paths if path})),
            evidence_refs=tuple(sorted({ref for ref in evidence_refs if ref})),
            planner_node_id=planner_node_id,
            request_id=request_id,
            candidate_id=candidate_id,
            status=status,
            metadata=metadata or {},
        )
        self.records[record_id] = record
        self._source_index[source_key] = record_id
        self._index_record(record)
        return record

    def ingest_memory_staging(self, record: MemoryStagingRecord) -> MemoryRecord:
        """Convert a Perceptor memory-staging entry into a structured fact record."""

        return self.add_record(
            kind="fact",
            summary=record.observation,
            content=record.observation,
            source_key=f"memory-staging:{record.request_id}",
            tags=_memory_tags_from_text(record.observation),
            artifact_paths=record.source_artifact_paths,
            evidence_refs=_evidence_refs(record.evidence),
            planner_node_id=record.planner_node_id,
            request_id=record.request_id,
            metadata={"evidence": record.evidence.as_dict()},
        )

    def ingest_candidate_proposals(self, *, observation_node_id: str, proposals: Iterable) -> tuple[MemoryRecord, ...]:
        """Index planner-generated hypotheses as structured memory."""

        records: list[MemoryRecord] = []
        for proposal in proposals:
            records.append(
                self.add_record(
                    kind="hypothesis",
                    summary=proposal.title,
                    content=proposal.hypothesis,
                    source_key=f"candidate:{proposal.candidate_key}",
                    tags=(
                        proposal.action_kind,
                        proposal.target_name,
                        *(hit.doc_id for hit in proposal.knowledge_hits),
                    ),
                    evidence_refs=proposal.supporting_evidence,
                    planner_node_id=observation_node_id,
                    metadata={
                        "goal": proposal.goal,
                        "prerequisites": proposal.prerequisites,
                        "effects": proposal.effects,
                        "knowledge_doc_ids": [hit.doc_id for hit in proposal.knowledge_hits],
                    },
                )
            )
        return tuple(records)

    def ingest_turn_result(self, *, turn_record, tree, graph) -> MemoryRecord | None:
        """Index one planner turn result as an outcome record."""

        if not turn_record.request_id:
            return None
        summary = turn_record.notes or f"Planner turn {turn_record.turn_index} executed."
        content_parts = [summary]
        if turn_record.candidate_id:
            candidate = graph.candidates.get(turn_record.candidate_id)
            if candidate is not None:
                content_parts.append(candidate.summary)
        if turn_record.observation_node_id:
            observation = tree.nodes.get(turn_record.observation_node_id)
            if observation is not None:
                content_parts.append(observation.content)
        return self.add_record(
            kind="outcome",
            summary=summary,
            content=" ".join(part for part in content_parts if part),
            source_key=f"turn:{turn_record.request_id}",
            tags=("turn-result", turn_record.status),
            planner_node_id=turn_record.observation_node_id or turn_record.action_node_id,
            request_id=turn_record.request_id,
            candidate_id=turn_record.candidate_id,
            status=turn_record.status,
            metadata={"turn_index": turn_record.turn_index, "termination_reason": turn_record.termination_reason},
        )

    def ingest_contradictions(self, *, graph) -> tuple[MemoryRecord, ...]:
        """Index contradicted candidates without removing prior provenance."""

        records: list[MemoryRecord] = []
        for candidate in graph.candidates.values():
            if candidate.status != "contradicted":
                continue
            records.append(
                self.add_record(
                    kind="contradiction",
                    summary=f"Candidate contradicted: {candidate.candidate_id}",
                    content=candidate.summary,
                    source_key=f"contradiction:{candidate.candidate_id}",
                    tags=("contradicted",),
                    candidate_id=candidate.candidate_id,
                    planner_node_id=candidate.hypothesis_node_id,
                    status=candidate.status,
                    metadata={"contradicting_node_ids": candidate.contradicting_node_ids},
                )
            )
        return tuple(records)

    def ingest_objective_progress(self, progress) -> MemoryRecord | None:
        """Index one objective-progress snapshot."""

        if progress is None:
            return None
        indicator = progress.success_indicator or "pending"
        return self.add_record(
            kind="objective",
            summary=progress.objective_summary,
            content=" ".join(
                part
                for part in (
                    progress.objective_summary,
                    progress.success_indicator,
                    " ".join(progress.partial_progress_markers),
                )
                if part
            ),
            source_key=f"objective:{progress.mode}:{indicator}:{','.join(progress.matched_observation_ids)}",
            tags=(progress.mode, *(progress.partial_progress_markers or ())),
            planner_node_id=progress.matched_observation_ids[-1] if progress.matched_observation_ids else None,
            status="succeeded" if progress.succeeded else "pending",
            metadata=progress.as_payload(),
        )

    def search(self, query: MemoryQuery) -> tuple[MemorySearchHit, ...]:
        """Return deterministic ranked retrieval hits for the query."""

        goal_terms = _tokenize(query.goal)
        keyword_terms = {term.lower() for term in query.keywords}
        scored: list[MemorySearchHit] = []
        for document in self.retrieval_documents.values():
            if query.kinds and document.kind not in query.kinds:
                continue
            if query.candidate_id and document.candidate_id != query.candidate_id:
                continue
            haystack = " ".join((document.title, document.text, " ".join(document.tags))).lower()
            matched_terms = tuple(
                term
                for term in sorted(goal_terms | keyword_terms)
                if term and term in haystack
            )
            if not matched_terms:
                continue
            score = float(len(matched_terms))
            if document.kind == "fact":
                score += 0.5
            if query.candidate_id and document.candidate_id == query.candidate_id:
                score += 2.0
            scored.append(
                MemorySearchHit(
                    document_id=document.document_id,
                    record_id=document.record_id,
                    kind=document.kind,
                    title=document.title,
                    score=score,
                    matched_terms=matched_terms,
                    artifact_paths=document.artifact_paths,
                    candidate_id=document.candidate_id,
                )
            )
        scored.sort(key=lambda hit: (-hit.score, hit.kind, hit.document_id))
        return tuple(scored[: max(query.limit, 0)])

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_name": self.target_name,
            "records": {record_id: asdict(record) for record_id, record in sorted(self.records.items())},
        }

    def retrieval_snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_name": self.target_name,
            "documents": {doc_id: asdict(document) for doc_id, document in sorted(self.retrieval_documents.items())},
        }

    def _index_record(self, record: MemoryRecord) -> None:
        document_id = self._allocate_document_id()
        self.retrieval_documents[document_id] = RetrievalDocument(
            document_id=document_id,
            record_id=record.record_id,
            session_id=self.session_id,
            target_name=self.target_name,
            kind=record.kind,
            title=record.summary,
            text=" ".join(
                part
                for part in (record.summary, record.content, " ".join(record.evidence_refs))
                if part
            ),
            tags=record.tags,
            artifact_paths=record.artifact_paths,
            candidate_id=record.candidate_id,
        )

    def _allocate_record_id(self) -> str:
        self._record_counter += 1
        return f"mem-{self._record_counter:04d}"

    def _allocate_document_id(self) -> str:
        self._document_counter += 1
        return f"doc-{self._document_counter:04d}"


def _memory_tags_from_text(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    tags = []
    for needle, tag in (
        ("sql", "sql"),
        ("flag{", "flag"),
        ("root", "root"),
        ("admin", "admin"),
        ("login", "login"),
    ):
        if needle in lowered:
            tags.append(tag)
    return tuple(sorted(set(tags)))


def _evidence_refs(evidence) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *(f"url:{url}" for url in evidence.urls),
                *(f"port:{port}" for port in evidence.ports),
                *(f"status:{status_code}" for status_code in evidence.status_codes),
                *(f"path:{path}" for path in evidence.file_paths),
            }
        )
    )


def _tokenize(text: str) -> set[str]:
    return {term.lower() for term in text.replace("/", " ").replace(":", " ").split() if len(term) >= 3}
