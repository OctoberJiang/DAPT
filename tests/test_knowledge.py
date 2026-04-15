from __future__ import annotations

import unittest
from pathlib import Path

from dapt.executor import build_pentest_registry, build_pentest_tool_registry
from dapt.knowledge import load_knowledge_manifest


class KnowledgeManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.manifest = load_knowledge_manifest(self.repo_root)

    def test_manifest_and_retrieval_contract_exist(self) -> None:
        self.assertEqual(self.manifest.schema_version, 1)
        self.assertTrue(self.manifest.retrieval_contract_path.exists())

    def test_all_manifest_documents_exist(self) -> None:
        for document in self.manifest.all_documents():
            self.assertTrue(document.path.exists(), document.path.as_posix())
            self.assertTrue(document.keywords, document.doc_id)

    def test_every_registered_pentest_tool_has_a_tool_note(self) -> None:
        registry = build_pentest_tool_registry()
        self.assertEqual(set(registry.tools), self.manifest.tool_ids())

    def test_every_registered_pentest_skill_has_a_playbook(self) -> None:
        registry = build_pentest_registry()
        self.assertEqual(set(registry.skills), self.manifest.skill_ids())

    def test_related_tool_and_skill_references_are_known(self) -> None:
        registry = build_pentest_registry()
        tool_ids = set(registry.tools)
        skill_ids = set(registry.skills)
        for document in self.manifest.all_documents():
            self.assertTrue(set(document.related_tools).issubset(tool_ids), document.doc_id)
            self.assertTrue(set(document.related_skills).issubset(skill_ids), document.doc_id)


if __name__ == "__main__":
    unittest.main()
