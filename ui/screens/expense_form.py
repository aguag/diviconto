"""Form per aggiungere una spesa a un viaggio."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from src import core
from ui.widgets import FormTextField, toast


class ExpenseFormScreen(MDScreen):
    """Costruisce dinamicamente i campi e crea la spesa via ``core.add_expense``."""

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()
        trip = app.current_trip
        self.participants = app.db.list_participants(trip.id)
        self.payer_name = self.participants[0].name if self.participants else ""
        self.split_mode = "equal"
        self._menu = None
        self._build_form(trip)

    def _build_form(self, trip):
        box = self.ids.form_box
        box.clear_widgets()

        # Pagante (menu a tendina)
        self.payer_btn = MDRaisedButton(
            text=f"Pagante: {self.payer_name}",
            on_release=lambda *_: self._open_payer_menu(),
        )
        box.add_widget(self._wrap(self.payer_btn))

        # Importo e valuta
        self.amount_field = FormTextField(hint_text="Importo", input_filter="float")
        box.add_widget(self.amount_field)

        self.currency_field = FormTextField(
            hint_text="Valuta", text=trip.base_currency,
        )
        box.add_widget(self.currency_field)

        self.rate_field = FormTextField(
            hint_text=f"Tasso verso {trip.base_currency} (solo se valuta diversa)",
            input_filter="float",
        )
        box.add_widget(self.rate_field)

        self.desc_field = FormTextField(hint_text="Descrizione")
        box.add_widget(self.desc_field)

        # Tipo divisione
        box.add_widget(MDLabel(text="Divisione", font_style="Subtitle2",
                               adaptive_height=True, size_hint_y=None, height="24dp"))
        self.equal_btn = MDRaisedButton(text="Parti uguali",
                                        on_release=lambda *_: self._set_mode("equal"))
        self.exact_btn = MDRaisedButton(text="Importi esatti",
                                        on_release=lambda *_: self._set_mode("exact"))
        row = MDBoxLayout(orientation="horizontal", spacing="8dp",
                          size_hint_y=None, height="48dp")
        row.add_widget(self.equal_btn)
        row.add_widget(self.exact_btn)
        box.add_widget(row)

        # Contenitore per i campi degli importi esatti
        self.exact_box = MDBoxLayout(orientation="vertical", spacing="4dp",
                                     adaptive_height=True, size_hint_y=None, height=0)
        box.add_widget(self.exact_box)

        self._set_mode("equal")

    @staticmethod
    def _wrap(widget):
        wrap = MDBoxLayout(size_hint_y=None, height="48dp")
        wrap.add_widget(widget)
        return wrap

    # ---- pagante ---------------------------------------------------------
    def _open_payer_menu(self):
        items = [
            {
                "text": p.name,
                "viewclass": "OneLineListItem",
                "on_release": lambda name=p.name: self._set_payer(name),
            }
            for p in self.participants
        ]
        self._menu = MDDropdownMenu(caller=self.payer_btn, items=items, width_mult=4)
        self._menu.open()

    def _set_payer(self, name):
        self.payer_name = name
        self.payer_btn.text = f"Pagante: {name}"
        if self._menu:
            self._menu.dismiss()

    # ---- modalità divisione ---------------------------------------------
    def _set_mode(self, mode):
        self.split_mode = mode
        self.equal_btn.text = ("✓ " if mode == "equal" else "") + "Parti uguali"
        self.exact_btn.text = ("✓ " if mode == "exact" else "") + "Importi esatti"

        self.exact_box.clear_widgets()
        if mode == "exact":
            self.exact_fields = {}
            for p in self.participants:
                field = FormTextField(hint_text=f"Quota di {p.name}", input_filter="float")
                self.exact_fields[p.name] = field
                self.exact_box.add_widget(field)
            self.exact_box.height = len(self.participants) * 56
        else:
            self.exact_fields = {}
            self.exact_box.height = 0

    # ---- salvataggio -----------------------------------------------------
    def save(self):
        app = MDApp.get_running_app()
        trip = app.current_trip

        if self.split_mode == "equal":
            split = core.SplitSpec(mode="equal")
        else:
            amounts = {}
            for name, field in self.exact_fields.items():
                text = field.text.strip()
                if not text:
                    continue
                try:
                    amounts[name] = Decimal(text)
                except InvalidOperation:
                    toast(f"Importo non valido per {name}")
                    return
            split = core.SplitSpec(mode="exact", amounts=amounts)

        rate = self.rate_field.text.strip() or None
        try:
            core.add_expense(
                app.db,
                trip_ref=trip.id,
                payer_name=self.payer_name,
                amount=self.amount_field.text,
                description=self.desc_field.text,
                currency=self.currency_field.text or None,
                rate=rate,
                split=split,
            )
        except ValueError as exc:
            toast(str(exc))
            return
        self.manager.current = "trip_detail"

    def go_back(self):
        self.manager.current = "trip_detail"
