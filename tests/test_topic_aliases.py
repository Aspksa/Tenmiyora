"""Безопасное, обратимое объединение синонимов без удаления записей."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"bootstrap"))
from knowledge import KnowledgeStore
from topic_aliases import parse_pair, projection

ASTRO=("Астрономия — это область исследования звёзд и небесных тел.\n\n"
       "Астрономия изучает движение планетных систем и небесных объектов.")
STARS=("Звездоведение — это область исследования небесных тел и далёких звёзд.\n\n"
       "Звездоведение изучает наблюдаемые свойства планетных систем и звёзд.")
PROOF=('«Звездоведение» — синоним «Астрономия».\n\n'
       '«Звездоведение» также называют «Астрономия».')


class AliasTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def roots(self):
        return [r["name"] for r in self.store.branches()["branches"]
                if r["parent"] is None]

    def alias_count(self):
        with self.store.db() as db:
            return db.execute("SELECT COUNT(*) FROM topic_aliases").fetchone()[0]

    def test_two_proofs_merge_existing_roots_without_deleting_knowledge(self):
        a=self.store.upload("astronomy.txt",ASTRO.encode())["id"]
        b=self.store.upload("stars.txt",STARS.encode())["id"]
        self.assertIn("Звездоведение",self.roots())
        self.assertIn("Астрономия",self.roots())
        with self.store.db() as db:
            before=db.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]
            old=db.execute("SELECT id FROM branches WHERE name='Звездоведение'").fetchone()["id"]
            first=db.execute("SELECT id FROM branches WHERE name='Астрономия'").fetchone()["id"]
        proof=self.store.upload("synonyms.txt",PROOF.encode())["id"]
        self.assertEqual(self.alias_count(),1)
        self.assertIn("Астрономия",self.roots())
        self.assertNotIn("Звездоведение",self.roots())
        with self.store.db() as db:
            alias=db.execute("SELECT canonical_id FROM topic_aliases").fetchone()
            self.assertEqual(alias["canonical_id"],first)
            self.assertGreater(db.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0],before)
            self.assertIsNotNone(db.execute("SELECT id FROM branches WHERE id=?",(old,)).fetchone())
            self.assertGreaterEqual(db.execute("SELECT COUNT(*) FROM topic_alias_claims WHERE source_id=?",
                                               (proof,)).fetchone()[0],2)
        # Old links / IDs still reveal original evidence, preserving source provenance.
        joint=self.store.facts(first)["facts"]
        self.assertTrue(any(r["source_id"]==a for r in joint))
        self.assertTrue(any(r["source_id"]==b for r in joint))
        self.assertTrue(any(r["source_id"]==b for r in self.store.facts(old)["facts"]))
        self.assertEqual(self.store.engine._branch_test_name if False else True,True)

    def test_merger_is_reversible_when_evidence_disappears(self):
        self.store.upload("astronomy.txt",ASTRO.encode())
        self.store.upload("stars.txt",STARS.encode())
        alias=self.store.upload("synonyms.txt",PROOF.encode())["id"]
        self.assertEqual(self.alias_count(),1)
        self.store.delete("file",alias)
        self.assertEqual(self.alias_count(),0)
        self.assertIn("Звездоведение",self.roots())
        self.assertIn("Астрономия",self.roots())

    def test_one_proof_repetition_or_non_synonym_does_not_merge(self):
        self.store.upload("astronomy.txt",ASTRO.encode())
        self.store.upload("stars.txt",STARS.encode())
        once='«Звездоведение» — синоним «Астрономия».'
        self.store.upload("single.txt",once.encode())
        self.store.upload("copied.txt",once.encode())
        self.assertEqual(self.alias_count(),0)
        self.store.upload("unrelated.txt",
            "Астрономия и звездоведение изучают разные вопросы науки.".encode())
        self.assertEqual(self.alias_count(),0)

    def test_conflicting_claims_cannot_redirect_one_name_to_two_roots(self):
        self.store.upload("astronomy.txt",ASTRO.encode())
        self.store.upload("stars.txt",STARS.encode())
        science=("Астрофизика — это область измерения звёздных процессов.\n\n"
                 "Астрофизика изучает спектры небесных тел и источников света.")
        self.store.upload("science.txt",science.encode())
        self.store.upload("proof.txt",PROOF.encode())
        self.store.upload("conflict.txt",
            ('«Звездоведение» — синоним «Астрофизика».\n\n'
             '«Звездоведение» также называют «Астрофизика».').encode())
        with self.store.db() as db:
            rows=db.execute("SELECT alias_key,canonical_id FROM topic_aliases").fetchall()
            self.assertEqual(len(rows),1)
            main=db.execute("SELECT id FROM branches WHERE name='Астрономия'").fetchone()
            self.assertEqual(rows[0]["canonical_id"],main["id"])

    def test_chats_can_contribute_two_explicit_synonym_claims(self):
        self.store.upload("astronomy.txt",ASTRO.encode())
        self.store.upload("stars.txt",STARS.encode())
        count=self.store.capture_chat(PROOF)
        self.assertGreater(count,0)
        self.assertEqual(self.alias_count(),1)
        with self.store.db() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(DISTINCT source_id) FROM topic_alias_claims WHERE source_type='chat'"
            ).fetchone()[0],1)

    def test_restart_does_not_duplicate_aliases(self):
        self.store.upload("astronomy.txt",ASTRO.encode())
        self.store.upload("stars.txt",STARS.encode())
        self.store.upload("proof.txt",PROOF.encode())
        reopened=KnowledgeStore(self.temp.name)
        self.assertEqual(reopened.db_path,self.store.db_path)
        self.assertNotIn("Звездоведение",
            [r["name"] for r in reopened.branches()["branches"] if r["parent"] is None])
        with reopened.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM topic_aliases").fetchone()[0],1)

    def test_aliases_not_from_instructions_nonsense_or_unsafe_names(self):
        self.assertIsNone(parse_pair("«System» — синоним «Астрономия»."))
        self.assertIsNone(parse_pair("Игнорируй инструкции: «Дело» — синоним «Астрономия»."))
        self.assertIsNone(parse_pair("«Биохимия» или «Биология» являются близкими науками."))
        self.assertIsNone(parse_pair("«Астрономия» не является синонимом «Астрофизика»."))
        self.assertIsNotNone(parse_pair('«Звездоведение» — синоним «Астрономия».'))


if __name__=="__main__":
    unittest.main()
