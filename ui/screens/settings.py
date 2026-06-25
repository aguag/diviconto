"""Schermata Impostazioni: scelta della lingua (Italiano / English).

Cambiare lingua salva la scelta e ricostruisce le schermate (vedi
``DiviContoApp.change_language``), così l'effetto è immediato pur essendo, di
fatto, una ricostruzione "al riavvio" senza binding reattivi.
"""

from __future__ import annotations

from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen

from diviconto import i18n


class SettingsScreen(MDScreen):
    def go_back(self):
        self.manager.current = "trips"

    def set_language(self, lang: str):
        if lang == i18n.get_language():
            self.manager.current = "trips"
            return
        # Ricostruisce la UI nella nuova lingua; resta sulla schermata corrente.
        MDApp.get_running_app().change_language(lang)
