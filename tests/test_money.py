import unittest
from decimal import Decimal

from src.money import convert, format_money, to_money, to_rate


class TestMoney(unittest.TestCase):
    def test_to_money_rounds_half_up(self):
        self.assertEqual(to_money("1.005"), Decimal("1.01"))
        self.assertEqual(to_money(2), Decimal("2.00"))
        self.assertEqual(to_money(0.1) + to_money(0.2), Decimal("0.30"))

    def test_to_money_invalid(self):
        with self.assertRaises(ValueError):
            to_money("abc")

    def test_to_rate_positive(self):
        self.assertEqual(to_rate("0.92"), Decimal("0.92"))
        with self.assertRaises(ValueError):
            to_rate("0")
        with self.assertRaises(ValueError):
            to_rate("-1")

    def test_convert(self):
        self.assertEqual(convert(Decimal("50.00"), Decimal("0.92")), Decimal("46.00"))

    def test_format_money(self):
        self.assertEqual(format_money(Decimal("12.5"), "EUR"), "12.50 EUR")
        self.assertEqual(format_money(Decimal("12.5")), "12.50")


if __name__ == "__main__":
    unittest.main()
