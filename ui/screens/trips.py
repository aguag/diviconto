"""Schermata elenco viaggi + creazione di un nuovo viaggio."""

from __future__ import annotations

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import ThreeLineListItem, TwoLineListItem
from kivymd.uix.screen import MDScreen

from diviconto import core
from ui.widgets import FormTextField, toast


class TripsScreen(MDScreen):
    """Mostra i viaggi salvati e permette di crearne di nuovi."""

    _dialog = None

    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self):
        app = MDApp.get_running_app()
        self._update_account_bar(app)
        container = self.ids.trip_list
        container.clear_widgets()
        trips = app.db.list_trips()
        if not trips:
            container.add_widget(
                TwoLineListItem(text="Nessun viaggio", secondary_text="Tocca + per crearne uno")
            )
            return
        members = app.db.members_by_trip()
        me = app.sync.current_user()
        for trip in trips:
            secondary = trip.description or "(nessuna descrizione)"
            title = f"{trip.name}  [{trip.base_currency}]"
            # Mostra con chi è condiviso: gli altri membri (esclude te stesso).
            others = [e for e in members.get(trip.id, []) if e and e != me]
            if others:
                item = ThreeLineListItem(
                    text=title,
                    secondary_text=secondary,
                    tertiary_text="Condiviso con: " + ", ".join(others),
                )
            else:
                item = TwoLineListItem(text=title, secondary_text=secondary)
            item.bind(on_release=lambda _w, t=trip: self.open_trip(t))
            container.add_widget(item)

    def open_trip(self, trip):
        app = MDApp.get_running_app()
        app.current_trip = trip
        self.manager.current = "trip_detail"

    # ---- dialog nuovo viaggio --------------------------------------------
    def open_new_trip_dialog(self):
        self._name = FormTextField(hint_text="Nome del viaggio")
        self._currency = FormTextField(hint_text="Valuta base (es. EUR)", text="EUR")
        self._desc = FormTextField(hint_text="Descrizione (opzionale)")
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

    # ---- Account (connesso / offline) ------------------------------------
    def _update_account_bar(self, app):
        if app.sync.is_logged_in():
            self.ids.account_label.text = f"Connesso: {app.sync.current_user()}"
            self.ids.account_btn.text = "Esci"
        else:
            self.ids.account_label.text = "Modalità offline (non connesso)"
            self.ids.account_btn.text = "Accedi"

    def account_action(self):
        """Esce se connesso, altrimenti porta alla schermata di accesso."""
        app = MDApp.get_running_app()
        if app.sync.is_logged_in():
            self.do_logout()
        else:
            self.manager.current = "auth"

    def do_logout(self):
        app = MDApp.get_running_app()
        app.sync.logout()
        toast("Disconnesso")
        self.refresh()  # resta sui viaggi in modalità offline

    # ---- Unisciti a un viaggio con codice --------------------------------
    def open_join_dialog(self):
        app = MDApp.get_running_app()
        if not app.sync.is_logged_in():
            toast("Accedi per unirti a un viaggio")
            self.manager.current = "auth"
            return
        self._code = FormTextField(hint_text="Codice del viaggio")
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
