import unittest
from decimal import Decimal

from diviconto.core import (
    SplitSpec, add_expense, add_participant, compute_balance, create_trip,
    delete_expense, delete_participant, rename_participant, update_expense,
    update_expense_description,
)
from diviconto.db import Database


class CoreTestBase(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.trip = create_trip(self.db, "Spagna", "EUR", "test")
        add_participant(self.db, "Spagna", "Anna")
        add_participant(self.db, "Spagna", "Bob")

    def tearDown(self):
        self.db.close()

    def net(self):
        return compute_balance(self.db, "Spagna").net


class TestUpdateExpense(CoreTestBase):
    def test_equal_to_exact(self):
        e = add_expense(self.db, "Spagna", "Anna", "100", description="cena",
                        split=SplitSpec("equal"))
        update_expense(self.db, e.id, "Anna", "100", description="cena",
                       split=SplitSpec("exact", amounts={"Anna": Decimal("70"),
                                                         "Bob": Decimal("30")}))
        net = self.net()
        self.assertEqual(net["Anna"], Decimal("30.00"))   # paga 100, deve 70
        self.assertEqual(net["Bob"], Decimal("-30.00"))
        exps = self.db.list_expenses(self.trip.id)
        self.assertEqual(len(exps), 1)          # è un aggiornamento, non una nuova spesa
        self.assertEqual(exps[0].id, e.id)
        self.assertEqual(exps[0].splits[0].mode, "exact")

    def test_exact_sum_mismatch_raises(self):
        e = add_expense(self.db, "Spagna", "Anna", "100", description="cena",
                        split=SplitSpec("equal"))
        with self.assertRaises(ValueError):
            update_expense(self.db, e.id, "Anna", "100", description="cena",
                           split=SplitSpec("exact", amounts={"Anna": Decimal("70"),
                                                             "Bob": Decimal("20")}))


class TestDeleteParticipant(CoreTestBase):
    def test_rename(self):
        rename_participant(self.db, "Spagna", "Bob", "Roberto")
        names = [p.name for p in self.db.list_participants(self.trip.id)]
        self.assertIn("Roberto", names)
        self.assertNotIn("Bob", names)

    def test_rename_duplicate_raises(self):
        with self.assertRaises(ValueError):
            rename_participant(self.db, "Spagna", "Bob", "Anna")

    def test_delete_non_payer_redistributes_share(self):
        add_participant(self.db, "Spagna", "Cleo")
        add_expense(self.db, "Spagna", "Anna", "90", description="cena", split=SplitSpec("equal"))
        delete_participant(self.db, "Spagna", "Cleo")
        net = self.net()
        self.assertNotIn("Cleo", net)
        self.assertEqual(net["Anna"], Decimal("45.00"))   # 90 - 45
        self.assertEqual(net["Bob"], Decimal("-45.00"))
        self.assertEqual(sum(net.values()), Decimal("0.00"))

    def test_delete_payer_splits_and_washes_out(self):
        add_participant(self.db, "Spagna", "Cleo")
        add_expense(self.db, "Spagna", "Anna", "90", description="cena", split=SplitSpec("equal"))
        delete_participant(self.db, "Spagna", "Anna")  # Anna è il pagante
        net = self.net()
        self.assertNotIn("Anna", net)
        self.assertEqual(net["Bob"], Decimal("0.00"))
        self.assertEqual(net["Cleo"], Decimal("0.00"))
        # spesa pagata da Anna spezzata in 2 voci (una per pagante rimanente)
        self.assertEqual(len(self.db.list_expenses(self.trip.id)), 2)

    def test_delete_payer_two_people(self):
        add_expense(self.db, "Spagna", "Anna", "100", description="cena", split=SplitSpec("equal"))
        delete_participant(self.db, "Spagna", "Anna")
        net = self.net()
        self.assertEqual(net["Bob"], Decimal("0.00"))
        exps = self.db.list_expenses(self.trip.id)
        self.assertEqual(len(exps), 1)
        bob = self.db.get_participant_by_name(self.trip.id, "Bob")
        self.assertEqual(exps[0].payer_id, bob.id)


class TestEqualSplit(CoreTestBase):
    def test_equal_split_two(self):
        add_expense(self.db, "Spagna", "Anna", "100", description="cena",
                    split=SplitSpec("equal"))
        net = self.net()
        # Anna ha pagato 100, ciascuno deve 50 -> Anna +50, Bob -50
        self.assertEqual(net["Anna"], Decimal("50.00"))
        self.assertEqual(net["Bob"], Decimal("-50.00"))

    def test_net_sums_to_zero_odd_amount(self):
        add_participant(self.db, "Spagna", "Cleo")
        add_expense(self.db, "Spagna", "Anna", "100", description="cena",
                    split=SplitSpec("equal"))
        net = self.net()
        self.assertEqual(sum(net.values()), Decimal("0.00"))

    def test_equal_subset(self):
        add_participant(self.db, "Spagna", "Cleo")
        add_expense(self.db, "Spagna", "Anna", "100", description="cena",
                    split=SplitSpec("equal", names=["Anna", "Bob"]))
        net = self.net()
        self.assertEqual(net["Cleo"], Decimal("0.00"))
        self.assertEqual(net["Anna"], Decimal("50.00"))
        self.assertEqual(net["Bob"], Decimal("-50.00"))


class TestExactSplit(CoreTestBase):
    def test_exact_split(self):
        add_expense(self.db, "Spagna", "Anna", "60", description="hotel",
                    split=SplitSpec("exact", amounts={"Anna": Decimal("40"), "Bob": Decimal("20")}))
        net = self.net()
        self.assertEqual(net["Anna"], Decimal("20.00"))   # pagato 60, doveva 40
        self.assertEqual(net["Bob"], Decimal("-20.00"))

    def test_exact_sum_mismatch(self):
        with self.assertRaises(ValueError):
            add_expense(self.db, "Spagna", "Anna", "60", description="hotel",
                        split=SplitSpec("exact", amounts={"Anna": Decimal("40"), "Bob": Decimal("10")}))


class TestCurrency(CoreTestBase):
    def test_foreign_currency_requires_rate(self):
        with self.assertRaises(ValueError):
            add_expense(self.db, "Spagna", "Anna", "50", description="benzina",
                        currency="USD")

    def test_foreign_currency_converted(self):
        add_expense(self.db, "Spagna", "Bob", "50", description="benzina",
                    currency="USD", rate="0.92", split=SplitSpec("equal"))
        # 50 USD * 0.92 = 46 EUR, diviso 2 = 23 ciascuno
        net = self.net()
        self.assertEqual(net["Bob"], Decimal("23.00"))
        self.assertEqual(net["Anna"], Decimal("-23.00"))


class TestSettlement(CoreTestBase):
    def test_settlement_balances(self):
        add_participant(self.db, "Spagna", "Cleo")
        add_expense(self.db, "Spagna", "Anna", "90", description="cena",
                    split=SplitSpec("equal"))
        bal = compute_balance(self.db, "Spagna")
        # ricostruisce i netti applicando i pagamenti: devono azzerarsi
        net = dict(bal.net)
        for s in bal.settlements:
            net[s.debtor] += s.amount
            net[s.creditor] -= s.amount
        for v in net.values():
            self.assertEqual(v, Decimal("0.00"))


class TestValidation(CoreTestBase):
    def test_duplicate_participant(self):
        with self.assertRaises(ValueError):
            add_participant(self.db, "Spagna", "Anna")

    def test_unknown_trip(self):
        with self.assertRaises(ValueError):
            add_participant(self.db, "Nessuno", "X")

    def test_negative_amount(self):
        with self.assertRaises(ValueError):
            add_expense(self.db, "Spagna", "Anna", "-5", description="x",
                        split=SplitSpec("equal"))

    def test_description_required(self):
        with self.assertRaises(ValueError):
            add_expense(self.db, "Spagna", "Anna", "10", description="",
                        split=SplitSpec("equal"))
        with self.assertRaises(ValueError):
            add_expense(self.db, "Spagna", "Anna", "10", description="   ",
                        split=SplitSpec("equal"))


class TestEditDelete(CoreTestBase):
    def _add(self, desc="cena"):
        return add_expense(self.db, "Spagna", "Anna", "100", description=desc,
                           split=SplitSpec("equal"))

    def test_delete_expense_removes_from_balance(self):
        exp = self._add()
        self.assertEqual(self.net()["Anna"], Decimal("50.00"))
        delete_expense(self.db, exp.id)
        # spesa sparita dalla lista e dal bilancio (tutti a zero)
        self.assertEqual(self.db.list_expenses(self.trip.id), [])
        self.assertEqual(self.net()["Anna"], Decimal("0.00"))

    def test_delete_marks_dirty(self):
        exp = self._add()
        self.db.mark_clean("expenses", [exp.id])
        delete_expense(self.db, exp.id)
        ids = [r["id"] for r in self.db.dirty_rows("expenses")]
        self.assertIn(exp.id, ids)

    def test_update_description(self):
        exp = self._add(desc="vecchia")
        update_expense_description(self.db, exp.id, "nuova")
        got = self.db.list_expenses(self.trip.id)[0]
        self.assertEqual(got.description, "nuova")

    def test_update_description_empty_rejected(self):
        exp = self._add()
        with self.assertRaises(ValueError):
            update_expense_description(self.db, exp.id, "  ")


if __name__ == "__main__":
    unittest.main()
