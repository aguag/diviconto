"""Test della localizzazione (diviconto/i18n.py)."""

from __future__ import annotations

import os
import unittest

from diviconto import i18n


class I18nTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("it")  # ripristina il default per gli altri test

    def test_italian_is_identity(self):
        i18n.set_language("it")
        self.assertEqual(i18n.tr("Accedi"), "Accedi")

    def test_english_translation(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("Accedi"), "Sign in")

    def test_missing_key_falls_back_to_source(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("Stringa senza traduzione XYZ"),
                         "Stringa senza traduzione XYZ")

    def test_template_placeholder(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("Rimosso {email}").format(email="a@x.it"),
                         "Removed a@x.it")

    def test_unsupported_language_uses_fallback(self):
        i18n.set_language("fr")
        self.assertEqual(i18n.get_language(), "en")

    def test_resolve_explicit_wins_over_saved(self):
        self.assertEqual(i18n.resolve_language(saved="it", explicit="en"), "en")

    def test_resolve_env_over_saved(self):
        os.environ["DIVICONTO_LANG"] = "en"
        try:
            self.assertEqual(i18n.resolve_language(saved="it"), "en")
        finally:
            del os.environ["DIVICONTO_LANG"]

    def test_resolve_saved_over_device(self):
        os.environ.pop("DIVICONTO_LANG", None)
        self.assertEqual(i18n.resolve_language(saved="en"), "en")


if __name__ == "__main__":
    unittest.main()
