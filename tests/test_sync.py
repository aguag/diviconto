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
        self.members = {}      # trip_id -> {email: role}
        self.clock = 0
        self._current_email = None  # utente della richiesta corrente (dal token)

    def _email_for(self, uid):
        for email, u in self.users.items():
            if u["id"] == uid:
                return email
        return None

    def _now(self) -> str:
        self.clock += 1
        return f"2020-01-01T00:00:{self.clock:012d}+00:00"

    # punto d'aggancio: sostituisce SyncClient._http
    def handle(self, method, url, headers, data):
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        body = json.loads(data) if data else None

        auth = headers.get("Authorization", "")
        token = auth[len("Bearer "):] if auth.startswith("Bearer ") else None
        self._current_email = self.tokens.get(token)

        if path == "/auth/v1/signup":
            return self._signup(body)
        if path == "/auth/v1/token":
            return self._token(q, body)
        if path == "/rest/v1/rpc/join_trip":
            return self._join(body)
        if path == "/rest/v1/rpc/leave_trip":
            return self._leave(body)
        if path == "/rest/v1/rpc/remove_member":
            return self._remove_member(body)
        if path == "/rest/v1/rpc/revoke_sharing":
            return self._revoke(body)
        if path == "/rest/v1/trip_members":
            return self._select_members()
        if path.startswith("/rest/v1/"):
            table = path[len("/rest/v1/"):]
            if method == "POST":
                return self._upsert(table, body)
            if method == "GET":
                return self._select(table, q)
        return self._json(404, {"message": f"non gestito: {method} {path}"})

    def _select_members(self):
        rows = [
            {"trip_id": tid, "email": email, "role": role}
            for tid, members in self.members.items()
            for email, role in members.items()
        ]
        return self._json(200, rows)

    # --- gestione condivisione/appartenenza ---
    def _is_owner(self, tid, email):
        trip = self.tables["trips"].get(tid)
        return bool(trip and email and trip.get("owner_id") == self._email_for_id(email))

    def _email_for_id(self, email):
        u = self.users.get(email)
        return u["id"] if u else None

    def _leave(self, body):
        tid, email = body["tid"], self._current_email
        if self._is_owner(tid, email):
            return self._json(400, {"message": "owner non può abbandonare"})
        self.members.get(tid, {}).pop(email, None)
        return (204, b"")

    def _remove_member(self, body):
        tid, email = body["tid"], self._current_email
        if not self._is_owner(tid, email):
            return self._json(400, {"message": "solo il proprietario"})
        self.members.get(tid, {}).pop(body["member_email"], None)
        return (204, b"")

    def _revoke(self, body):
        tid, email = body["tid"], self._current_email
        if not self._is_owner(tid, email):
            return self._json(400, {"message": "solo il proprietario"})
        self.members[tid] = {email: "owner"}
        newcode = uuid.uuid4().hex[:8].upper()
        self.tables["trips"][tid]["share_code"] = newcode
        return self._json(200, newcode)

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
                if self._current_email:
                    self.members.setdefault(row["id"], {})[self._current_email] = "member"
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
            if table == "trips":  # il creatore è owner (come il trigger server)
                owner_email = self._email_for(row.get("owner_id"))
                if owner_email:
                    self.members.setdefault(row["id"], {}).setdefault(owner_email, "owner")
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

    def test_expense_delete_propagates(self):
        trip = seed_trip(self.a)
        self.a.sync()
        self.b.sync()
        self.assertEqual(len(self.b.db.list_expenses(trip.id)), 1)
        exp = self.a.db.list_expenses(trip.id)[0]
        core.delete_expense(self.a.db, exp.id)
        self.a.sync()
        self.b.sync()
        self.assertEqual(self.b.db.list_expenses(trip.id), [])

    def test_join_trip_with_code(self):
        trip = seed_trip(self.a)
        self.a.sync()
        code = self.a.share_code(trip.id)
        self.assertTrue(code)
        returned = self.b.join_trip(code)
        self.assertEqual(returned, trip.id)
        self.assertEqual([t.name for t in self.b.db.list_trips()], ["Roma"])

    def test_join_older_trip_after_own_sync(self):
        # A crea il viaggio (updated_at "vecchio").
        trip = seed_trip(self.a)
        self.a.sync()
        code = self.a.share_code(trip.id)
        # Simula che B abbia già sincronizzato dati propri più recenti: i suoi
        # watermark sono avanti rispetto all'updated_at del viaggio di A, che B
        # non ha ancora in locale (ne diventa membro solo ora, unendosi).
        high = "2020-01-01T00:00:999999999999"
        for table in ("trips", "participants", "expenses", "splits"):
            self.b.db.set_state(f"wm:{table}", high)
        # Unendosi, il viaggio (più vecchio del watermark) deve comunque comparire.
        self.b.join_trip(code)
        self.assertIn("Roma", [t.name for t in self.b.db.list_trips()])
        self.assertEqual(len(self.b.db.list_expenses(trip.id)), 1)

    def test_offline_accountant_can_upload_and_share(self):
        # Il "contabile" lavora OFFLINE (non loggato): viaggio, persone, spesa.
        acct = make_client(self.server)
        seed_trip(acct)
        self.assertFalse(acct.is_logged_in())
        # Più tardi crea un account e accede: i dati offline NON vanno persi...
        acct.signup("acct@x.it", "pw")
        acct.sync()  # ...e vengono caricati sul server (push delle righe dirty)
        trip_id = acct.db.list_trips()[0].id
        code = acct.share_code(trip_id)
        self.assertTrue(code)
        # Un amico si unisce col codice e vede tutto.
        friend = make_client(self.server)
        friend.signup("friend@x.it", "pw2")
        friend.join_trip(code)
        self.assertEqual([t.name for t in friend.db.list_trips()], ["Roma"])
        self.assertEqual(len(friend.db.list_expenses(trip_id)), 1)
        acct.db.close()
        friend.db.close()

    def test_members_visible_after_join(self):
        trip = seed_trip(self.a)        # A è owner
        self.a.sync()
        code = self.a.share_code(trip.id)
        self.b.join_trip(code)          # B si unisce
        self.a.sync()                   # A riscarica la membership di B
        # Entrambi vedono i due membri nella cache locale.
        self.assertEqual(self.a.db.members_by_trip().get(trip.id), ["a@x.it", "b@x.it"])
        self.assertEqual(self.b.db.members_by_trip().get(trip.id), ["a@x.it", "b@x.it"])

    def test_delete_trip_propagates(self):
        trip = seed_trip(self.a)
        self.a.sync()
        code = self.a.share_code(trip.id)
        self.b.join_trip(code)
        self.assertIn("Roma", [t.name for t in self.b.db.list_trips()])
        # L'owner cancella il viaggio (soft-delete) -> sparisce per tutti.
        core.delete_trip(self.a.db, trip.id)
        self.a.sync()
        self.b.sync()
        self.assertEqual(self.b.db.list_trips(), [])

    def test_leave_trip_removes_local_and_membership(self):
        trip = seed_trip(self.a)
        self.a.sync()
        self.b.join_trip(self.a.share_code(trip.id))
        self.assertIn("Roma", [t.name for t in self.b.db.list_trips()])
        self.b.leave_trip(trip.id)
        self.assertEqual(self.b.db.list_trips(), [])           # copia locale rimossa
        self.assertIn("Roma", [t.name for t in self.a.db.list_trips()])  # resta per A
        self.a._pull_members()
        self.assertNotIn("b@x.it", self.a.db.members_by_trip().get(trip.id, []))

    def test_owner_cannot_leave(self):
        trip = seed_trip(self.a)
        self.a.sync()
        with self.assertRaises(SyncError):
            self.a.leave_trip(trip.id)

    def test_owner_removes_member(self):
        trip = seed_trip(self.a)
        self.a.sync()
        self.b.join_trip(self.a.share_code(trip.id))
        self.a._pull_members()
        self.assertIn("b@x.it", self.a.db.members_by_trip().get(trip.id, []))
        self.a.remove_member(trip.id, "b@x.it")
        self.assertNotIn("b@x.it", self.a.db.members_by_trip().get(trip.id, []))

    def test_member_cannot_remove(self):
        trip = seed_trip(self.a)
        self.a.sync()
        self.b.join_trip(self.a.share_code(trip.id))
        with self.assertRaises(SyncError):
            self.b.remove_member(trip.id, "a@x.it")

    def test_revoke_sharing_kicks_all_and_rotates_code(self):
        trip = seed_trip(self.a)
        self.a.sync()
        code = self.a.share_code(trip.id)
        self.b.join_trip(code)
        newcode = self.a.revoke_sharing(trip.id)
        self.assertTrue(newcode and newcode != code)
        self.assertNotIn("b@x.it", self.a.db.members_by_trip().get(trip.id, []))
        self.assertEqual(self.a.share_code(trip.id), newcode)

    @staticmethod
    def _rename(db, trip_id, name):
        db.conn.execute(
            "UPDATE trips SET name = ?, dirty = 1 WHERE id = ?", (name, trip_id)
        )
        db.conn.commit()


