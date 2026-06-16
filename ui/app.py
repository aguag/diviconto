"""Applicazione Kivy/KivyMD di DiviConto.

Apre un'unica connessione al DB (riusando ``diviconto.db.Database``) salvato
nella cartella dati dell'app, scrivibile sia su Linux sia su Android. Gestisce
anche il client di sincronizzazione (Supabase) e un helper per eseguire le
operazioni di rete fuori dal thread della UI.
"""

from __future__ import annotations

import os
import threading

from kivy.clock import Clock
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, SlideTransition
from kivymd.app import MDApp

from diviconto.db import Database
from diviconto.sync import SyncClient
from ui.screens.auth import AuthScreen
from ui.screens.expense_form import ExpenseFormScreen
from ui.screens.trip_detail import TripDetailScreen
from ui.screens.trips import TripsScreen

KV_PATH = os.path.join(os.path.dirname(__file__), "diviconto.kv")


class DiviContoApp(MDApp):
    """App principale: tiene il DB aperto e gestisce schermate e sync."""

    def build(self):
        self.theme_cls.primary_palette = "Teal"
        self.theme_cls.theme_style = "Light"

        # Default: DB nella cartella dati dell'app (valida anche su Android).
        # La variabile DIVICONTO_DB la sovrascrive (utile per test/più "dispositivi").
        db_path = os.environ.get("DIVICONTO_DB") or os.path.join(
            self.user_data_dir, "diviconto.db"
        )
        self.db = Database(db_path)
        self.sync = SyncClient(self.db)
        self.current_trip = None  # viaggio selezionato (impostato da TripsScreen)

        Builder.load_file(KV_PATH)

        sm = ScreenManager(transition=SlideTransition())
        sm.add_widget(AuthScreen(name="auth"))
        sm.add_widget(TripsScreen(name="trips"))
        sm.add_widget(TripDetailScreen(name="trip_detail"))
        sm.add_widget(ExpenseFormScreen(name="expense_form"))
        # Se già loggato si va diritti ai viaggi, altrimenti alla schermata auth.
        sm.current = "trips" if self.sync.is_logged_in() else "auth"
        return sm

    def run_async(self, func, on_done=None, on_error=None):
        """Esegue ``func`` in un thread; le callback tornano sul thread UI."""
        def worker():
            try:
                result = func()
            except Exception as exc:  # noqa: BLE001 - mostrato all'utente
                if on_error:
                    Clock.schedule_once(lambda _dt, e=exc: on_error(e))
                return
            if on_done:
                Clock.schedule_once(lambda _dt, r=result: on_done(r))

        threading.Thread(target=worker, daemon=True).start()

    def on_stop(self):
        if getattr(self, "db", None):
            self.db.close()


def main():
    DiviContoApp().run()


if __name__ == "__main__":
    main()
