"""Test della sincronizzazione (diviconto/sync.py).

Si usa un finto Supabase in memoria che intercetta le richieste HTTP a livello
di ``SyncClient._http``: così la logica reale di push/pull/watermark/auth viene
esercitata, ma senza rete. Un'unica istanza di FakeSupabase fa da "server"
condiviso tra due client con DB locali distinti (due dispositivi).
"""

from __future__ import annotations

import json
import unittest
import urllib.parse
import uuid

from diviconto import core
from diviconto.db import Database
from diviconto.sync import SyncClient, SyncError


class FakeSupabase:
    """Emula il sottoinsieme di Supabase usato da SyncClient (senza RLS)."""

    def __init__(self):
        self.tables = {"trips": {}, "participants": {}, "expenses": {}, "splits": {}}
        self.users = {}        # email -> {"id":..., "password":...}
        self.tokens = {}       # access_token -> email
        self.clock = 0

    def _now(self) -> str:
        self.clock += 1
        return f"2020-01-01T00:00:{self.clock:012d}+00:00"

    # punto d'aggancio: sostituisce SyncClient._http
    def handle(self, method, url, headers, data):
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        body = json.loads(data) if data else None

        if path == "/auth/v1/signup":
            return self._signup(body)
        if path == "/auth/v1/token":
            return self._token(q, body)
        if path == "/rest/v1/rpc/join_trip":
            return self._join(body)
        if path.startswith("/rest/v1/"):
            table = path[len("/rest/v1/"):]
            if method == "POST":
                return self._upsert(table, body)
            if method == "GET":
                return self._select(table, q)
        return self._json(404, {"message": f"non gestito: {method} {path}"})

    # --- auth ---
    def _signup(self, body):
        email = body["email"]
        if email not in self.users:
            self.users[email] = {"id": str(uuid.uuid4()), "password": body["password"]}
        u = self.users[email]
        return self._json(200, {"user": {"id": u["id"], "email": email}})

    def _token(self, q, body):
        grant = q.get("grant_type")
        if grant == "refresh_token":
            return self._session_for(next(iter(self.users)))  # semplificazione
        email = body["email"]
        u = self.users.get(email)
        if not u or u["password"] != body["password"]:
            return self._json(400, {"error_description": "Invalid login credentials"})
        return self._session_for(email)

    def _session_for(self, email):
        u = self.users[email]
        token = "tok-" + u["id"]
        self.tokens[token] = email
        return self._json(200, {
            "access_token": token,
            "refresh_token": "ref-" + u["id"],
            "user": {"id": u["id"], "email": email},
        })

    # --- rest ---
    def _join(self, body):
        code = body["code"]
        for row in self.tables["trips"].values():
            if row.get("share_code") == code:
                return self._json(200, row["id"])
        return self._json(400, {"message": "codice non valido"})

    def _upsert(self, table, rows):
        store = self.tables[table]
        for row in rows:
            existing = store.get(row["id"], {})
            merged = {**existing, **row}
            merged["updated_at"] = self._now()
            if table == "trips" and not merged.get("share_code"):
                merged["share_code"] = uuid.uuid4().hex[:8].upper()
            store[row["id"]] = merged
        return (201, b"")  # return=minimal

    def _select(self, table, q):
        store = self.tables[table]
        rows = list(store.values())
        if "id" in q and q["id"].startswith("eq."):
            wanted = q["id"][3:]
            rows = [r for r in rows if r["id"] == wanted]
        if "updated_at" in q and q["updated_at"].startswith("gt."):
            wm = q["updated_at"][3:]
            rows = [r for r in rows if r["updated_at"] > wm]
        rows.sort(key=lambda r: r["updated_at"])
        return self._json(200, rows)

    @staticmethod
    def _json(status, obj):
        return status, json.dumps(obj).encode("utf-8")


def make_client(server: FakeSupabase) -> SyncClient:
    client = SyncClient(Database(":memory:"), base_url="http://fake", anon_key="anon")
    client._http = server.handle
    return client


