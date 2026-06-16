"""Sincronizzazione offline-first con Supabase.

Il SQLite locale resta la fonte primaria: questo modulo scambia con Supabase
solo le righe cambiate (push delle righe ``dirty``, pull di quelle con
``updated_at`` più recente del watermark). I conflitti si risolvono per riga,
last-write-wins sull'``updated_at`` autoritativo del server; le cancellazioni
viaggiano come ``deleted = true`` (tombstone).

Usa solo la libreria standard (``urllib``): nessuna dipendenza aggiuntiva, così
funziona identico su desktop e nell'APK Android.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .db import SYNC_COLUMNS, Database
from .sync_config import SUPABASE_ANON_KEY, SUPABASE_URL

# Ordine di sincronizzazione: i genitori prima dei figli (vincoli FK locali).
SYNC_TABLES = ("trips", "participants", "expenses", "splits")

_EPOCH = "1970-01-01T00:00:00+00:00"


class SyncError(Exception):
    """Errore di autenticazione, di rete o lato server durante il sync."""


class SyncClient:
    """Client di sincronizzazione legato a un :class:`Database` locale."""

    def __init__(
        self,
        db: Database,
        base_url: Optional[str] = None,
        anon_key: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self.db = db
        self.base_url = (base_url or SUPABASE_URL).rstrip("/")
        self.anon_key = anon_key or SUPABASE_ANON_KEY
        self.timeout = timeout

    # ---- Autenticazione ---------------------------------------------------
    def is_logged_in(self) -> bool:
        return self.db.get_state("access_token") is not None

    def current_user(self) -> Optional[str]:
        return self.db.get_state("user_email")

    def signup(self, email: str, password: str) -> None:
        """Registra un nuovo utente e apre la sessione.

        Richiede che in Supabase la conferma email sia disattivata (vedi README).
        """
        self._request(
            "POST", "/auth/v1/signup",
            body={"email": email, "password": password}, auth=False,
        )
        self.login(email, password)

    def login(self, email: str, password: str) -> None:
        resp = self._request(
            "POST", "/auth/v1/token",
            params={"grant_type": "password"},
            body={"email": email, "password": password}, auth=False,
        )
        self._store_session(resp)

    def logout(self) -> None:
        for key in ("access_token", "refresh_token", "user_id", "user_email"):
            self.db.delete_state(key)

    def _store_session(self, resp: Optional[dict]) -> None:
        if not resp or not resp.get("access_token"):
            raise SyncError("risposta di autenticazione senza token")
        self.db.set_state("access_token", resp["access_token"])
        if resp.get("refresh_token"):
            self.db.set_state("refresh_token", resp["refresh_token"])
        user = resp.get("user") or {}
        if user.get("id"):
            self.db.set_state("user_id", user["id"])
        if user.get("email"):
            self.db.set_state("user_email", user["email"])

    def _refresh(self) -> None:
        rt = self.db.get_state("refresh_token")
        if not rt:
            raise SyncError("sessione scaduta: accedi di nuovo")
        try:
            resp = self._request(
                "POST", "/auth/v1/token",
                params={"grant_type": "refresh_token"},
                body={"refresh_token": rt}, auth=False, _retry=False,
            )
        except SyncError:
            self.logout()
            raise SyncError("sessione scaduta: accedi di nuovo")
        self._store_session(resp)

    # ---- Sincronizzazione -------------------------------------------------
    def sync(self) -> None:
        """Esegue push + pull per tutte le tabelle. Richiede di essere loggati."""
        if not self.is_logged_in():
            raise SyncError("devi accedere prima di sincronizzare")
        for table in SYNC_TABLES:
            self._push(table)
        for table in SYNC_TABLES:
            self._pull(table)

    def join_trip(self, code: str) -> str:
        """Si unisce a un viaggio tramite codice, poi sincronizza. Ritorna l'id."""
        if not self.is_logged_in():
            raise SyncError("devi accedere prima di unirti a un viaggio")
        trip_id = self._request(
            "POST", "/rest/v1/rpc/join_trip", body={"code": code.strip()},
        )
        self.sync()
        return trip_id

    def share_code(self, trip_id: str) -> Optional[str]:
        """Legge dal server il codice di condivisione del viaggio (None se assente)."""
        rows = self._request(
            "GET", "/rest/v1/trips",
            params={"id": f"eq.{trip_id}", "select": "share_code"},
        )
        if rows:
            return rows[0].get("share_code")
        return None

    def _push(self, table: str) -> None:
        rows = self.db.dirty_rows(table)
        if not rows:
            return
        payload = [self._to_remote(table, r) for r in rows]
        self._request(
            "POST", f"/rest/v1/{table}",
            params={"on_conflict": "id"},
            body=payload,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        self.db.mark_clean(table, [r["id"] for r in rows])

    def _pull(self, table: str) -> None:
        wm_key = f"wm:{table}"
        wm = self.db.get_state(wm_key) or _EPOCH
        rows = self._request(
            "GET", f"/rest/v1/{table}",
            params={"select": "*", "updated_at": f"gt.{wm}", "order": "updated_at.asc"},
        ) or []
        max_wm = wm
        for row in rows:
            self.db.upsert_from_remote(table, row)
            if row.get("updated_at", "") > max_wm:
                max_wm = row["updated_at"]
        if max_wm != wm:
            self.db.set_state(wm_key, max_wm)

    def _to_remote(self, table: str, row: dict) -> dict:
        """Converte una riga locale nel payload per Supabase.

        ``updated_at`` non viene inviato: lo assegna il server (timestamp
        autoritativo). Per i viaggi si aggiunge ``owner_id`` (l'utente corrente).
        """
        out: dict = {"id": row["id"]}
        for col in SYNC_COLUMNS[table]:
            if col == "updated_at":
                continue
            val = row[col]
            if col == "deleted":
                val = bool(val)
            out[col] = val
        if table == "trips":
            out["owner_id"] = self.db.get_state("user_id")
        return out

    # ---- HTTP -------------------------------------------------------------
    def _request(
        self, method, path, params=None, body=None, auth=True,
        prefer=None, _retry=True,
    ):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"apikey": self.anon_key, "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        if auth:
            token = self.db.get_state("access_token")
            if token:
                headers["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode("utf-8") if body is not None else None

        status, raw = self._http(method, url, headers, data)
        if status == 401 and auth and _retry and self.db.get_state("refresh_token"):
            self._refresh()
            return self._request(method, path, params, body, auth, prefer, _retry=False)
        if status >= 400:
            raise SyncError(self._error_message(status, raw))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def _http(self, method, url, headers, data):
        """Esegue la richiesta HTTP. Isolato per poterlo sostituire nei test."""
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            raise SyncError(f"errore di rete: {exc.reason}") from exc

    @staticmethod
    def _error_message(status: int, raw: bytes) -> str:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            for key in ("error_description", "msg", "message", "error", "hint"):
                if data.get(key):
                    return str(data[key])
        return f"errore dal server (HTTP {status})"
