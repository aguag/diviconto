"""Dettaglio di un viaggio: spese, partecipanti e bilancio (3 tab)."""

from __future__ import annotations

from datetime import datetime

from kivymd.app import MDApp
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.list import OneLineListItem, TwoLineListItem
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from diviconto import core
from diviconto.money import format_money
from ui.widgets import toast


def _format_when(iso_ts: str) -> str:
    """Formatta un timestamp ISO (UTC) come data/ora locale leggibile."""
    try:
        return datetime.fromisoformat(iso_ts).astimezone().strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return iso_ts or ""


class TripDetailScreen(MDScreen):
    """Schermata con bottom navigation: Spese / Partecipanti / Bilancio."""

    _dialog = None

    def on_pre_enter(self, *args):
        app = MDApp.get_running_app()
        trip = app.current_trip
        if trip is None:
            self.manager.current = "trips"
            return
        self.ids.topbar.title = f"{trip.name} [{trip.base_currency}]"
        self.refresh_all()

    def on_enter(self, *args):
        # Sync automatico all'apertura del viaggio (se loggati), senza bloccare.
        app = MDApp.get_running_app()
        if app.sync.is_logged_in():
            app.run_async(app.sync.sync, lambda _: self.refresh_all(), lambda _exc: None)

    def refresh_all(self):
        self.refresh_expenses()
        self.refresh_people()
        self.refresh_balance()

    def go_back(self):
        self.manager.current = "trips"

    def do_sync(self):
        app = MDApp.get_running_app()
        if not app.sync.is_logged_in():
            toast("Accedi per sincronizzare")
            return
        toast("Sincronizzazione…")

        def done(_):
            self.refresh_all()
            toast("Sincronizzato")

        app.run_async(app.sync.sync, done, lambda exc: toast(str(exc)))

    # ---- Condivisione ----------------------------------------------------
    def show_share_code(self):
        app = MDApp.get_running_app()
        if not app.sync.is_logged_in():
            toast("Accedi per condividere il viaggio")
            return
        trip_id = app.current_trip.id
        toast("Recupero codice…")

        def done(code):
            if not code:
                toast("Sincronizza prima per generare il codice")
                return
            self._dialog = MDDialog(
                # auto_dismiss=False: si chiude solo coi pulsanti. Senza questo,
                # il rilascio del tocco che ha aperto il dialog cade fuori da esso
                # e lo chiuderebbe subito (il sync è veloce e apre a metà tocco).
                auto_dismiss=False,
                title="Codice del viaggio",
                text=f"Condividi questo codice:\n\n[b]{code}[/b]\n\n"
                     "Gli amici lo inseriscono in \"Unisciti a un viaggio\".",
                buttons=[
                    MDFlatButton(text="Copia", on_release=lambda *_: self._copy_code(code)),
                    MDFlatButton(text="Chiudi", on_release=lambda *_: self._dialog.dismiss()),
                ],
            )
            self._dialog.open()

        # Prima sincronizza (così il viaggio esiste lato server), poi legge il codice.
        def work():
            app.sync.sync()
            return app.sync.share_code(trip_id)

        app.run_async(work, done, lambda exc: toast(str(exc)))

    def _copy_code(self, code: str):
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(code)
        toast("Codice copiato")

    # ---- Spese -----------------------------------------------------------
    def refresh_expenses(self):
        app = MDApp.get_running_app()
        trip = app.current_trip
        lst = self.ids.expense_list
        lst.clear_widgets()
        people = {p.id: p.name for p in app.db.list_participants(trip.id)}
        expenses = app.db.list_expenses(trip.id)
        if not expenses:
            lst.add_widget(OneLineListItem(text="Nessuna spesa"))
            return
        for e in expenses:
            payer = people.get(e.payer_id, "?")
            amount = format_money(e.amount, e.currency)
            if e.currency != trip.base_currency:
                amount += f" = {format_money(e.amount_base, trip.base_currency)}"
            desc = e.description or "(senza descrizione)"
            item = TwoLineListItem(
                text=f"{payer}: {amount}",
                secondary_text=f"{desc} · {_format_when(e.created_at)}",
            )
            item.bind(on_release=lambda _w, exp=e: self.open_expense_actions(exp))
            lst.add_widget(item)

    def open_expense_form(self):
        app = MDApp.get_running_app()
        if not app.db.list_participants(app.current_trip.id):
            toast("Aggiungi prima un partecipante")
            return
        self.manager.current = "expense_form"

    # ---- Azioni su una spesa (modifica descrizione / cancella) ------------
    def open_expense_actions(self, exp):
        self._dialog = MDDialog(
            auto_dismiss=False,
            title="Spesa",
            text=exp.description or "(senza descrizione)",
            buttons=[
                MDFlatButton(text="Modifica descrizione",
                             on_release=lambda *_: self._edit_description(exp)),
                MDFlatButton(text="Cancella", theme_text_color="Custom",
                             text_color=(0.8, 0, 0, 1),
                             on_release=lambda *_: self._confirm_delete(exp)),
                MDFlatButton(text="Chiudi", on_release=lambda *_: self._dialog.dismiss()),
            ],
        )
        self._dialog.open()

    def _edit_description(self, exp):
        self._dialog.dismiss()
        self._edit_field = MDTextField(text=exp.description, hint_text="Descrizione")
        self._dialog = MDDialog(
            auto_dismiss=False,
            title="Modifica descrizione",
            type="custom",
            content_cls=self._edit_field,
            buttons=[
                MDFlatButton(text="Annulla", on_release=lambda *_: self._dialog.dismiss()),
                MDRaisedButton(text="Salva", on_release=lambda *_: self._save_description(exp)),
            ],
        )
        self._dialog.open()

    def _save_description(self, exp):
        app = MDApp.get_running_app()
        try:
            core.update_expense_description(app.db, exp.id, self._edit_field.text)
        except ValueError as exc:
            toast(str(exc))
            return
        self._dialog.dismiss()
        self.refresh_expenses()
        toast("Descrizione aggiornata")

    def _confirm_delete(self, exp):
        self._dialog.dismiss()
        self._dialog = MDDialog(
            auto_dismiss=False,
            title="Cancellare la spesa?",
            text=f"{exp.description or '(senza descrizione)'}\nL'operazione non è annullabile.",
            buttons=[
                MDFlatButton(text="Annulla", on_release=lambda *_: self._dialog.dismiss()),
                MDRaisedButton(text="Cancella", md_bg_color=(0.8, 0, 0, 1),
                               on_release=lambda *_: self._do_delete(exp)),
            ],
        )
        self._dialog.open()

    def _do_delete(self, exp):
        app = MDApp.get_running_app()
        core.delete_expense(app.db, exp.id)
        self._dialog.dismiss()
        self.refresh_expenses()
        self.refresh_balance()
        toast("Spesa cancellata")

    # ---- Partecipanti ----------------------------------------------------
    def refresh_people(self):
        app = MDApp.get_running_app()
        trip = app.current_trip
        lst = self.ids.people_list
        lst.clear_widgets()
        people = app.db.list_participants(trip.id)
        if not people:
            lst.add_widget(OneLineListItem(text="Nessun partecipante"))
            return
        for p in people:
            lst.add_widget(OneLineListItem(text=p.name))

    def add_person(self):
        app = MDApp.get_running_app()
        field = self.ids.new_person
        try:
            core.add_participant(app.db, app.current_trip.id, field.text)
        except ValueError as exc:
            toast(str(exc))
            return
        field.text = ""
        self.refresh_people()
        self.refresh_balance()

    # ---- Bilancio --------------------------------------------------------
    def refresh_balance(self):
        app = MDApp.get_running_app()
        box = self.ids.balance_box
        box.clear_widgets()
        bal = core.compute_balance(app.db, app.current_trip.id)
        cur = bal.base_currency

        box.add_widget(self._row("Saldi", bold=True))
        for name in bal.net:
            net = bal.net[name]
            stato = "in credito" if net > 0 else ("in debito" if net < 0 else "in pari")
            box.add_widget(self._row(
                f"{name}: {format_money(net, cur)} ({stato})  "
                f"— pagato {format_money(bal.paid[name])}, "
                f"dovuto {format_money(bal.owed[name])}"
            ))

        box.add_widget(self._row(""))
        if not bal.settlements:
            box.add_widget(self._row("Conti già in pari.", bold=True))
            return
        box.add_widget(self._row("Pagamenti suggeriti", bold=True))
        for s in bal.settlements:
            box.add_widget(self._row(
                f"  {s.debtor} deve dare {format_money(s.amount, cur)} a {s.creditor}"
            ))

    @staticmethod
    def _row(text: str, bold: bool = False) -> MDLabel:
        return MDLabel(
            text=f"[b]{text}[/b]" if bold else text,
            markup=True,
            font_style="Subtitle1" if bold else "Body2",
            adaptive_height=True,
            size_hint_y=None,
            height="28dp",
        )
