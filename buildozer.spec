[app]

# Nome visualizzato e nome pacchetto
title = DiviConto
package.name = diviconto
package.domain = org.diviconto

# Sorgenti: la root del progetto (include sia ui/ sia il core diviconto/)
source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,ttf,atlas
# Includi esplicitamente i package Python necessari
source.include_patterns = ui/*,ui/screens/*,diviconto/*

# File principale avviato sul dispositivo
# (Buildozer cerca main.py nella source.dir)

version = 0.1.0

# Icona dell'app (generata da tools/make_icon.py)
icon.filename = %(source.dir)s/data/icon.png

# Dipendenze: il core usa solo la stdlib; sqlite3 è incluso in python-for-android.
# openssl serve per le chiamate HTTPS (urllib) della sincronizzazione con Supabase.
requirements = python3,kivy==2.3.1,kivymd==1.2.0,openssl

orientation = portrait
fullscreen = 0

[android]

# API target/minima ragionevoli (aggiornabili in base all'SDK installato)
android.api = 33
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a

# INTERNET serve per la sincronizzazione con Supabase (il DB resta comunque locale)
android.permissions = android.permission.INTERNET

# Accetta automaticamente le licenze dell'SDK durante il primo build
android.accept_sdk_license = True

[buildozer]

log_level = 2
warn_on_root = 1
