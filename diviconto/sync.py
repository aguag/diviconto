"""Sincronizzazione offline-first con Supabase.

Il SQLite locale resta la fonte primaria: questo modulo scambia con Supabase
solo le righe cambiate (push delle righe ``dirty``, pull di quelle con
``updated_at`` più recente del watermark). I conflitti si risolvono per riga,
last-write-wins sull'``updated_at`` autoritativo del server; le cancellazioni
viaggiano come ``deleted = true`` (tombstone).

Usa la libreria standard (``urllib``) per le richieste HTTP. Su Android l'APK
include ``certifi`` solo per fornire il bundle di certificati CA alla verifica
TLS (vedi :func:`_get_ssl_context`); su desktop non serve.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .db import SYNC_COLUMNS, Database
from .sync_config import SUPABASE_ANON_KEY, SUPABASE_URL

# Ordine di sincronizzazione: i genitori prima dei figli (vincoli FK locali).
SYNC_TABLES = ("trips", "participants", "expenses", "splits")

_EPOCH = "1970-01-01T00:00:00+00:00"

# Trust store di sistema su Android (file CA in formato c_rehash).
_ANDROID_CA_DIR = "/system/etc/security/cacerts"

_ssl_context: Optional[ssl.SSLContext] = None


def _get_ssl_context() -> ssl.SSLContext:
    """Context TLS con un bundle di CA valido sia su desktop sia su Android.

    Su Android l'APK non ha i certificati nei path standard di OpenSSL: senza
    questo, ``urlopen`` su HTTPS fallisce la verifica e il sync non parte.
    Si prova ``certifi`` (incluso nell'APK), poi il trust store di sistema
    Android, infine il context di default (desktop con CA di sistema).
    """
    global _ssl_context
    if _ssl_context is not None:
        return _ssl_context
    ctx = ssl.create_default_context()
    try:
        import certifi  # opzionale: presente nell'APK, non richiesto su desktop

        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        if os.path.isdir(_ANDROID_CA_DIR):
            try:
                ctx.load_verify_locations(capath=_ANDROID_CA_DIR)
            except Exception:
                pass
    _ssl_context = ctx
    return ctx


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
        new_uid = user.get("id")
        if new_uid:
            # Il DB locale è legato a un solo account per volta. Se ne accede uno
            # diverso (o, su DB pre-esistenti senza marcatore, sono presenti dati
            # già sincronizzati di qualcun altro), si azzera la cache e si
            # riparte dai dati del nuovo account. Il lavoro offline non ancora
            # inviato (dirty) viene invece mantenuto e diventa di questo utente.
            prev = self.db.get_state("session_user")
            if new_uid != prev and (prev is not None or self.db.has_synced_data()):
                self.db.clear_synced_data()
            self.db.set_state("session_user", new_uid)
            self.db.set_state("user_id", new_uid)
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
        self._pull_members()

    def _pull_members(self) -> None:
        """Aggiorna la cache locale dei membri (chi accede a ciascun viaggio).

        La RLS restituisce solo i membri dei viaggi di cui si fa parte. Non c'è
        watermark: `trip_members` è piccola e la si rilegge intera a ogni sync.
        """
        rows = self._request(
            "GET", "/rest/v1/trip_members", params={"select": "trip_id,email,role"}
        ) or []
        self.db.replace_trip_members(rows)

    def join_trip(self, code: str) -> str:
        """Si unisce a un viaggio tramite codice, poi sincronizza. Ritorna l'id."""
        if not self.is_logged_in():
            raise SyncError("devi accedere prima di unirti a un viaggio")
        trip_id = self._request(
            "POST", "/rest/v1/rpc/join_trip", body={"code": code.strip()},
        )
        # Un viaggio appena unito è stato creato/aggiornato prima d'ora: il suo
        # ``updated_at`` può essere più VECCHIO del watermark di pull, e il pull
        # incrementale lo salterebbe (oltre a poter scaricare spese senza il
        # viaggio padre → errore FK). Azzeriamo i watermark così il prossimo
        # pull riscarica, in ordine di dipendenza, tutto ciò di cui siamo ora
        # membri (il nuovo viaggio compreso). È idempotente: l'upsert non duplica.
        for table in SYNC_TABLES:
            self.db.delete_state(f"wm:{table}")
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

    def leave_trip(self, trip_id: str) -> None:
        """Abbandona un viaggio: rimuove la membership sul server e la copia locale.

        Non è un soft-delete: il viaggio resta per gli altri membri; sparisce solo
        da questo dispositivo.
        """
        if not self.is_logged_in():
            raise SyncError("devi accedere per abbandonare un viaggio")
        self._request("POST", "/rest/v1/rpc/leave_trip", body={"tid": trip_id})
        self.db.drop_trip_local(trip_id)

    def remove_member(self, trip_id: str, email: str) -> None:
        """L'owner rimuove un membro (per email), poi rilegge i membri."""
        if not self.is_logged_in():
            raise SyncError("devi accedere per gestire i membri")
        self._request(
            "POST", "/rest/v1/rpc/remove_member",
            body={"tid": trip_id, "member_email": email.strip()},
        )
        self._pull_members()

    def revoke_sharing(self, trip_id: str) -> Optional[str]:
        """L'owner revoca la condivisione a tutti e rigenera il codice.

        Ritorna il nuovo share_code (il vecchio smette di funzionare).
        """
        if not self.is_logged_in():
            raise SyncError("devi accedere per gestire la condivisione")
        code = self._request("POST", "/rest/v1/rpc/revoke_sharing", body={"tid": trip_id})
        self._pull_members()
        return code

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
            with urllib.request.urlopen(
                req, timeout=self.timeout, context=_get_ssl_context()
            ) as resp:
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
