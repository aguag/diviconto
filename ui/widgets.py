"""Helper UI condivisi tra le schermate."""

from __future__ import annotations

from kivy.factory import Factory
from kivy.metrics import dp
from kivymd.uix.label import MDLabel
from kivymd.uix.snackbar import MDSnackbar
from kivymd.uix.textfield import MDTextField


class FormTextField(MDTextField):
    """Campo di testo che riapre la tastiera anche se ritoccato mentre è già
    "focused".

    Su Android la tastiera chiusa col tasto Indietro non azzera il ``focus`` del
    campo: un nuovo tocco sullo stesso campo non cambierebbe stato e quindi non
    riaprirebbe la tastiera (toccando un altro campo invece sì). Forzando un
    breve defocus, il tocco — gestito poi da super — rifocalizza il campo e
    riapre la tastiera.
    """

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and self.focus:
            self.focus = False
        return super().on_touch_down(touch)


# Registrato nel Factory così è usabile anche nei file .kv come "FormTextField".
Factory.register("FormTextField", cls=FormTextField)


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
