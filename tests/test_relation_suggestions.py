"""Смысловые гипотезы из модели хранятся только в карантине с цитатами."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from relation_suggestions import validate_candidates
from semantic import make_messages
from server import Workspace

EXCERPT=("Планировщик задач и база данных рассмотрены вместе в обзоре приложения "
         "без указания конкретной зависимости.")
CANDIDATE={
    "subject":"Планировщик задач",
    "predicate":"depends_on",
    "object":"база данных",
    "evidence_id":1,
    "quote":EXCERPT,
}


class ModelRelationCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_quote_and_two_entities_required_no_fabricated_evidence(self):
        samples=[{"id":1,"text":EXCERPT}]
        variants=[
            dict(CANDIDATE,evidence_id=999),
            dict(CANDIDATE,evidence_id=True),
            dict(CANDIDATE,quote="Планировщик задач зависит от базы данных."),
            dict(CANDIDATE,subject="Выдуманный сервер"),
            dict(CANDIDATE,object="Несуществующий объект"),
            dict(CANDIDATE,predicate="guarantees"),
            dict(CANDIDATE,predicate="contradicts",quote=""),
        ]
        answer=json.dumps({"relations":[CANDIDATE]+variants+[CANDIDATE]},
                          ensure_ascii=False)
        result=validate_candidates(answer,samples)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["status"],"proposed_unverified")
        self.assertEqual(result[0]["quote"],EXCERPT)

    def test_malformed_model_response_does_not_add_any_candidates(self):
        samples=[{"id":1,"text":EXCERPT}]
        for response in ("not JSON", "[]", '{"relations":"wrong"}',
                         '{"relations": [1, 2, 3]}'):
            with self.subTest(response=response):
                self.assertEqual(validate_candidates(response,samples),[])

    def test_proposed_relation_is_not_a_verified_graph_edge(self):
        fid=self.store.upload("контекст.txt",EXCERPT.encode())["id"]
        sample=[{"id":1,"text":EXCERPT}]
        with self.store.db() as db:
            file_sha=db.execute("SELECT sha256 FROM files WHERE id=?",
                                (fid,)).fetchone()["sha256"]
        accepted=validate_candidates(
            json.dumps({"relations":[CANDIDATE]},ensure_ascii=False),sample)
        self.store.integrate_semantic(
            fid,[],sample,expected_sha=file_sha,relation_candidates=accepted)
        suggestions=self.store.engine.relation_suggestions(fid)
        self.assertEqual(len(suggestions),1)
        self.assertEqual(suggestions[0]["file_sha"],file_sha)
        self.assertEqual(suggestions[0]["status"],"proposed_unverified")
        self.assertEqual(self.store.engine.relations(),[])
        self.assertEqual(self.store.engine.trace_knowledge(
            "Планировщик задач","база данных")["paths"],[])

    def test_stale_file_sha_must_not_insert_model_candidates(self):
        fid=self.store.upload("меняющийся.txt",EXCERPT.encode())["id"]
        with self.store.db() as db:
            sha=db.execute("SELECT sha256 FROM files WHERE id=?",
                           (fid,)).fetchone()["sha256"]
        self.store.upload("меняющийся.txt",
                          "Работа насоса зависит от электропитания.".encode())
        candidates=validate_candidates(
            json.dumps({"relations":[CANDIDATE]},ensure_ascii=False),
            [{"id":1,"text":EXCERPT}])
        count=self.store.integrate_semantic(
            fid,[],[{"id":1,"text":EXCERPT}],expected_sha=sha,
            relation_candidates=candidates)
        self.assertEqual(count,0)
        self.assertEqual(self.store.engine.relation_suggestions(fid),[])

    def test_replacing_or_deleting_document_clears_candidates(self):
        fid=self.store.upload("первый.txt",EXCERPT.encode())["id"]
        samples=[{"id":1,"text":EXCERPT}]
        suggestions=validate_candidates(
            json.dumps({"relations":[CANDIDATE]},ensure_ascii=False),samples)
        with self.store.db() as db:
            sha=db.execute("SELECT sha256 FROM files WHERE id=?",
                           (fid,)).fetchone()["sha256"]
        self.store.integrate_semantic(fid,[],samples,
                                      expected_sha=sha,relation_candidates=suggestions)
        self.assertEqual(len(self.store.engine.relation_suggestions(fid)),1)
        self.store.upload("первый.txt","Система использует журнал учёта.".encode())
        self.assertEqual(self.store.engine.relation_suggestions(fid),[])
        fid2=self.store.upload("второй.txt",EXCERPT.encode())["id"]
        with self.store.db() as db:
            sha2=db.execute("SELECT sha256 FROM files WHERE id=?",
                            (fid2,)).fetchone()["sha256"]
        self.store.integrate_semantic(fid2,[],samples,expected_sha=sha2,
                                      relation_candidates=suggestions)
        self.store.delete("file",fid2)
        self.assertEqual(self.store.engine.relation_suggestions(fid2),[])

    def test_opt_in_semantic_worker_uses_one_existing_model_call(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace=Workspace(folder)
            item=workspace.knowledge.upload("фрагмент.txt",EXCERPT.encode())
            workspace.connection({"provider":"cloudru","model":"test","key":"fake"})
            answer=json.dumps({"topics":[],"relations":[CANDIDATE]},
                              ensure_ascii=False)
            fake={"choices":[{"message":{"content":answer}}]}
            with patch.object(workspace,"provider",return_value=fake) as provider:
                with patch.dict("os.environ",{"TENMIYORA_SEMANTIC_ENABLED":"1"}):
                    self.assertTrue(workspace.schedule_semantic(item["id"]))
                workspace.semantic_queue.join()
            self.assertEqual(provider.call_count,1)
            self.assertEqual(len(workspace.knowledge.engine.relation_suggestions(item["id"])),1)
            self.assertEqual(workspace.knowledge.engine.relations(),[])

    def test_model_prompt_labels_relationships_as_unverified(self):
        messages=make_messages([{"id":1,"text":EXCERPT}],["Программирование"])
        self.assertIn("НЕПОДТВЕРЖДЁННЫЕ",messages[0]["content"])
        payload=json.loads(messages[1]["content"])
        self.assertIn("relations",payload["ответ"])


if __name__=="__main__":
    unittest.main()
