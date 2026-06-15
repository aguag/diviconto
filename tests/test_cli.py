import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCliEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name

    def tearDown(self):
        os.unlink(self.db)

    def run_cli(self, *args):
        cmd = [sys.executable, "-m", "diviconto", "--db", self.db, *args]
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)

    def test_help(self):
        r = self.run_cli("-h")
        self.assertEqual(r.returncode, 0)
        self.assertIn("DiviConto", r.stdout)

    def test_full_flow(self):
        self.assertEqual(self.run_cli("trip", "create", "--name", "Spagna",
                                      "--currency", "EUR").returncode, 0)
        self.run_cli("person", "add", "--trip", "Spagna", "--name", "Anna")
        self.run_cli("person", "add", "--trip", "Spagna", "--name", "Bob")
        self.run_cli("expense", "add", "--trip", "Spagna", "--payer", "Anna",
                     "--amount", "100", "--desc", "Cena", "--split", "equal")
        r = self.run_cli("balance", "--trip", "Spagna")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Bob deve dare 50.00 EUR a Anna", r.stdout)

    def test_error_exit_code(self):
        r = self.run_cli("person", "add", "--trip", "Inesistente", "--name", "X")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Errore", r.stderr)


if __name__ == "__main__":
    unittest.main()
