#!/usr/bin/env python3
"""Manutenzione del backend Supabase di DiviConto.

USA la chiave **service_role**, che BYPASSA la Row Level Security: vede e
cancella QUALSIASI riga di QUALSIASI utente. È una chiave di amministrazione:
passala SOLO da variabile d'ambiente, non scriverla nel codice né committarla.

Pensato per ripulire le righe-spazzatura lasciate dagli utenti usa-e-getta dei
test (invisibili agli utenti reali via RLS, ma comunque presenti nel DB).

Uso (dalla root del progetto)::

    export SUPABASE_SERVICE_KEY='eyJ...service_role...'   # Project Settings → API
    python tools/supabase_admin.py users                  # elenca gli utenti Auth
    python tools/supabase_admin.py trips                  # elenca tutti i viaggi
    python tools/supabase_admin.py purge-trip <id> [<id> ...]   # cancella viaggi
    python tools/supabase_admin.py purge-user <email>          # cancella utente + suoi viaggi

I comandi ``purge-*`` di default fanno un **DRY-RUN** (mostrano solo cosa
farebbero). Aggiungi ``--yes`` per eseguire davvero.

Tipo di cancellazione:
  * default = **soft-delete**: marca ``deleted=true`` (il trigger aggiorna
    ``updated_at``). È l'unico modo che si **propaga ai dispositivi** via sync:
    al prossimo sync l'app nasconde il viaggio ovunque. Usa questo per i dati
    di un account reale.
  * ``--hard`` = rimozione fisica della riga. NON si propaga (il pull non vede
    una riga sparita) e una copia locale ``dirty`` può ricrearla al push. Usalo
    SOLO per la spazzatura di utenti usa-e-getta dei test.
    Con ``purge-user`` la rimozione dell'utente Auth avviene solo con ``--hard``.

L'URL del progetto si prende da ``diviconto.sync_config`` (sovrascrivibile con
la variabile d'ambiente ``SUPABASE_URL``).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# Assicura che la root del progetto sia importabile anche lanciando lo script
# come "python tools/supabase_admin.py" (altrimenti in sys.path c'è solo tools/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# URL del progetto (riusa la configurazione dell'app; rispetta SUPABASE_URL).
try:
    from diviconto.sync_config import SUPABASE_URL
except Exception:  # se eseguito fuori dalla root del progetto
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")

BASE = (SUPABASE_URL or "").rstrip("/")

SERVICE_KEY = (
    os.environ.get("SUPABASE_SERVICE_KEY")
    or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
)

# Ordine di cancellazione: figli prima dei genitori (le FK non hanno CASCADE).
# splits → expenses → participants → trip_members → trips


def _check_env() -> None:
    if not BASE:
        sys.exit("Errore: SUPABASE_URL non configurato.")
    if not SERVICE_KEY:
        sys.exit(
            "Errore: imposta SUPABASE_SERVICE_KEY con la chiave service_role\n"
            "(Dashboard → Project Settings → API → service_role 'secret').\n"
            "NON la chiave anon e NON la password del DB."
        )


def _req(method, path, params=None, body=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": "Bearer " + SERVICE_KEY,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {exc.code} su {method} {path}: {body}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Errore di rete: {exc.reason}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


# ---- Lettura --------------------------------------------------------------

def list_users():
    users, page = [], 1
    while True:
        data = _req("GET", "/auth/v1/admin/users",
                    params={"page": page, "per_page": 1000})
        batch = data.get("users", []) if isinstance(data, dict) else (data or [])
        if not batch:
            break
        users.extend(batch)
        if len(batch) < 1000:
            break
        page += 1
    return users


def fetch_all(table, select="*", **filters):
    params = {"select": select}
    params.update(filters)
    return _req("GET", f"/rest/v1/{table}", params=params) or []


# ---- Comandi --------------------------------------------------------------

def cmd_users():
    users = list_users()
    if not users:
        print("Nessun utente.")
        return
    for u in sorted(users, key=lambda x: x.get("created_at") or ""):
        print(f"{u['id']}  {(u.get('created_at') or '')[:19]}  "
              f"{u.get('email') or '(senza email)'}")
    print(f"\nTotale: {len(users)} utenti.")


def cmd_trips():
    emails = {u["id"]: u.get("email") or "?" for u in list_users()}
    trips = fetch_all("trips")
    if not trips:
        print("Nessun viaggio.")
        return
    pc, ec = {}, {}
    for p in fetch_all("participants", select="trip_id"):
        pc[p["trip_id"]] = pc.get(p["trip_id"], 0) + 1
    for e in fetch_all("expenses", select="trip_id"):
        ec[e["trip_id"]] = ec.get(e["trip_id"], 0) + 1
    for t in sorted(trips, key=lambda x: x.get("created_at") or ""):
        flag = " [deleted]" if t.get("deleted") else ""
        print(f"{t['id']}  {(t.get('created_at') or '')[:19]}  "
              f"owner={emails.get(t['owner_id'], t['owner_id'])}  "
              f"part={pc.get(t['id'], 0)} spese={ec.get(t['id'], 0)}  "
              f"code={t.get('share_code')}{flag}  \"{t.get('name')}\"")
    print(f"\nTotale: {len(trips)} viaggi.")


def purge_trips(trip_ids, do_it, hard=False):
    for tid in trip_ids:
        trip = fetch_all("trips", id=f"eq.{tid}")
        if not trip:
            print(f"- {tid}: non trovato, salto.")
            continue
        name = trip[0].get("name")
        exp_ids = [e["id"] for e in fetch_all("expenses", select="id", trip_id=f"eq.{tid}")]
        n_part = len(fetch_all("participants", select="id", trip_id=f"eq.{tid}"))
        mode = "HARD-delete (riga rimossa)" if hard else "soft-delete (tombstone deleted=true)"
        print(f"* viaggio {tid} \"{name}\": {len(exp_ids)} spese, {n_part} partecipanti "
              f"(+ relativi splits e membri) — {mode}")
        if not do_it:
            continue
        if hard:
            # Rimozione fisica: figli prima dei genitori (le FK non hanno CASCADE).
            # Da usare SOLO per spazzatura di utenti usa-e-getta: NON propaga ai
            # dispositivi (il pull non vede una riga sparita) e una copia locale
            # "dirty" può ricrearla al push successivo.
            if exp_ids:
                in_list = "in.(" + ",".join(exp_ids) + ")"
                _req("DELETE", "/rest/v1/splits", params={"expense_id": in_list})
            _req("DELETE", "/rest/v1/expenses", params={"trip_id": f"eq.{tid}"})
            _req("DELETE", "/rest/v1/participants", params={"trip_id": f"eq.{tid}"})
            _req("DELETE", "/rest/v1/trip_members", params={"trip_id": f"eq.{tid}"})
            _req("DELETE", "/rest/v1/trips", params={"id": f"eq.{tid}"})
        else:
            # Soft-delete: marca deleted=true; il trigger aggiorna updated_at, così
            # il pull lo propaga a tutti i dispositivi e l'app nasconde il viaggio.
            if exp_ids:
                in_list = "in.(" + ",".join(exp_ids) + ")"
                _req("PATCH", "/rest/v1/splits", params={"expense_id": in_list},
                     body={"deleted": True})
            _req("PATCH", "/rest/v1/expenses", params={"trip_id": f"eq.{tid}"},
                 body={"deleted": True})
            _req("PATCH", "/rest/v1/participants", params={"trip_id": f"eq.{tid}"},
                 body={"deleted": True})
            _req("PATCH", "/rest/v1/trips", params={"id": f"eq.{tid}"},
                 body={"deleted": True})
        print(f"  fatto.")


def cmd_purge_user(email, do_it, hard=False):
    user = next((u for u in list_users()
                 if (u.get("email") or "").lower() == email.lower()), None)
    if not user:
        print(f"Utente {email} non trovato.")
        return
    uid = user["id"]
    trips = fetch_all("trips", select="id", owner_id=f"eq.{uid}")
    print(f"Utente {email} ({uid}): {len(trips)} viaggi posseduti.")
    purge_trips([t["id"] for t in trips], do_it, hard=hard)
    # Rimuovere l'utente Auth ha senso solo con la rimozione fisica: i suoi
    # viaggi devono sparire davvero (la FK trips.owner_id → auth.users lo impone).
    if do_it and hard:
        _req("DELETE", "/rest/v1/trip_members", params={"user_id": f"eq.{uid}"})
        _req("DELETE", f"/auth/v1/admin/users/{uid}")
        print(f"Utente {email} eliminato.")
    elif do_it:
        print(f"Viaggi marcati come cancellati. L'utente Auth {email} è stato "
              f"mantenuto (per rimuoverlo serve --hard).")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    _check_env()
    cmd = argv[0]
    do_it = "--yes" in argv
    hard = "--hard" in argv
    rest = [a for a in argv[1:] if a not in ("--yes", "--hard")]

    if cmd == "users":
        cmd_users()
    elif cmd == "trips":
        cmd_trips()
    elif cmd == "purge-trip":
        if not rest:
            sys.exit("Specifica almeno un id viaggio.")
        purge_trips(rest, do_it, hard=hard)
    elif cmd == "purge-user":
        if not rest:
            sys.exit("Specifica l'email dell'utente.")
        cmd_purge_user(rest[0], do_it, hard=hard)
    else:
        sys.exit(f"Comando sconosciuto: {cmd!r}. Usa -h per l'aiuto.")

    if cmd.startswith("purge-") and not do_it:
        print("\nDRY-RUN: non è stato cancellato nulla. "
              "Rilancia lo stesso comando con --yes per eseguire.")


if __name__ == "__main__":
    main(sys.argv[1:])
