"""Applicazione Kivy/KivyMD di DiviConto.

Apre un'unica connessione al DB (riusando ``diviconto.db.Database``) salvato
nella cartella dati dell'app, scrivibile sia su Linux sia su Android.
"""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, SlideTransition
from kivymd.app import MDApp

from diviconto.db import Database
from ui.screens.expense_form import ExpenseFormScreen
from ui.screens.trip_detail import TripDetailScreen
from ui.screens.trips import TripsScreen

KV_PATH = os.path.join(os.path.dirname(__file__), "diviconto.kv")


class DiviContoApp(MDApp):
    """App principale: tiene il DB aperto e gestisce le schermate."""

    def build(self):
        self.theme_cls.primary_palette = "Teal"
        self.theme_cls.theme_style = "Light"

        db_path = os.path.join(self.user_data_dir, "diviconto.db")
        self.db = Database(db_path)
        self.current_trip = None  # viaggio selezionato (impostato da TripsScreen)

        Builder.load_file(KV_PATH)

        sm = ScreenManager(transition=SlideTransition())
        sm.add_widget(TripsScreen(name="trips"))
        sm.add_widget(TripDetailScreen(name="trip_detail"))
        sm.add_widget(ExpenseFormScreen(name="expense_form"))
        return sm

    def on_stop(self):
        if getattr(self, "db", None):
            self.db.close()


def main():
    DiviContoApp().run()


if __name__ == "__main__":
    main()
