"""Amministrazione del backend Supabase (comandi ``diviconto admin ...``).

A differenza del resto della CLI, questi comandi agiscono sull'intero backend.
Per farlo ci si autentica come un utente **admin** — un normale account Auth il
cui id è in ``public.admins`` (gestita dalla dashboard) — NON con la chiave
service_role. Si usa la chiave **anon** (pubblica) + il token di sessione
ottenuto col login; la sessione è salvata in locale e rinnovata col refresh.

L'accesso esteso ai dati lo concede la RLS (policy ``or is_admin(...)``); gli
utenti Auth, non esposti via RLS, si gestiscono con le RPC ``admin_*`` (vedi
``supabase/schema.sql``). Solo libreria standard (``urllib``).

La sessione admin sta in ``~/.config/diviconto/admin_session.json`` (override con
l'env ``DIVICONTO_ADMIN_SESSION``); il file è scritto con permessi 0600.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .sync_config import SUPABASE_ANON_KEY, SUPABASE_URL


class AdminError(Exception):
    """Errore di configurazione, autenticazione o lato server in un comando admin."""


# ---- sessione locale ------------------------------------------------------
def session_path() -> str:
    override = os.environ.get("DIVICONTO_ADMIN_SESSION")
    if override:
        return override
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "diviconto", "admin_session.json")


def _load_session() -> dict:
    try:
        with open(session_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_session(data: dict) -> None:
    path = session_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 0600: solo il proprietario può leggere il token.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _clear_session() -> None:
    try:
        os.remove(session_path())
    except OSError:
        pass


class AdminClient:
    """Client admin: login come utente Auth, poi REST (RLS estesa) + RPC admin_*."""

    def __init__(self, base_url: Optional[str] = None, anon_key: Optional[str] = None):
        self.base = (base_url or SUPABASE_URL).rstrip("/")
        self.anon = anon_key or SUPABASE_ANON_KEY
        sess = _load_session()
        self.token: Optional[str] = sess.get("access_token")
        self.refresh_token: Optional[str] = sess.get("refresh_token")
        self.email: Optional[str] = sess.get("email")

    # ---- autenticazione ---------------------------------------------------
    def is_logged_in(self) -> bool:
        return self.token is not None

    def login(self, email: str, password: str) -> None:
        resp = self._request(
            "POST", "/auth/v1/token",
            params={"grant_type": "password"},
            body={"email": email, "password": password},
            auth=False,
        )
        self._store(resp, email)

    def logout(self) -> None:
        self.token = self.refresh_token = self.email = None
        _clear_session()

    def _store(self, resp, email=None) -> None:
        if not resp or not resp.get("access_token"):
            raise AdminError("risposta di autenticazione senza token")
        self.token = resp["access_token"]
        self.refresh_token = resp.get("refresh_token") or self.refresh_token
        user = resp.get("user") or {}
        self.email = user.get("email") or email or self.email
        _save_session({
            "access_token": self.token,
            "refresh_token": self.refresh_token,
            "email": self.email,
        })

    def _refresh(self) -> None:
        if not self.refresh_token:
            raise AdminError("sessione scaduta: esegui di nuovo 'divc admin login'")
        try:
            resp = self._request(
                "POST", "/auth/v1/token",
                params={"grant_type": "refresh_token"},
                body={"refresh_token": self.refresh_token},
                auth=False, _retry=False,
            )
        except AdminError:
            self.logout()
            raise AdminError("sessione scaduta: esegui di nuovo 'divc admin login'")
        self._store(resp)

    # ---- HTTP -------------------------------------------------------------
    def _request(self, method, path, params=None, body=None, auth=True, _retry=True):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"apikey": self.anon, "Content-Type": "application/json"}
        if auth and self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = json.dumps(body).encode("utf-8") if body is not None else None

        status, raw = self._http(method, url, headers, data)
        if status == 401 and auth and _retry and self.refresh_token:
            self._refresh()
            return self._request(method, path, params, body, auth, _retry=False)
        if status >= 400:
            raise AdminError(self._error_message(status, raw))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def _http(self, method, url, headers, data):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            raise AdminError(f"errore di rete: {exc.reason}")

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

    def _rpc(self, name, body=None):
        return self._request("POST", f"/rest/v1/rpc/{name}", body=body or {})

    # ---- letture ----------------------------------------------------------
    def am_i_admin(self) -> bool:
        return bool(self._rpc("am_i_admin"))

    def list_users(self) -> list:
        return self._rpc("admin_list_users") or []

    def fetch_all(self, table, select="*", **filters) -> list:
        params = {"select": select}
        params.update(filters)
        return self._request("GET", f"/rest/v1/{table}", params=params) or []

    # ---- comandi (stampano l'output operativo) ----------------------------
    def cmd_users(self) -> None:
        users = self.list_users()
        if not users:
            print("Nessun utente.")
            return
        for u in sorted(users, key=lambda x: x.get("created_at") or ""):
            print(f"{u['id']}  {(u.get('created_at') or '')[:19]}  "
                  f"{u.get('email') or '(senza email)'}")
        print(f"\nTotale: {len(users)} utenti.")

    def cmd_trips(self) -> None:
        emails = {u["id"]: u.get("email") or "?" for u in self.list_users()}
        trips = self.fetch_all("trips")
        if not trips:
            print("Nessun viaggio.")
            return
        pc, ec = {}, {}
        for p in self.fetch_all("participants", select="trip_id"):
            pc[p["trip_id"]] = pc.get(p["trip_id"], 0) + 1
        for e in self.fetch_all("expenses", select="trip_id"):
            ec[e["trip_id"]] = ec.get(e["trip_id"], 0) + 1
        for t in sorted(trips, key=lambda x: x.get("created_at") or ""):
            flag = " [deleted]" if t.get("deleted") else ""
            print(f"{t['id']}  {(t.get('created_at') or '')[:19]}  "
                  f"owner={emails.get(t['owner_id'], t['owner_id'])}  "
                  f"part={pc.get(t['id'], 0)} spese={ec.get(t['id'], 0)}  "
                  f"code={t.get('share_code')}{flag}  \"{t.get('name')}\"")
        print(f"\nTotale: {len(trips)} viaggi.")

    def purge_trips(self, trip_ids, do_it, hard=False) -> None:
        for tid in trip_ids:
            trip = self.fetch_all("trips", id=f"eq.{tid}")
            if not trip:
                print(f"- {tid}: non trovato, salto.")
                continue
            name = trip[0].get("name")
            exp_ids = [e["id"] for e in self.fetch_all("expenses", select="id", trip_id=f"eq.{tid}")]
            n_part = len(self.fetch_all("participants", select="id", trip_id=f"eq.{tid}"))
            mode = "HARD-delete (riga rimossa)" if hard else "soft-delete (tombstone deleted=true)"
            print(f"* viaggio {tid} \"{name}\": {len(exp_ids)} spese, {n_part} partecipanti "
                  f"(+ relativi splits e membri) — {mode}")
            if not do_it:
                continue
            in_list = "in.(" + ",".join(exp_ids) + ")" if exp_ids else None
            if hard:
                if in_list:
                    self._request("DELETE", "/rest/v1/splits", params={"expense_id": in_list})
                self._request("DELETE", "/rest/v1/expenses", params={"trip_id": f"eq.{tid}"})
                self._request("DELETE", "/rest/v1/participants", params={"trip_id": f"eq.{tid}"})
                self._request("DELETE", "/rest/v1/trip_members", params={"trip_id": f"eq.{tid}"})
                self._request("DELETE", "/rest/v1/trips", params={"id": f"eq.{tid}"})
            else:
                if in_list:
                    self._request("PATCH", "/rest/v1/splits", params={"expense_id": in_list},
                                  body={"deleted": True})
                self._request("PATCH", "/rest/v1/expenses", params={"trip_id": f"eq.{tid}"},
                              body={"deleted": True})
                self._request("PATCH", "/rest/v1/participants", params={"trip_id": f"eq.{tid}"},
                              body={"deleted": True})
                self._request("PATCH", "/rest/v1/trips", params={"id": f"eq.{tid}"},
                              body={"deleted": True})
            print("  fatto.")

    def purge_user(self, email, do_it, hard=False) -> None:
        user = next(
            (u for u in self.list_users() if (u.get("email") or "").lower() == email.lower()),
            None,
        )
        if not user:
            print(f"Utente {email} non trovato.")
            return
        uid = user["id"]
        owned = self.fetch_all("trips", select="id", owner_id=f"eq.{uid}")
        if hard:
            print(f"Utente {email} ({uid}): ELIMINA l'utente e i suoi {len(owned)} viaggi posseduti.")
        else:
            print(f"Utente {email} ({uid}): marca come cancellati i suoi {len(owned)} viaggi "
                  f"(l'account Auth resta).")
        if not do_it:
            return
        if hard:
            # admin_delete_user fa tutto lato server (viaggi posseduti + utente).
            self._rpc("admin_delete_user", {"uid": uid})
            print(f"Utente {email} eliminato (con i suoi viaggi).")
        else:
            self.purge_trips([t["id"] for t in owned], do_it=True, hard=False)
            print(f"Viaggi marcati come cancellati. Utente {email} mantenuto "
                  f"(per rimuoverlo serve --hard).")
