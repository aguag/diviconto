"""Logica di business riusabile da CLI e (in futuro) UI.

Nessuna stampa qui: le funzioni restituiscono dati o sollevano ValueError
con un messaggio leggibile. Lo strato CLI si occupa dell'output.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from . import balance as balance_mod
from .db import Database, new_id
from .i18n import tr
from .models import Balance, Expense, Participant, Split, Trip
from .money import convert, to_money, to_rate


class NotFoundError(ValueError):
    """Entità non trovata (viaggio o partecipante)."""


@dataclass
class SplitSpec:
    """Descrizione di come dividere una spesa.

    - mode "equal": divisa in parti uguali tra ``names`` (None = tutti i
      partecipanti del viaggio).
    - mode "exact": importi espliciti per partecipante in valuta ORIGINALE
      della spesa (``amounts``: nome -> importo); la somma deve coincidere
      con l'importo della spesa.
    """

    mode: str
    names: Optional[list[str]] = None
    amounts: Optional[dict[str, Decimal]] = None


# ---- Trip ----------------------------------------------------------------
def create_trip(db: Database, name: str, currency: str, description: str = "") -> Trip:
    if not name.strip():
        raise ValueError(tr("il nome del viaggio non può essere vuoto"))
    if not currency.strip():
        raise ValueError(tr("la valuta base è obbligatoria"))
    return db.add_trip(name.strip(), currency.strip().upper(), description.strip())


def resolve_trip(db: Database, ref: str) -> Trip:
    trip = db.get_trip(ref)
    if trip is None:
        raise NotFoundError(tr("viaggio non trovato: {ref}").format(ref=repr(ref)))
    return trip


# ---- Participant ---------------------------------------------------------
def add_participant(db: Database, trip_ref: str, name: str) -> Participant:
    trip = resolve_trip(db, trip_ref)
    name = name.strip()
    if not name:
        raise ValueError(tr("il nome del partecipante non può essere vuoto"))
    if db.get_participant_by_name(trip.id, name):
        raise ValueError(tr("partecipante {name} già presente nel viaggio").format(name=repr(name)))
    return db.add_participant(trip.id, name)


def _participant_or_error(db: Database, trip: Trip, name: str) -> Participant:
    p = db.get_participant_by_name(trip.id, name)
    if p is None:
        raise NotFoundError(tr("partecipante non trovato nel viaggio: {name}").format(name=repr(name)))
    return p


# ---- Expense -------------------------------------------------------------
def add_expense(
    db: Database,
    trip_ref: str,
    payer_name: str,
    amount,
    description: str = "",
    currency: Optional[str] = None,
    rate=None,
    split: Optional[SplitSpec] = None,
) -> Expense:
    """Registra una spesa e calcola le quote in valuta base.

    ``currency`` default = valuta base del viaggio. ``rate`` è il tasso verso
    la valuta base (obbligatorio se la valuta è diversa da quella base).
    ``split`` default = parti uguali tra tutti i partecipanti.
    """
    trip = resolve_trip(db, trip_ref)
    participants = db.list_participants(trip.id)
    if not participants:
        raise ValueError(tr("aggiungi almeno un partecipante prima di registrare spese"))

    if not description.strip():
        raise ValueError(tr("la descrizione della spesa è obbligatoria"))

    payer = _participant_or_error(db, trip, payer_name)
    amount = to_money(amount)
    if amount <= 0:
        raise ValueError(tr("l'importo della spesa deve essere positivo"))

    currency = (currency or trip.base_currency).strip().upper()
    if currency == trip.base_currency:
        rate_dec = Decimal("1")
    else:
        if rate is None:
            raise ValueError(
                tr("valuta {cur} diversa dalla base {base}: "
                   "serve --rate (tasso verso la valuta base)").format(
                    cur=currency, base=trip.base_currency)
            )
        rate_dec = to_rate(rate)
    amount_base = convert(amount, rate_dec)

    if split is None:
        split = SplitSpec(mode="equal")

    expense = Expense(
        id=new_id(),
        trip_id=trip.id,
        payer_id=payer.id,
        amount=amount,
        currency=currency,
        rate_to_base=rate_dec,
        amount_base=amount_base,
        description=description.strip(),
    )
    expense.splits = _build_splits(db, trip, participants, expense, split, rate_dec)
    return db.add_expense(expense)


def _build_splits(
    db: Database,
    trip: Trip,
    participants: list[Participant],
    expense: Expense,
    split: SplitSpec,
    rate_dec: Decimal,
) -> list[Split]:
    if split.mode == "equal":
        if split.names:
            chosen = [_participant_or_error(db, trip, n) for n in split.names]
        else:
            chosen = participants
        shares_base = _split_equally(expense.amount_base, len(chosen))
        return [
            Split(new_id(), expense.id, p.id, "equal", share)
            for p, share in zip(chosen, shares_base)
        ]

    if split.mode == "exact":
        if not split.amounts:
            raise ValueError(tr("divisione 'exact' senza importi"))
        chosen = [_participant_or_error(db, trip, n) for n in split.amounts]
        shares_orig = [to_money(split.amounts[p.name]) for p in chosen]
        total = sum(shares_orig, Decimal("0.00"))
        if total != expense.amount:
            raise ValueError(
                tr("la somma delle quote ({total}) non corrisponde all'importo "
                   "della spesa ({amount} {currency})").format(
                    total=total, amount=expense.amount, currency=expense.currency)
            )
        # converte ogni quota in valuta base; l'ultima assorbe l'arrotondamento
        shares_base = [convert(s, rate_dec) for s in shares_orig]
        drift = expense.amount_base - sum(shares_base, Decimal("0.00"))
        if shares_base:
            shares_base[-1] = to_money(shares_base[-1] + drift)
        return [
            Split(new_id(), expense.id, p.id, "exact", share)
            for p, share in zip(chosen, shares_base)
        ]

    raise ValueError(tr("modalità di divisione sconosciuta: {mode}").format(mode=repr(split.mode)))


def _split_equally(total: Decimal, n: int) -> list[Decimal]:
    """Divide ``total`` in ``n`` quote che sommano esattamente a ``total``."""
    if n <= 0:
        raise ValueError(tr("nessun partecipante selezionato per la divisione"))
    base = to_money(total / n)
    shares = [base] * n
    drift = to_money(total - base * n)
    shares[-1] = to_money(shares[-1] + drift)
    return shares


def update_expense_description(db: Database, expense_id: str, description: str) -> None:
    """Modifica la descrizione di una spesa (obbligatoria, non vuota)."""
    description = description.strip()
    if not description:
        raise ValueError(tr("la descrizione della spesa è obbligatoria"))
    db.update_expense_description(expense_id, description)


def delete_expense(db: Database, expense_id: str) -> None:
    """Cancella (soft-delete) una spesa."""
    db.delete_expense(expense_id)


def delete_trip(db: Database, trip_ref: str) -> Trip:
    """Cancella (soft-delete) un intero viaggio. Ritorna il viaggio cancellato."""
    trip = resolve_trip(db, trip_ref)
    db.delete_trip(trip.id)
    return trip


# ---- Partecipanti: rinomina / elimina ------------------------------------
def rename_participant(db: Database, trip_ref: str, old_name: str, new_name: str) -> Participant:
    """Corregge il nome di un partecipante (non vuoto, non duplicato)."""
    trip = resolve_trip(db, trip_ref)
    p = _participant_or_error(db, trip, old_name)
    new_name = new_name.strip()
    if not new_name:
        raise ValueError(tr("il nome del partecipante non può essere vuoto"))
    existing = db.get_participant_by_name(trip.id, new_name)
    if existing and existing.id != p.id:
        raise ValueError(tr("partecipante {name} già presente nel viaggio").format(name=repr(new_name)))
    db.rename_participant(p.id, new_name)
    return p


def _scale_shares(shares: dict, total: Decimal, target: Decimal) -> dict:
    """Riscalonature le quote ``shares`` (somma=total) a sommare ``target``."""
    ids = list(shares)
    if total == 0 or not ids:
        return {pid: Decimal("0.00") for pid in ids}
    scaled = [to_money(shares[pid] * target / total) for pid in ids]
    drift = to_money(target - sum(scaled, Decimal("0.00")))
    scaled[-1] = to_money(scaled[-1] + drift)
    return dict(zip(ids, scaled))


def _insert_base_expense(db: Database, trip: Trip, payer_id: str,
                         amount_base: Decimal, description: str, shares: dict) -> None:
    """Crea una spesa in valuta base con quote esplicite (per la riassegnazione)."""
    eid = new_id()
    splits = [Split(new_id(), eid, pid, "equal", share) for pid, share in shares.items()]
    db.add_expense(Expense(
        id=eid, trip_id=trip.id, payer_id=payer_id,
        amount=amount_base, currency=trip.base_currency, rate_to_base=Decimal("1"),
        amount_base=amount_base, description=description, splits=splits,
    ))


def delete_participant(db: Database, trip_ref: str, name: str) -> Participant:
    """Elimina un partecipante; i suoi movimenti sono stornati ai rimanenti.

    - la sua **quota** in ogni spesa è ridistribuita in parti uguali tra gli
      altri partecipanti di quella spesa;
    - le spese che ha **pagato** sono riassegnate ai rimanenti partecipanti di
      quella spesa in parti uguali (la spesa è spezzata in più voci, una per
      pagante, in valuta base).
    """
    trip = resolve_trip(db, trip_ref)
    p = _participant_or_error(db, trip, name)

    for exp in db.list_expenses(trip.id):
        splits = {s.participant_id: s for s in exp.splits}
        p_split = splits.get(p.id)
        p_is_payer = exp.payer_id == p.id
        if p_split is None and not p_is_payer:
            continue  # P non è coinvolto in questa spesa

        other_ids = [pid for pid in splits if pid != p.id]
        p_share = p_split.share_base if p_split else Decimal("0.00")
        new_shares: dict = {}
        if other_ids:
            adds = _split_equally(p_share, len(other_ids))
            for pid, add in zip(other_ids, adds):
                new_shares[pid] = to_money(splits[pid].share_base + add)

        if not p_is_payer:
            # Il pagante resta: aggiorna le quote in place (rimuovi quella di P).
            if new_shares:
                if p_split:
                    db.soft_delete_split(p_split.id)
                for pid, val in new_shares.items():
                    db.update_split_share(splits[pid].id, val)
            else:
                db.delete_expense(exp.id)  # nessun consumatore rimasto
        else:
            # P pagava: spezza la spesa, pagamento ai rimanenti sharer in parti uguali.
            db.delete_expense(exp.id)
            if new_shares:
                portions = _split_equally(exp.amount_base, len(other_ids))
                for r_id, portion in zip(other_ids, portions):
                    _insert_base_expense(
                        db, trip, r_id, portion, exp.description,
                        _scale_shares(new_shares, exp.amount_base, portion),
                    )

    db.delete_participant(p.id)
    return p


# ---- Balance -------------------------------------------------------------
def compute_balance(db: Database, trip_ref: str) -> Balance:
    trip = resolve_trip(db, trip_ref)
    participants = db.list_participants(trip.id)
    expenses = db.list_expenses(trip.id)
    return balance_mod.compute_balance(participants, expenses, trip.base_currency)
