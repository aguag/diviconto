"""Utilità monetarie basate su :class:`decimal.Decimal`.

Tutti gli importi nel programma sono ``Decimal`` arrotondati a 2 cifre
decimali. Usare Decimal (e non float) evita gli errori di arrotondamento
tipici dei soldi (es. 0.1 + 0.2 != 0.3).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

CENTS = Decimal("0.01")


def to_money(value) -> Decimal:
    """Converte un valore (str/int/float/Decimal) in importo a 2 decimali.

    I float vengono passati come stringa per non ereditarne l'imprecisione.
    Solleva ``ValueError`` se il valore non è un numero valido.
    """
    if isinstance(value, float):
        value = repr(value)
    try:
        return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"importo non valido: {value!r}") from exc


def to_rate(value) -> Decimal:
    """Converte un tasso di cambio in Decimal (senza arrotondare a 2 cifre)."""
    if isinstance(value, float):
        value = repr(value)
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"tasso di cambio non valido: {value!r}") from exc
    if rate <= 0:
        raise ValueError("il tasso di cambio deve essere positivo")
    return rate


def convert(amount: Decimal, rate: Decimal) -> Decimal:
    """Converte un importo nella valuta base moltiplicando per il tasso."""
    return to_money(amount * rate)


def format_money(amount: Decimal, currency: str = "") -> str:
    """Formatta un importo per la stampa, es. ``12.50 EUR``."""
    text = f"{to_money(amount):.2f}"
    return f"{text} {currency}".strip()