def seed_trip(client: SyncClient):
    """Crea su un client un viaggio con un partecipante e una spesa."""
    db = client.db
    trip = core.create_trip(db, "Roma", "EUR", "weekend")
    core.add_participant(db, trip.id, "Anna")
    core.add_participant(db, trip.id, "Bruno")
    core.add_expense(db, trip.id, "Anna", "30.00", description="cena")
    return trip


class SyncTwoClientsTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeSupabase()
        self.a = make_client(self.server)
        self.b = make_client(self.server)
        self.a.signup("a@x.it", "password1")
        self.b.signup("b@x.it", "password2")

    def tearDown(self):
        self.a.db.close()
        self.b.db.close()

    def test_push_then_pull_propagates_data(self):
        trip = seed_trip(self.a)
        self.a.sync()

        self.b.sync()
        b_trips = self.b.db.list_trips()
        self.assertEqual([t.name for t in b_trips], ["Roma"])
        self.assertEqual(
            sorted(p.name for p in self.b.db.list_participants(trip.id)),
            ["Anna", "Bruno"],
        )
        b_exp = self.b.db.list_expenses(trip.id)
        self.assertEqual(len(b_exp), 1)
        self.assertEqual(str(b_exp[0].amount), "30.00")
        self.assertEqual(len(b_exp[0].splits), 2)

    def test_pulled_rows_are_not_dirty(self):
        seed_trip(self.a)
        self.a.sync()
        self.b.sync()
        # Le righe scaricate non devono essere rispedite: niente dirty su B.
        for table in ("trips", "participants", "expenses", "splits"):
            self.assertEqual(self.b.db.dirty_rows(table), [], table)

    def test_incremental_second_change(self):
        trip = seed_trip(self.a)
        self.a.sync()
        self.b.sync()
        # Nuova spesa su A, poi sync su entrambi.
        core.add_expense(self.a.db, trip.id, "Bruno", "10.00", description="taxi")
        self.a.sync()
        self.b.sync()
        self.assertEqual(len(self.b.db.list_expenses(trip.id)), 2)

    def test_last_write_wins(self):
        trip = seed_trip(self.a)
        self.a.sync()
        self.b.sync()
        # A rinomina il viaggio, poi B lo rinomina diversamente (più tardi).
        self._rename(self.a.db, trip.id, "Roma-A")
        self.a.sync()
        self._rename(self.b.db, trip.id, "Roma-B")
        self.b.sync()      # B vince: ha l'updated_at server più recente
        self.a.sync()      # A converge sul valore di B
        self.assertEqual(self.a.db.get_trip(trip.id).name, "Roma-B")
        self.assertEqual(self.b.db.get_trip(trip.id).name, "Roma-B")

    def test_deleted_propagates(self):
        trip = seed_trip(self.a)
        self.a.sync()
        self.b.sync()
        self.a.db.conn.execute(
            "UPDATE trips SET deleted = 1, dirty = 1 WHERE id = ?", (trip.id,)
        )
        self.a.db.conn.commit()
        self.a.sync()
        self.b.sync()
        self.assertEqual(self.b.db.list_trips(), [])

    def test_join_trip_with_code(self):
        trip = seed_trip(self.a)
        self.a.sync()
        code = self.a.share_code(trip.id)
        self.assertTrue(code)
        returned = self.b.join_trip(code)
        self.assertEqual(returned, trip.id)
        self.assertEqual([t.name for t in self.b.db.list_trips()], ["Roma"])

    @staticmethod
    def _rename(db, trip_id, name):
        db.conn.execute(
            "UPDATE trips SET name = ?, dirty = 1 WHERE id = ?", (name, trip_id)
        )
        db.conn.commit()


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeSupabase()
        self.client = make_client(self.server)

    def tearDown(self):
        self.client.db.close()

    def test_login_wrong_password_raises(self):
        self.client.signup("u@x.it", "rightpass")
        self.client.logout()
        with self.assertRaises(SyncError):
            self.client.login("u@x.it", "wrongpass")

    def test_sync_requires_login(self):
        with self.assertRaises(SyncError):
            self.client.sync()


if __name__ == "__main__":
    unittest.main()
