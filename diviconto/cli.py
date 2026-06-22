"""Interfaccia a riga di comando di DiviConto.

Strato sottile su :mod:`diviconto.core`. Usa argparse, quindi ``-h`` è
disponibile automaticamente sia globalmente sia per ogni sottocomando.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from . import __version__
from .core import SplitSpec, add_expense, add_participant, compute_balance, create_trip, resolve_trip
from .db import Database
from .models import Balance
from .money import format_money


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


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        with Database(args.db) as db:
            args.func(db, args)
    except ValueError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
