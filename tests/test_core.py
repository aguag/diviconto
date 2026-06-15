import unittest
from decimal import Decimal

from diviconto.core import SplitSpec, add_expense, add_participant, compute_balance, create_trip
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


class TestEqualSplit(CoreTestBase):
    def test_equal_split_two(self):
        add_expense(self.db, "Spagna", "Anna", "100", split=SplitSpec("equal"))
        net = self.net()
        # Anna ha pagato 100, ciascuno deve 50 -> Anna +50, Bob -50
        self.assertEqual(net["Anna"], Decimal("50.00"))
        self.assertEqual(net["Bob"], Decimal("-50.00"))

    def test_net_sums_to_zero_odd_amount(self):
        add_participant(self.db, "Spagna", "Cleo")
        add_expense(self.db, "Spagna", "Anna", "100", split=SplitSpec("equal"))
        net = self.net()
        self.assertEqual(sum(net.values()), Decimal("0.00"))

    def test_equal_subset(self):
        add_participant(self.db, "Spagna", "Cleo")
        add_expense(self.db, "Spagna", "Anna", "100",
                    split=SplitSpec("equal", names=["Anna", "Bob"]))
        net = self.net()
        self.assertEqual(net["Cleo"], Decimal("0.00"))
        self.assertEqual(net["Anna"], Decimal("50.00"))
        self.assertEqual(net["Bob"], Decimal("-50.00"))


class TestExactSplit(CoreTestBase):
    def test_exact_split(self):
        add_expense(self.db, "Spagna", "Anna", "60",
                    split=SplitSpec("exact", amounts={"Anna": Decimal("40"), "Bob": Decimal("20")}))
        net = self.net()
        self.assertEqual(net["Anna"], Decimal("20.00"))   # pagato 60, doveva 40
        self.assertEqual(net["Bob"], Decimal("-20.00"))

    def test_exact_sum_mismatch(self):
        with self.assertRaises(ValueError):
            add_expense(self.db, "Spagna", "Anna", "60",
                        split=SplitSpec("exact", amounts={"Anna": Decimal("40"), "Bob": Decimal("10")}))


class TestCurrency(CoreTestBase):
    def test_foreign_currency_requires_rate(self):
        with self.assertRaises(ValueError):
            add_expense(self.db, "Spagna", "Anna", "50", currency="USD")

    def test_foreign_currency_converted(self):
        add_expense(self.db, "Spagna", "Bob", "50", currency="USD", rate="0.92",
                    split=SplitSpec("equal"))
        # 50 USD * 0.92 = 46 EUR, diviso 2 = 23 ciascuno
        net = self.net()
        self.assertEqual(net["Bob"], Decimal("23.00"))
        self.assertEqual(net["Anna"], Decimal("-23.00"))


class TestSettlement(CoreTestBase):
    def test_settlement_balances(self):
        add_participant(self.db, "Spagna", "Cleo")
        add_expense(self.db, "Spagna", "Anna", "90", split=SplitSpec("equal"))
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
            add_expense(self.db, "Spagna", "Anna", "-5", split=SplitSpec("equal"))


if __name__ == "__main__":
    unittest.main()
