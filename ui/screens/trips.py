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
