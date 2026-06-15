"""Helper UI condivisi tra le schermate."""

from __future__ import annotations

from kivymd.uix.snackbar import Snackbar


def toast(message: str) -> None:
    """Mostra un breve messaggio in fondo allo schermo (errori/conferme)."""
    Snackbar(text=str(message), duration=2.5).open()
