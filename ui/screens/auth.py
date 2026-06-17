"""Schermata di accesso/registrazione (Supabase Auth).

Mostrata all'avvio se non si è loggati. L'app resta comunque offline-first:
con "Continua senza account" si può lavorare in locale e accedere più tardi
per sincronizzare (i viaggi creati offline vengono caricati al primo login).
"""

from __future__ import annotations

from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen

from ui.widgets import toast


class AuthScreen(MDScreen):
    """Login/registrazione con email e password."""

    def do_login(self):
        self._authenticate(lambda app, e, p: app.sync.login(e, p))

    def do_signup(self):
        self._authenticate(lambda app, e, p: app.sync.signup(e, p))

    def use_offline(self):
        self.manager.current = "trips"

    def _authenticate(self, action):
        app = MDApp.get_running_app()
        email = self.ids.email.text.strip()
        password = self.ids.password.text
        if not email or not password:
            self.ids.status.text = "Inserisci email e password"
            return

        # C'è lavoro fatto offline (mai legato a un account) che verrà adottato
        # da questo account e caricato sul server al primo sync? Va rilevato ORA,
        # prima del login (che imposta session_user e poi sincronizza).
        offline_pending = (
            app.db.get_state("session_user") is None
            and bool(app.db.dirty_rows("trips"))
        )

        def work():
            action(app, email, password)

        def done(_result):
            self.ids.password.text = ""
            self.ids.status.text = ""
            toast(f"Accesso eseguito ({app.sync.current_user()})")
            self.manager.current = "trips"

            def after_sync(_):
                self.manager.get_screen("trips").refresh()
                if offline_pending:
                    toast("I tuoi viaggi offline sono stati caricati sul tuo account")

            # Sincronizza subito: carica l'eventuale lavoro offline e scarica i
            # dati dell'account (dopo un cambio utente la cache era stata azzerata).
            app.run_async(app.sync.sync, after_sync, lambda _e: None)

        def failed(exc):
            # Errore visibile e persistente (il toast era troppo fugace per
            # diagnosticare i problemi di connessione su telefono).
            self.ids.status.text = str(exc) or "Connessione non riuscita"

        self.ids.status.text = "Connessione…"
        app.run_async(work, done, failed)
