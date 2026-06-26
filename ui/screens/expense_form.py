"""Form per aggiungere una spesa a un viaggio."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from diviconto import core
from diviconto.i18n import tr
from diviconto.money import to_money
from ui.widgets import FormTextField, toast


class ExpenseFormScreen(MDScreen):
    """Form per creare una spesa o **modificarne** una esistente.

    Se ``app.editing_expense`` è impostata, la schermata si apre in modifica:
    campi precompilati e il salvataggio fa ``core.update_expense``.
    """

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()
        trip = app.current_trip
        self.participants = app.db.list_participants(trip.id)
        self.editing = getattr(app, "editing_expense", None)
        self._menu = None

        self.ids.form_topbar.title = tr("Modifica spesa") if self.editing else tr("Nuova spesa")
        people = {p.id: p.name for p in self.participants}
        if self.editing:
            self.payer_name = people.get(
                self.editing.payer_id,
                self.participants[0].name if self.participants else "")
            self.split_mode = self.editing.splits[0].mode if self.editing.splits else "equal"
        else:
            self.payer_name = self.participants[0].name if self.participants else ""
            self.split_mode = "equal"
        self._build_form(trip)

    def _build_form(self, trip):
        box = self.ids.form_box
        box.clear_widgets()

        # Pagante (menu a tendina)
        self.payer_btn = MDRaisedButton(
            text=tr("Pagante: {name}").format(name=self.payer_name),
            on_release=lambda *_: self._open_payer_menu(),
        )
        box.add_widget(self._wrap(self.payer_btn))

        ed = self.editing
        # Importo e valuta (precompilati in modifica)
        self.amount_field = FormTextField(
            hint_text=tr("Importo"), input_filter="float",
            text=(f"{to_money(ed.amount):.2f}" if ed else ""))
        box.add_widget(self.amount_field)

        self.currency_field = FormTextField(
            hint_text=tr("Valuta"), text=(ed.currency if ed else trip.base_currency))
        box.add_widget(self.currency_field)

        rate_text = ""
        if ed and ed.currency != trip.base_currency:
            rate_text = f"{ed.rate_to_base}"
        self.rate_field = FormTextField(
            hint_text=tr("Tasso verso {cur} (solo se valuta diversa)").format(cur=trip.base_currency),
            input_filter="float", text=rate_text)
        box.add_widget(self.rate_field)

        self.desc_field = FormTextField(
            hint_text=tr("Descrizione"), text=(ed.description if ed else ""))
        box.add_widget(self.desc_field)

        # Tipo divisione
        box.add_widget(MDLabel(text=tr("Divisione"), font_style="Subtitle2",
                               adaptive_height=True, size_hint_y=None, height="24dp"))
        self.equal_btn = MDRaisedButton(text=tr("Parti uguali"),
                                        on_release=lambda *_: self._set_mode("equal"))
        self.exact_btn = MDRaisedButton(text=tr("Importi esatti"),
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
        self.payer_btn.text = tr("Pagante: {name}").format(name=name)
        if self._menu:
            self._menu.dismiss()

    # ---- modalità divisione ---------------------------------------------
    def _set_mode(self, mode):
        self.split_mode = mode
        self.equal_btn.text = ("✓ " if mode == "equal" else "") + tr("Parti uguali")
        self.exact_btn.text = ("✓ " if mode == "exact" else "") + tr("Importi esatti")

        self.exact_box.clear_widgets()
        if mode == "exact":
            self.exact_fields = {}
            ed = getattr(self, "editing", None)
            ed_shares = {}
            if ed:
                for s in ed.splits:
                    ed_shares[s.participant_id] = to_money(s.share_base / ed.rate_to_base)
            for p in self.participants:
                field = FormTextField(hint_text=tr("Quota di {name}").format(name=p.name), input_filter="float")
                if p.id in ed_shares:
                    field.text = f"{ed_shares[p.id]:.2f}"
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
                    toast(tr("Importo non valido per {name}").format(name=name))
                    return
            split = core.SplitSpec(mode="exact", amounts=amounts)

        rate = self.rate_field.text.strip() or None
        kwargs = dict(
            payer_name=self.payer_name,
            amount=self.amount_field.text,
            description=self.desc_field.text,
            currency=self.currency_field.text or None,
            rate=rate,
            split=split,
        )
        try:
            if self.editing:
                core.update_expense(app.db, self.editing.id, **kwargs)
            else:
                core.add_expense(app.db, trip_ref=trip.id, **kwargs)
        except ValueError as exc:
            toast(str(exc))
            return
        app.editing_expense = None
        self.manager.current = "trip_detail"

    def go_back(self):
        MDApp.get_running_app().editing_expense = None
        self.manager.current = "trip_detail"
