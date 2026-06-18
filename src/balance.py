"""Calcolo dei saldi e dei pagamenti di pareggio.

Tutto è espresso nella valuta base del viaggio. Funzioni pure (nessun I/O),
così sono riusabili dalla CLI e dalla futura UI.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from .models import Balance, Expense, Participant, Settlement
from .money import to_money


def compute_balance(
    participants: Iterable[Participant],
    expenses: Iterable[Expense],
    base_currency: str,
) -> Balance:
    """Calcola pagato/dovuto/netto per partecipante e i pagamenti di pareggio."""
    names = {p.id: p.name for p in participants}
    paid: dict[str, Decimal] = {name: Decimal("0.00") for name in names.values()}
    owed: dict[str, Decimal] = {name: Decimal("0.00") for name in names.values()}

    for exp in expenses:
        payer = names.get(exp.payer_id)
        if payer is not None:
            paid[payer] += exp.amount_base
        for s in exp.splits:
            who = names.get(s.participant_id)
            if who is not None:
                owed[who] += s.share_base

    paid = {n: to_money(v) for n, v in paid.items()}
    owed = {n: to_money(v) for n, v in owed.items()}
    net = {n: to_money(paid[n] - owed[n]) for n in paid}

    settlements = _settle(net)
    return Balance(
        base_currency=base_currency, paid=paid, owed=owed, net=net, settlements=settlements
    )


def _settle(net: dict[str, Decimal]) -> list[Settlement]:
    """Algoritmo greedy per il numero minimo di pagamenti.

    Abbina ripetutamente il maggior debitore al maggior creditore per la
    cifra minima tra i due, finché tutti i saldi sono azzerati.
    """
    creditors = [[n, amt] for n, amt in net.items() if amt > 0]
    debtors = [[n, -amt] for n, amt in net.items() if amt < 0]
    creditors.sort(key=lambda x: x[1], reverse=True)
    debtors.sort(key=lambda x: x[1], reverse=True)

    settlements: list[Settlement] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        d_name, d_amt = debtors[i]
        c_name, c_amt = creditors[j]
        pay = to_money(min(d_amt, c_amt))
        if pay > 0:
            settlements.append(Settlement(debtor=d_name, creditor=c_name, amount=pay))
        debtors[i][1] = to_money(d_amt - pay)
        creditors[j][1] = to_money(c_amt - pay)
        if debtors[i][1] <= 0:
            i += 1
        if creditors[j][1] <= 0:
            j += 1
    return settlements
