"""Schermata di accesso/registrazione (Supabase Auth).

Mostrata all'avvio se non si è loggati. L'app resta comunque offline-first:
con "Usa offline" si può lavorare in locale e accedere più tardi per
sincronizzare.
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
            toast("Inserisci email e password")
            return

        def work():
            action(app, email, password)

        def done(_result):
            self.ids.password.text = ""
            toast(f"Accesso eseguito ({app.sync.current_user()})")
            self.manager.current = "trips"

        toast("Connessione…")
        app.run_async(work, done, lambda exc: toast(str(exc)))
