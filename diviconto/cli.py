"""Interfaccia a riga di comando di DiviConto.

Strato sottile su :mod:`diviconto.core`. Usa argparse, quindi ``-h`` è
disponibile automaticamente sia globalmente sia per ogni sottocomando.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from . import __version__
from .admin import AdminClient, AdminError
from .core import (
    SplitSpec, add_expense, add_participant, compute_balance, create_trip,
    delete_trip, resolve_trip,
)
from .db import Database
from .models import Balance
from .money import format_money
from .sync import SyncClient, SyncError


def parse_split(spec: str) -> SplitSpec:
    """Interpreta la stringa di divisione passata a ``--split``.

    Formati accettati:
      equal                  -> parti uguali tra tutti
      equal:Anna,Bob         -> parti uguali tra i nominati
      exact:Anna=30,Bob=20   -> importi esatti (valuta della spesa)
    """
    spec = spec.strip()
    if spec == "equal" or spec == "":
        return SplitSpec(mode="equal")

    if ":" not in spec:
        raise ValueError(f"formato --split non valido: {spec!r}")
    mode, _, rest = spec.partition(":")
    mode = mode.strip().lower()
    rest = rest.strip()

    if mode == "equal":
        names = [n.strip() for n in rest.split(",") if n.strip()]
        if not names:
            raise ValueError("--split equal: elenco partecipanti vuoto")
        return SplitSpec(mode="equal", names=names)

    if mode == "exact":
        amounts: dict[str, Decimal] = {}
        for piece in rest.split(","):
            piece = piece.strip()
            if not piece:
                continue
            if "=" not in piece:
                raise ValueError(f"voce 'exact' non valida: {piece!r} (atteso nome=importo)")
            name, _, value = piece.partition("=")
            amounts[name.strip()] = Decimal(value.strip())
        if not amounts:
            raise ValueError("--split exact: nessun importo specificato")
        return SplitSpec(mode="exact", amounts=amounts)

    raise ValueError(f"modalità --split sconosciuta: {mode!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diviconto",
        description="DiviConto — dividi le spese di un viaggio tra amici.",
        epilog="Esempio: diviconto expense add --trip Spagna --payer Anna "
        "--amount 100 --desc Cena --split equal",
    )
    parser.add_argument("--version", action="version", version=f"DiviConto {__version__}")
    parser.add_argument(
        "--db", metavar="PATH",
        help="percorso del file DB (default ~/.diviconto/diviconto.db o env DIVICONTO_DB)",
    )
    # I comandi locali lavorano sul SQLite (local=True); quelli 'admin' sul cloud.
    parser.set_defaults(local=True)
    sub = parser.add_subparsers(dest="command", required=True, metavar="<comando>")

    # trip ----------------------------------------------------------------
    p_trip = sub.add_parser("trip", help="gestione viaggi").add_subparsers(
        dest="action", required=True, metavar="<azione>"
    )
    t_create = p_trip.add_parser("create", help="crea un nuovo viaggio")
    t_create.add_argument("--name", required=True, help="nome del viaggio")
    t_create.add_argument("--currency", required=True, help="valuta base (es. EUR)")
    t_create.add_argument("--desc", default="", help="descrizione del viaggio")
    t_create.set_defaults(func=cmd_trip_create)

    t_list = p_trip.add_parser("list", help="elenca i viaggi")
    t_list.set_defaults(func=cmd_trip_list)

    t_delete = p_trip.add_parser("delete", help="cancella un viaggio (solo il creatore)")
    t_delete.add_argument("--trip", required=True, help="id o nome del viaggio")
    t_delete.set_defaults(func=cmd_trip_delete)

    t_leave = p_trip.add_parser("leave", help="abbandona un viaggio condiviso (richiede login)")
    t_leave.add_argument("--trip", required=True, help="id o nome del viaggio")
    t_leave.set_defaults(func=cmd_trip_leave)

    t_kick = p_trip.add_parser("kick", help="rimuovi un membro dal viaggio (solo owner; richiede login)")
    t_kick.add_argument("--trip", required=True, help="id o nome del viaggio")
    t_kick.add_argument("--email", required=True, help="email del membro da rimuovere")
    t_kick.set_defaults(func=cmd_trip_kick)

    t_revoke = p_trip.add_parser("revoke", help="revoca la condivisione a tutti + rigenera il codice (solo owner)")
    t_revoke.add_argument("--trip", required=True, help="id o nome del viaggio")
    t_revoke.set_defaults(func=cmd_trip_revoke)

    # person --------------------------------------------------------------
    p_person = sub.add_parser("person", help="gestione partecipanti").add_subparsers(
        dest="action", required=True, metavar="<azione>"
    )
    pe_add = p_person.add_parser("add", help="aggiungi un partecipante")
    pe_add.add_argument("--trip", required=True, help="id o nome del viaggio")
    pe_add.add_argument("--name", required=True, help="nome del partecipante")
    pe_add.set_defaults(func=cmd_person_add)

    pe_list = p_person.add_parser("list", help="elenca i partecipanti")
    pe_list.add_argument("--trip", required=True, help="id o nome del viaggio")
    pe_list.set_defaults(func=cmd_person_list)

    # expense -------------------------------------------------------------
    p_exp = sub.add_parser("expense", help="gestione spese").add_subparsers(
        dest="action", required=True, metavar="<azione>"
    )
    ex_add = p_exp.add_parser("add", help="registra una spesa")
    ex_add.add_argument("--trip", required=True, help="id o nome del viaggio")
    ex_add.add_argument("--payer", required=True, help="chi ha pagato (nome)")
    ex_add.add_argument("--amount", required=True, help="importo della spesa")
    ex_add.add_argument("--desc", required=True, help="descrizione della spesa (obbligatoria)")
    ex_add.add_argument("--currency", help="valuta della spesa (default: valuta base)")
    ex_add.add_argument("--rate", help="tasso di cambio verso la valuta base")
    ex_add.add_argument(
        "--split", default="equal",
        help="divisione: 'equal', 'equal:Anna,Bob' o 'exact:Anna=30,Bob=20'",
    )
    ex_add.set_defaults(func=cmd_expense_add)

    ex_list = p_exp.add_parser("list", help="elenca le spese")
    ex_list.add_argument("--trip", required=True, help="id o nome del viaggio")
    ex_list.set_defaults(func=cmd_expense_list)

    # balance -------------------------------------------------------------
    p_bal = sub.add_parser("balance", help="mostra saldi e pagamenti di pareggio")
    p_bal.add_argument("--trip", required=True, help="id o nome del viaggio")
    p_bal.set_defaults(func=cmd_balance)

    # admin ---------------------------------------------------------------
    # Operazioni sul backend cloud (Supabase): ci si autentica come utente admin
    # (`divc admin login`). Accesso esteso via RLS (is_admin); usare con cautela.
    p_admin = sub.add_parser(
        "admin",
        help="amministrazione del backend cloud (richiede login come admin)",
    ).add_subparsers(dest="action", required=True, metavar="<azione>")

    a_login = p_admin.add_parser("login", help="accedi come utente admin (salva la sessione)")
    a_login.set_defaults(func=cmd_admin_login, local=False)

    a_logout = p_admin.add_parser("logout", help="esci e rimuovi la sessione admin")
    a_logout.set_defaults(func=cmd_admin_logout, local=False)

    a_users = p_admin.add_parser("users", help="elenca gli utenti Auth")
    a_users.set_defaults(func=cmd_admin_users, local=False)

    a_trips = p_admin.add_parser("trips", help="elenca i viaggi (owner + conteggi)")
    a_trips.set_defaults(func=cmd_admin_trips, local=False)

    a_ptrip = p_admin.add_parser(
        "purge-trip", help="cancella viaggi (dry-run senza --yes)")
    a_ptrip.add_argument("ids", nargs="+", metavar="ID", help="id dei viaggi")
    a_ptrip.add_argument("--yes", action="store_true", help="esegui davvero (default: dry-run)")
    a_ptrip.add_argument(
        "--hard", action="store_true",
        help="rimozione fisica (solo spazzatura usa-e-getta; NON si propaga via sync)",
    )
    a_ptrip.set_defaults(func=cmd_admin_purge_trip, local=False)

    a_puser = p_admin.add_parser(
        "purge-user", help="cancella un utente e i suoi viaggi (dry-run senza --yes)")
    a_puser.add_argument("email", help="email dell'utente")
    a_puser.add_argument("--yes", action="store_true", help="esegui davvero (default: dry-run)")
    a_puser.add_argument(
        "--hard", action="store_true",
        help="rimozione fisica + rimuove l'utente Auth (solo spazzatura usa-e-getta)",
    )
    a_puser.set_defaults(func=cmd_admin_purge_user, local=False)

    return parser


# ---- handlers ------------------------------------------------------------
def cmd_trip_create(db: Database, args) -> None:
    trip = create_trip(db, args.name, args.currency, args.desc)
    print(f"Creato viaggio {trip.name!r} ({trip.base_currency}) — id {trip.id}")


def cmd_trip_list(db: Database, args) -> None:
    trips = db.list_trips()
    if not trips:
        print("Nessun viaggio.")
        return
    for t in trips:
        extra = f" — {t.description}" if t.description else ""
        print(f"{t.name} [{t.base_currency}]  ({t.id}){extra}")


def cmd_trip_delete(db: Database, args) -> None:
    trip = delete_trip(db, args.trip)
    print(f"Viaggio {trip.name!r} cancellato (soft-delete). "
          "Sincronizza dall'app per propagare la cancellazione.")


def _sync_logged(db: Database) -> SyncClient:
    """SyncClient con sessione attiva sul DB locale; errore chiaro se non loggato."""
    sync = SyncClient(db)
    if not sync.is_logged_in():
        raise ValueError(
            "operazione online: devi essere connesso. Accedi dall'app usando lo "
            "stesso DB (variabile DIVICONTO_DB) e riprova."
        )
    return sync


def cmd_trip_leave(db: Database, args) -> None:
    trip = resolve_trip(db, args.trip)
    _sync_logged(db).leave_trip(trip.id)
    print(f"Hai abbandonato il viaggio {trip.name!r} (rimosso solo da questo dispositivo).")


def cmd_trip_kick(db: Database, args) -> None:
    trip = resolve_trip(db, args.trip)
    _sync_logged(db).remove_member(trip.id, args.email)
    print(f"Rimosso {args.email} dal viaggio {trip.name!r}.")


def cmd_trip_revoke(db: Database, args) -> None:
    trip = resolve_trip(db, args.trip)
    newcode = _sync_logged(db).revoke_sharing(trip.id)
    print(f"Condivisione revocata per {trip.name!r}. Nuovo codice: {newcode}")


def cmd_person_add(db: Database, args) -> None:
    p = add_participant(db, args.trip, args.name)
    print(f"Aggiunto partecipante {p.name!r}")


def cmd_person_list(db: Database, args) -> None:
    trip = resolve_trip(db, args.trip)
    people = db.list_participants(trip.id)
    if not people:
        print("Nessun partecipante.")
        return
    for p in people:
        print(p.name)


def cmd_expense_add(db: Database, args) -> None:
    split = parse_split(args.split)
    exp = add_expense(
        db,
        trip_ref=args.trip,
        payer_name=args.payer,
        amount=args.amount,
        description=args.desc,
        currency=args.currency,
        rate=args.rate,
        split=split,
    )
    desc = f" — {exp.description}" if exp.description else ""
    base = format_money(exp.amount_base, resolve_trip(db, args.trip).base_currency)
    print(
        f"Registrata spesa {format_money(exp.amount, exp.currency)} "
        f"(= {base}){desc}"
    )


def cmd_expense_list(db: Database, args) -> None:
    trip = resolve_trip(db, args.trip)
    people = {p.id: p.name for p in db.list_participants(trip.id)}
    expenses = db.list_expenses(trip.id)
    if not expenses:
        print("Nessuna spesa.")
        return
    for e in expenses:
        payer = people.get(e.payer_id, "?")
        desc = e.description or "(senza descrizione)"
        orig = format_money(e.amount, e.currency)
        base = format_money(e.amount_base, trip.base_currency)
        line = f"{payer}: {orig}"
        if e.currency != trip.base_currency:
            line += f" = {base}"
        print(f"{line}  — {desc}")


def cmd_balance(db: Database, args) -> None:
    trip = resolve_trip(db, args.trip)
    bal: Balance = compute_balance(db, args.trip)
    cur = bal.base_currency
    print(f"Bilancio viaggio {trip.name!r} (valuta {cur})\n")
    print(f"{'Partecipante':<16}{'Pagato':>12}{'Dovuto':>12}{'Saldo':>12}")
    print("-" * 52)
    for name in bal.net:
        print(
            f"{name:<16}{format_money(bal.paid[name]):>12}"
            f"{format_money(bal.owed[name]):>12}{format_money(bal.net[name]):>12}"
        )
    print()
    if not bal.settlements:
        print("Conti già in pari.")
        return
    print("Pagamenti suggeriti:")
    for s in bal.settlements:
        print(f"  {s.debtor} deve dare {format_money(s.amount, cur)} a {s.creditor}")


# ---- handlers admin (cloud) ----------------------------------------------
def _admin_logged() -> AdminClient:
    """Client admin con sessione attiva; errore chiaro se non si è loggati."""
    client = AdminClient()
    if not client.is_logged_in():
        raise AdminError("non sei loggato come admin. Esegui prima: divc admin login")
    return client


def cmd_admin_login(args) -> None:
    import getpass
    email = input("Email admin: ").strip()
    password = getpass.getpass("Password: ")
    if not email or not password:
        raise AdminError("email e password sono obbligatorie")
    client = AdminClient()
    client.login(email, password)
    if not client.am_i_admin():
        client.logout()
        raise AdminError(
            f"l'utente {email} non è un amministratore. Chiedi a chi gestisce il "
            "progetto di aggiungere il tuo account alla tabella 'admins'."
        )
    print(f"Login admin eseguito ({email}). Sessione salvata.")


def cmd_admin_logout(args) -> None:
    AdminClient().logout()
    print("Logout admin: sessione rimossa.")


def cmd_admin_users(args) -> None:
    _admin_logged().cmd_users()


def cmd_admin_trips(args) -> None:
    _admin_logged().cmd_trips()


def _dry_run_notice(args) -> None:
    if not args.yes:
        print("\nDRY-RUN: non è stato cancellato nulla. "
              "Rilancia lo stesso comando con --yes per eseguire.")


def cmd_admin_purge_trip(args) -> None:
    _admin_logged().purge_trips(args.ids, args.yes, args.hard)
    _dry_run_notice(args)


def cmd_admin_purge_user(args) -> None:
    _admin_logged().purge_user(args.email, args.yes, args.hard)
    _dry_run_notice(args)


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if getattr(args, "local", True):
            # Comandi locali: aprono il SQLite e ricevono (db, args).
            with Database(args.db) as db:
                args.func(db, args)
        else:
            # Comandi 'admin' (cloud): non toccano il DB locale, ricevono (args).
            args.func(args)
    except (ValueError, AdminError, SyncError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
