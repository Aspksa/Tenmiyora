"""Независимые регрессии многошагового графа: направление, пределы, откат."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from knowledge import KnowledgeStore
from knowledge_paths import format_context

PARTS=(
    "«Клапан» является частью «Насос».",
    "«Насос» является частью «Система водоснабжения».",
    "«Система водоснабжения» является частью «Предприятие».",
)


class KnowledgePathTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def upload(self, name, *sentences):
        return self.store.upload(name,("\n\n".join(sentences)).encode("utf-8"))["id"]

    def test_three_steps_with_independent_document_provenance(self):
        ids=[self.upload(f"{i}.txt",sentence) for i,sentence in enumerate(PARTS)]
        result=self.store.engine.trace_knowledge("Клапан","Предприятие")
        self.assertEqual(result["status"],"found")
        self.assertEqual(len(result["paths"]),1)
        path=result["paths"][0]
        self.assertEqual(path["length"],3)
        self.assertEqual(path["interpretation"],"conditional_part_of_chain")
        self.assertFalse(path["verified"])
        for i,step in enumerate(path["steps"]):
            self.assertEqual(step["predicate"],"part_of")
            self.assertEqual(step["sources"][0]["source_id"],ids[i])
            self.assertEqual(step["sources"][0]["evidence"],PARTS[i])
            self.assertIn(f"{i}.txt",step["sources"][0]["locator"])
        self.assertIn("не проверены",format_context(result))

    def test_direction_is_not_reversible(self):
        self.upload("a.txt",*PARTS)
        answer=self.store.engine.trace_knowledge("Предприятие","Клапан")
        self.assertEqual(answer["paths"],[])
        self.assertEqual(answer["status"],"no_path")

    def test_depends_on_and_used_for_remain_only_evidence_chains(self):
        self.upload("mixed.txt",
            "«Отчёт» зависит от «Данные».",
            "«Данные» используется для «Аналитика».")
        answer=self.store.engine.trace_knowledge("Отчёт","Аналитика")
        self.assertEqual(answer["paths"][0]["interpretation"],"related_claims_only")
        self.assertFalse(answer["paths"][0]["verified"])
        self.assertEqual([h["predicate"] for h in answer["paths"][0]["steps"]],
                         ["depends_on","used_for"])

    def test_contradiction_never_transitive(self):
        self.upload("contradicts.txt",
            "«Правило А» противоречит «Правило Б».",
            "«Правило Б» противоречит «Правило В».")
        answer=self.store.engine.trace_knowledge("Правило А","Правило В")
        self.assertEqual(answer["paths"][0]["interpretation"],"related_claims_only")
        self.assertFalse(answer["paths"][0]["verified"])
        self.assertEqual(len(answer["paths"][0]["steps"]),2)

    def test_cycle_cannot_repeat_nodes(self):
        self.upload("cycles.txt",
            "«Компонент А» является частью «Компонент Б».",
            "«Компонент Б» является частью «Компонент В».",
            "«Компонент В» является частью «Компонент А».",
            "«Компонент В» является частью «Комплекс».")
        answer=self.store.engine.trace_knowledge("Компонент А","Комплекс",max_depth=4)
        self.assertTrue(answer["paths"])
        self.assertEqual(answer["paths"][0]["length"],3)
        for path in answer["paths"]:
            nodes=[path["steps"][0]["subject"]]+[s["object"] for s in path["steps"]]
            self.assertEqual(len(nodes),len(set(nodes)))
        self.assertEqual(self.store.engine.trace_knowledge(
            "Компонент А","Компонент А")["paths"],[])

    def test_depth_limit_and_no_guessed_path(self):
        self.upload("four.txt",*PARTS,
            "«Предприятие» является частью «Холдинг».")
        self.assertEqual(self.store.engine.trace_knowledge(
            "Клапан","Холдинг",max_depth=3)["paths"],[])
        result=self.store.engine.trace_knowledge(
            "Клапан","Холдинг",max_depth=4)
        self.assertEqual(result["paths"][0]["length"],4)

    def test_invalid_limits_are_rejected(self):
        self.upload("one.txt",PARTS[0])
        for value in (0,5,True,"4",-1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.store.engine.trace_knowledge("Клапан","Насос",max_depth=value)
        for value in (0,9,False):
            with self.subTest(paths=value):
                with self.assertRaises(ValueError):
                    self.store.engine.trace_knowledge("Клапан","Насос",max_paths=value)

    def test_two_sources_same_hop_are_grouped_with_both_citations(self):
        a=self.upload("a.txt",PARTS[0])
        b=self.upload("b.txt",PARTS[0])
        self.upload("c.txt",PARTS[1])
        path=self.store.engine.trace_knowledge("Клапан","Система водоснабжения")["paths"][0]
        self.assertEqual(path["steps"][0]["evidence_count"],2)
        self.assertEqual({x["source_id"] for x in path["steps"][0]["sources"]},{a,b})

    def test_update_removes_stale_link_but_preserves_unrelated_edges(self):
        a=self.upload("first.txt",PARTS[0])
        b=self.upload("second.txt",PARTS[1])
        self.assertTrue(self.store.engine.trace_knowledge(
            "Клапан","Система водоснабжения")["paths"])
        self.store.upload("second.txt",
            "«Насос» используется для «Очистка воды».".encode("utf-8"))
        self.assertFalse(self.store.engine.trace_knowledge(
            "Клапан","Система водоснабжения")["paths"])
        self.assertTrue(self.store.engine.trace_knowledge(
            "Клапан","Очистка воды")["paths"])
        self.store.delete("file",a)
        self.assertFalse(self.store.engine.trace_knowledge(
            "Клапан","Очистка воды")["paths"])
        self.assertTrue(self.store.engine.relations("Насос"))

    def test_reloaded_database_preserves_paths(self):
        self.upload("first.txt",*PARTS)
        reopened=KnowledgeStore(self.temp.name)
        first=self.store.engine.trace_knowledge("Клапан","Предприятие")
        second=reopened.engine.trace_knowledge("Клапан","Предприятие")
        self.assertEqual(first["paths"],second["paths"])

    def test_explicit_pair_selection_for_chat_and_no_unrelated_queries(self):
        self.upload("first.txt",*PARTS)
        engine=self.store.engine
        self.assertIsNone(engine.contextual_paths("Какие есть связи по базе?"))
        self.assertIsNone(engine.contextual_paths(
            "Как связаны «Клапан», «Предприятие» и «Насос»?"))
        self.assertIsNone(engine.contextual_paths(
            "Как связаны «Выдуманный объект» и «Предприятие»?"))
        trace=engine.contextual_paths("Как связаны «Клапан» и «Предприятие»?")
        self.assertEqual(trace["paths"][0]["length"],3)
        self.assertIn("Клапан",format_context(trace))

    def test_branching_paths_bounded_and_shortest_first(self):
        self.upload("many.txt",
            "«Альфа» является частью «Бета».",
            "«Бета» является частью «Омега».",
            "«Альфа» является частью «Гамма».",
            "«Гамма» является частью «Омега».",
            "«Альфа» является частью «Омега».")
        result=self.store.engine.trace_knowledge("Альфа","Омега",max_paths=2)
        self.assertEqual(len(result["paths"]),2)
        self.assertEqual(result["paths"][0]["length"],1)
        self.assertEqual(result["status"],"incomplete")
        self.assertEqual(result["reason"],"max_paths")


if __name__=="__main__":
    unittest.main()