class AccountSwitchTest(unittest.TestCase):
    """Il DB locale è legato a un account per volta (vedi _store_session)."""

    def setUp(self):
        self.server = FakeSupabase()
        self.client = make_client(self.server)  # un solo "dispositivo"/DB

    def tearDown(self):
        self.client.db.close()

    def _count(self, table):
        return self.client.db.conn.execute(
            f"SELECT COUNT(*) AS c FROM {table}"
        ).fetchone()["c"]

    def test_switch_account_wipes_local_cache(self):
        # Utente A accede, crea dati e sincronizza.
        self.client.signup("a@x.it", "password1")
        seed_trip(self.client)
        self.client.sync()
        self.assertEqual([t.name for t in self.client.db.list_trips()], ["Roma"])
        # Utente B accede sullo STESSO dispositivo: la cache di A va azzerata.
        self.client.signup("b@x.it", "password2")
        self.assertEqual(self.client.db.list_trips(), [])
        for table in ("trips", "participants", "expenses", "splits"):
            self.assertEqual(self._count(table), 0, table)
        self.assertIsNone(self.client.db.get_state("wm:trips"))

    def test_relogin_same_account_keeps_data(self):
        self.client.signup("a@x.it", "password1")
        seed_trip(self.client)
        self.client.sync()
        self.client.logout()
        self.client.login("a@x.it", "password1")  # stesso utente: niente wipe
        self.assertEqual([t.name for t in self.client.db.list_trips()], ["Roma"])

    def test_offline_data_adopted_on_first_login(self):
        # Lavoro offline senza login: righe dirty, nessun account proprietario.
        seed_trip(self.client)
        self.assertTrue(self.client.db.dirty_rows("trips"))
        # Primo login: i dati offline NON vanno azzerati (diventano dell'utente).
        self.client.signup("a@x.it", "password1")
        self.assertEqual([t.name for t in self.client.db.list_trips()], ["Roma"])


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
