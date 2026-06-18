"""Dataclasses dei dati del dominio.

Gli importi sono memorizzati come :class:`decimal.Decimal`. Gli id sono
UUID testuali (vedi db.py) per facilitare una futura sincronizzazione tra
dispositivi senza collisioni.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class Trip:
    id: str
    name: str
    base_currency: str
    description: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Participant:
    id: str
    trip_id: str
    name: str
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Split:
    """Quota a carico di un partecipante per una spesa.

    ``mode`` è "equal" o "exact"; ``share_base`` è la quota dovuta risolta
    in valuta base del viaggio.
    """

    id: str
    expense_id: str
    participant_id: str
    mode: str
    share_base: Decimal


@dataclass
class Expense:
    id: str
    trip_id: str
    payer_id: str
    amount: Decimal          # importo nella valuta originale
    currency: str            # valuta originale della spesa
    rate_to_base: Decimal    # tasso verso la valuta base (1 se uguale)
    amount_base: Decimal     # importo convertito in valuta base
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
    splits: list[Split] = field(default_factory=list)


@dataclass
class Settlement:
    """Pagamento suggerito per pareggiare i conti: ``debtor`` paga a ``creditor``."""

    debtor: str
    creditor: str
    amount: Decimal


@dataclass
class Balance:
    """Riepilogo del bilancio di un viaggio."""

    base_currency: str
    paid: dict[str, Decimal]      # nome -> totale pagato
    owed: dict[str, Decimal]      # nome -> totale dovuto
    net: dict[str, Decimal]       # nome -> netto (pagato - dovuto)
    settlements: list[Settlement] = field(default_factory=list)
