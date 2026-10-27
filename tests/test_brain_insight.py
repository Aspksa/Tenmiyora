"""Понимание проекта: досье, карта денег и предчувствия по явным правилам с цитатами."""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bootstrap"))
from knowledge import KnowledgeStore
from brain_insight import amount_value, AMOUNT, dates_in, entities_in, insight, nominative

TODAY = date(2026, 10, 27)
CONTRACT = """Договор поставки № 15 от 01.09.2026

ООО «Ромашка», именуемое в дальнейшем «Покупатель», в лице генерального директора Иванова Петра Сергеевича, и ООО «Вектор», именуемое в дальнейшем «Поставщик», заключили настоящий договор.

Покупатель обязуется оплатить Поставщику 1 200 000 (Один миллион двести тысяч) рублей 00 копеек за поставку щебня не позднее 20.10.2026.
В том числе НДС 200 000 руб.
Поставщик обязан поставить товар до 05.11.2026 на автомобиле КамАЗ 65115 гос. номер А123ВС77, водитель Петров С. Н.
Договор действует до 15.11.2026 и продлевается автоматически.
Оплата по счёту № 7 от 10.09.2026 производится на расчётный счёт № 40702810900000012345.
"""
INVOICE = "Счёт № 7 от 10.09.2026 по договору № 15. Сумма 1 200 000 руб."


class BrainInsightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_insight(self):
        with self.store.db() as db:
            return insight(db, today=TODAY)

    def test_parsers(self):
        self.assertEqual(amount_value(AMOUNT.search("1 200 000 (Один миллион двести тысяч) рублей")), 1200000)
        self.assertEqual(amount_value(AMOUNT.search("2,5 млн руб.")), 2500000)
        self.assertEqual(amount_value(AMOUNT.search("45 тыс. ₽")), 45000)
        self.assertIsNone(AMOUNT.search("неустойка 0,1% за каждый день"))
        self.assertEqual(dates_in("до 5 ноября 2026 и 2026-12-01"), [date(2026, 11, 5), date(2026, 12, 1)])
        self.assertEqual(nominative("Иванова", "Петра", "Сергеевича"), ("Иванов", "Петр", "Сергеевич"))
        self.assertEqual(nominative("Петровой", "Анны", "Ивановны"), ("Петрова", "Анна", "Ивановна"))
        kinds = {kind: name for _, kind, name, _ in entities_in("ООО «Вектор» и Сидоров А. В. на КамАЗ А123ВС77")}
        self.assertEqual(kinds, {"company": "ООО «Вектор»", "person": "Сидоров А. В.", "vehicle": "КамАЗ · А123ВС77"})
        # Реквизиты банка — не документ «счёт».
        self.assertFalse([e for e in entities_in("на расчётный счёт № 40702810900000012345") if e[1] == "contract"])

    def test_empty_project(self):
        data = self.run_insight()
        self.assertEqual(data["dossiers"], [])
        self.assertEqual(data["money"]["total"], 0)
        self.assertEqual(data["foresight"]["items"], [])

    def test_dossiers_money_and_foresight(self):
        self.store.upload("Договор 15.txt", CONTRACT.encode())
        self.store.upload("Счёт 7.txt", INVOICE.encode())
        data = self.run_insight()
        by_name = {d["name"]: d for d in data["dossiers"]}
        buyer = by_name["ООО «Ромашка»"]
        self.assertEqual(buyer["roles"], ["Покупатель"])
        self.assertIn("ООО «Вектор»", [link["name"] for link in buyer["links"]])
        self.assertIn("Иванов Петр Сергеевич", by_name)
        self.assertIn("КамАЗ 65115 · А123ВС77", by_name)
        self.assertEqual(by_name["Договор № 15"]["money"], 1200000)
        for dossier in data["dossiers"]:
            for item in dossier["chronology"]:
                self.assertTrue(item["quote"] and item["name"])

        money = data["money"]
        # Сумма договора и та же сумма в счёте по нему — один платёж; НДС отдельно.
        self.assertEqual(money["total"], 1200000)
        self.assertEqual(money["overdue"], 1200000)
        self.assertEqual(money["flows"], [{"from": "ООО «Ромашка»", "to": "ООО «Вектор»", "amount": 1200000,
                                           "count": 1, "overdue": 1, "paid": 0}])
        self.assertIn("vat", {row["kind"] for row in money["items"]})

        titles = [item["title"] for item in data["foresight"]["items"]]
        self.assertEqual(data["foresight"]["items"][0]["level"], "critical")
        self.assertTrue(any("1 200 000 ₽ просрочен" in t for t in titles))
        self.assertTrue(any(t.startswith("Срок поставки 05.11.2026") for t in titles))
        self.assertTrue(any(t.startswith("Истекает срок действия 15.11.2026") for t in titles))
        self.assertTrue(any("есть счёт № 7, но нет акта" in t for t in titles))
        for item in data["foresight"]["items"]:
            self.assertTrue(item["quote"] and item["source"]["name"])

    def test_payment_mark_and_budget_mentions(self):
        self.store.upload("Акт.txt", ("Акт № 21 от 30.09.2026 по договору № 9.\n"
            "Заказчик ООО «Ромашка» перечислило ООО «ТрансЛайн» 340 000 руб. за перевозку.\n").encode())
        self.store.upload("Бюджет.txt", "Бюджет на 2026 год предусматривает доход 12 млн рублей.".encode())
        data = self.run_insight()
        money = data["money"]
        self.assertEqual(money["paid"], 340000)
        self.assertEqual(money["total"], 340000)
        self.assertEqual([row["kind"] for row in money["items"] if row["amount"] == 12e6], ["mention"])
        self.assertFalse([i for i in data["foresight"]["items"] if i["kind"] == "overdue"])

    def test_store_cache_follows_new_documents(self):
        first = self.store.brain_insight()
        self.assertIs(first, self.store.brain_insight())
        self.store.upload("Договор 15.txt", CONTRACT.encode())
        self.assertTrue(self.store.brain_insight()["dossiers"])

    def test_negated_payment_is_not_paid(self):
        self.store.upload("Договор.txt", "Договор № 15. Сумма 100 000 руб. не оплачена.".encode())
        self.assertEqual(self.run_insight()["money"]["paid"], 0)

    def test_payment_in_another_sentence_closes_overdue_alert(self):
        self.store.upload("Договор.txt", ("Договор № 15.\n"
            "Покупатель обязуется оплатить Поставщику 100 000 руб. до 20.10.2026.\n"
            "Покупатель перечислил Поставщику 100 000 руб. по договору № 15.\n").encode())
        data = self.run_insight()
        self.assertEqual(data["money"]["paid"], 100000)
        self.assertFalse([i for i in data["foresight"]["items"] if i["kind"] == "overdue"])

    def test_budget_in_contract_file_is_not_a_payment(self):
        self.store.upload("Договор.txt", ("Договор № 15.\nБюджет проекта составляет 12 млн рублей.\n"
            "Покупатель обязуется оплатить Поставщику 100 000 руб. до 20.11.2026.\n").encode())
        self.assertEqual(self.run_insight()["money"]["total"], 100000)

    def test_same_sum_and_date_in_two_contracts_are_two_alerts(self):
        for number in (15, 16):
            self.store.upload(f"Договор {number}.txt", (f"Договор № {number}.\n"
                "Покупатель обязуется оплатить Поставщику 100 000 руб. до 20.10.2026.\n").encode())
        data = self.run_insight()
        self.assertEqual(data["money"]["overdue"], 200000)
        self.assertEqual(data["foresight"]["counts"]["critical"], 2)

    def test_edited_document_refreshes_cache(self):
        result = self.store.upload("Договор.txt", "Договор № 15. Сумма 100 000 руб.".encode())
        self.assertEqual(self.store.brain_insight()["money"]["total"], 100000)
        self.store.save_text(result["id"], "Договор № 15. Сумма 200 000 руб.")
        self.assertEqual(self.store.brain_insight()["money"]["total"], 200000)


if __name__ == "__main__":
    unittest.main()
