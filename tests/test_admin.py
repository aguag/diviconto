"""Test dei comandi di amministrazione cloud (diviconto/admin.py).

Niente rete: si sostituisce ``AdminClient._request`` con uno stub che registra
le chiamate e restituisce dati finti. Verifica le sicurezze (dry-run, soft vs
hard, purge-user via RPC) e la persistenza della sessione admin.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import tempfile
import unittest

from diviconto.admin import AdminClient


class FakeAdmin(AdminClient):
    """AdminClient con ``_request`` finto: registra le chiamate, niente rete/sessione."""

    def __init__(self):
        self.base = "http://fake"
        self.anon = "anon"
        self.token = "tok"
        self.refresh_token = None
        self.email = "admin@x.it"
        self.calls = []
        self._tables = {
            "/rest/v1/trips": [{"id": "t1", "name": "Roma", "owner_id": "u1"}],
            "/rest/v1/expenses": [{"id": "e1"}],
            "/rest/v1/participants": [{"id": "p1"}],
        }
        self._users = [{"id": "u1", "email": "a@x.it", "created_at": "2020"}]

    def _request(self, method, path, params=None, body=None, auth=True, _retry=True):
        self.calls.append((method, path, params, body))
        if path.startswith("/rest/v1/rpc/"):
            name = path[len("/rest/v1/rpc/"):]
            if name == "am_i_admin":
                return True
            if name == "admin_list_users":
                return self._users
            return None
        if method == "GET":
            return self._tables.get(path, [])
        return None

    def mutations(self):
        return [(m, p) for m, p, _params, _body in self.calls if m in ("PATCH", "DELETE")]

    def rpc_calls(self):
        return [p for m, p, _params, _body in self.calls if p.startswith("/rest/v1/rpc/")]


def _silent(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


class AdminPurgeTripTest(unittest.TestCase):
    def test_dry_run_makes_no_mutations(self):
        c = FakeAdmin()
        _silent(c.purge_trips, ["t1"], do_it=False)
        self.assertEqual(c.mutations(), [])

    def test_soft_delete_uses_patch(self):
        c = FakeAdmin()
        _silent(c.purge_trips, ["t1"], do_it=True, hard=False)
        muts = c.mutations()
        self.assertTrue(muts)
        self.assertTrue(all(m == "PATCH" for m, _ in muts), muts)
        self.assertIn(("PATCH", "/rest/v1/trips"), muts)

    def test_hard_delete_uses_delete(self):
        c = FakeAdmin()
        _silent(c.purge_trips, ["t1"], do_it=True, hard=True)
        muts = c.mutations()
        self.assertTrue(muts)
        self.assertTrue(all(m == "DELETE" for m, _ in muts), muts)
        self.assertIn(("DELETE", "/rest/v1/trips"), muts)

    def test_missing_trip_is_skipped(self):
        c = FakeAdmin()
        c._tables["/rest/v1/trips"] = []
        _silent(c.purge_trips, ["x"], do_it=True)
        self.assertEqual(c.mutations(), [])


class AdminPurgeUserTest(unittest.TestCase):
    def test_hard_delegates_to_rpc(self):
        c = FakeAdmin()
        _silent(c.purge_user, "a@x.it", do_it=True, hard=True)
        self.assertIn("/rest/v1/rpc/admin_delete_user", c.rpc_calls())
        # niente DELETE diretti sulle tabelle: fa tutto la RPC lato server
        self.assertEqual([m for m, _ in c.mutations()], [])

    def test_soft_keeps_user_and_soft_deletes_trips(self):
        c = FakeAdmin()
        _silent(c.purge_user, "a@x.it", do_it=True, hard=False)
        self.assertNotIn("/rest/v1/rpc/admin_delete_user", c.rpc_calls())
        self.assertTrue(all(m == "PATCH" for m, _ in c.mutations()), c.mutations())

    def test_unknown_user_does_nothing(self):
        c = FakeAdmin()
        _silent(c.purge_user, "nope@x.it", do_it=True, hard=True)
        self.assertEqual(c.rpc_calls().count("/rest/v1/rpc/admin_delete_user"), 0)


class AdminSessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["DIVICONTO_ADMIN_SESSION"] = os.path.join(self.tmp, "sess.json")

    def tearDown(self):
        os.environ.pop("DIVICONTO_ADMIN_SESSION", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_session_not_logged_in(self):
        self.assertFalse(AdminClient(base_url="http://fake", anon_key="anon").is_logged_in())

    def test_store_persists_and_reloads(self):
        c = AdminClient(base_url="http://fake", anon_key="anon")
        c._store({"access_token": "tok", "refresh_token": "ref",
                  "user": {"email": "a@x.it"}})
        # un nuovo client rilegge la sessione dal file
        c2 = AdminClient(base_url="http://fake", anon_key="anon")
        self.assertTrue(c2.is_logged_in())
        self.assertEqual(c2.email, "a@x.it")
        c2.logout()
        self.assertFalse(AdminClient(base_url="http://fake", anon_key="anon").is_logged_in())


if __name__ == "__main__":
    unittest.main()
