"""Helper UI condivisi tra le schermate."""

from __future__ import annotations

from kivy.metrics import dp
from kivymd.uix.label import MDLabel
from kivymd.uix.snackbar import MDSnackbar


def toast(message: str) -> None:
    """Mostra un breve messaggio in fondo allo schermo (errori/conferme).

    In KivyMD 1.2.0 ``MDSnackbar`` prende i widget figli (non più ``text=``):
    si passa un ``MDLabel`` col testo.
    """
    MDSnackbar(
        MDLabel(text=str(message)),
        y=dp(24),
        pos_hint={"center_x": 0.5},
        size_hint_x=0.9,
        duration=2.5,
    ).open()
