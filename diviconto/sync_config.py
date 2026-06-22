"""Configurazione del backend di sincronizzazione (Supabase).

Project URL e chiave **anon public** sono valori PUBBLICI: la chiave anon è
protetta dalla Row Level Security lato server, quindi è normale includerla
nell'app/APK. NON mettere qui la service_role key né la password del database.

I valori si possono sovrascrivere con le variabili d'ambiente ``SUPABASE_URL``
e ``SUPABASE_ANON_KEY`` (comodo per CLI di test e per ambienti diversi).
"""

from __future__ import annotations

import os

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL",
    "https://lfobubjragylzprrpqme.supabase.co",
)

SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imxmb2J1YmpyYWd5bHpwcnJwcW1lIiwicm9sZSI6"
    "ImFub24iLCJpYXQiOjE3ODE1OTMxNjgsImV4cCI6MjA5NzE2OTE2OH0."
    "u54IucWWumT60NHlh2I3D-pFUwdizlBlVHG1HgrxLfI",
)
