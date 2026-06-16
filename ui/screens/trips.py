"""Schermata elenco viaggi + creazione di un nuovo viaggio."""

from __future__ import annotations

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import TwoLineListItem
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from diviconto import core
from ui.widgets import toast


class TripsScreen(MDScreen):
    """Mostra i viaggi salvati e permette di crearne di nuovi."""

    _dialog = None

    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self):
        app = MDApp.get_running_app()
        container = self.ids.trip_list
        container.clear_widgets()
        trips = app.db.list_trips()
        if not trips:
            container.add_widget(
                TwoLineListItem(text="Nessun viaggio", secondary_text="Tocca + per crearne uno")
            )
            return
        for trip in trips:
            secondary = trip.description or "(nessuna descrizione)"
            item = TwoLineListItem(
                text=f"{trip.name}  [{trip.base_currency}]",
                secondary_text=secondary,
            )
            item.bind(on_release=lambda _w, t=trip: self.open_trip(t))
            container.add_widget(item)

    def open_trip(self, trip):
        app = MDApp.get_running_app()
        app.current_trip = trip
        self.manager.current = "trip_detail"

    # ---- dialog nuovo viaggio --------------------------------------------
    def open_new_trip_dialog(self):
        self._name = MDTextField(hint_text="Nome del viaggio")
        self._currency = MDTextField(hint_text="Valuta base (es. EUR)", text="EUR")
        self._desc = MDTextField(hint_text="Descrizione (opzionale)")
        content = MDBoxLayout(
            orientation="vertical",
            spacing="12dp",
            size_hint_y=None,
            height="180dp",
        )
        content.add_widget(self._name)
        content.add_widget(self._currency)
        content.add_widget(self._desc)

        self._dialog = MDDialog(
            title="Nuovo viaggio",
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text="Annulla", on_release=lambda *_: self._dialog.dismiss()),
                MDRaisedButton(text="Crea", on_release=lambda *_: self._create_trip()),
            ],
        )
        self._dialog.open()

    def _create_trip(self):
        app = MDApp.get_running_app()
        try:
            core.create_trip(
                app.db,
                name=self._name.text,
                currency=self._currency.text,
                description=self._desc.text,
            )
        except ValueError as exc:
            toast(str(exc))
            return
        self._dialog.dismiss()
        self.refresh()

    # ---- Sincronizzazione -------------------------------------------------
    def do_sync(self):
        app = MDApp.get_running_app()
        if not app.sync.is_logged_in():
            toast("Accedi per sincronizzare")
            self.manager.current = "auth"
            return
        toast("Sincronizzazione…")

        def done(_):
            self.refresh()
            toast("Sincronizzato")

        app.run_async(app.sync.sync, done, lambda exc: toast(str(exc)))

    def do_logout(self):
        app = MDApp.get_running_app()
        app.sync.logout()
        toast("Disconnesso")
        self.manager.current = "auth"

    # ---- Unisciti a un viaggio con codice --------------------------------
    def open_join_dialog(self):
        app = MDApp.get_running_app()
        if not app.sync.is_logged_in():
            toast("Accedi per unirti a un viaggio")
            self.manager.current = "auth"
            return
        self._code = MDTextField(hint_text="Codice del viaggio")
        self._dialog = MDDialog(
            title="Unisciti a un viaggio",
            type="custom",
            content_cls=self._code,
            buttons=[
                MDFlatButton(text="Annulla", on_release=lambda *_: self._dialog.dismiss()),
                MDRaisedButton(text="Unisciti", on_release=lambda *_: self._join()),
            ],
        )
        self._dialog.open()

    def _join(self):
        app = MDApp.get_running_app()
        code = self._code.text.strip()
        if not code:
            toast("Inserisci un codice")
            return
        self._dialog.dismiss()
        toast("Mi unisco…")

        def done(_):
            self.refresh()
            toast("Unito al viaggio")

        app.run_async(lambda: app.sync.join_trip(code), done, lambda exc: toast(str(exc)))
