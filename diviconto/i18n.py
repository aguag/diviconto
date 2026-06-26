"""Localizzazione minimale (Italiano / Inglese), senza dipendenze.

Le stringhe sorgente sono in **italiano** e fanno da chiave: ``tr("Accedi")``
restituisce la traduzione nella lingua corrente, oppure l'italiano stesso se la
lingua è ``it`` o se manca la traduzione. Per i testi con valori variabili si usa
``{segnaposto}`` + ``.format(...)``::

    tr("Accesso eseguito ({user})").format(user=email)

Scelta della lingua (in ordine di priorità): override esplicito (CLI ``--lang``)
→ env ``DIVICONTO_LANG`` → impostazione salvata (app) → lingua del telefono →
inglese (riserva). Vedi :func:`resolve_language` / :func:`set_language`.
"""

from __future__ import annotations

import os
from typing import Optional

SUPPORTED = ("it", "en")
FALLBACK = "en"

_lang = "it"


def _device_language() -> str:
    """Lingua del dispositivo: su Android via pyjnius, su desktop via locale."""
    try:  # Android
        from jnius import autoclass  # type: ignore

        return str(autoclass("java.util.Locale").getDefault().getLanguage())
    except Exception:
        pass
    try:  # desktop
        import locale as _locale

        code = _locale.getdefaultlocale()[0] or os.environ.get("LANG", "")
        return code[:2]
    except Exception:
        return ""


def resolve_language(saved: Optional[str] = None, explicit: Optional[str] = None) -> str:
    """Determina la lingua secondo la priorità documentata; ``en`` di riserva."""
    for cand in (explicit, os.environ.get("DIVICONTO_LANG"), saved, _device_language()):
        if cand:
            code = cand[:2].lower()
            if code in SUPPORTED:
                return code
    return FALLBACK


def set_language(lang: Optional[str]) -> None:
    global _lang
    _lang = lang if lang in SUPPORTED else FALLBACK


def get_language() -> str:
    return _lang


def tr(text: str) -> str:
    """Traduce ``text`` nella lingua corrente (italiano = identità)."""
    if _lang == "it":
        return text
    return _TRANSLATIONS.get(_lang, {}).get(text, text)


# ---------------------------------------------------------------------------
# Dizionario IT -> EN. La chiave è ESATTAMENTE la stringa italiana passata a tr().
# ---------------------------------------------------------------------------
_TRANSLATIONS = {
    "en": {
        # -- generici / pulsanti --
        "Annulla": "Cancel",
        "Conferma": "Confirm",
        "Chiudi": "Close",
        "Salva": "Save",
        "Aggiungi": "Add",
        "Crea": "Create",
        "Copia": "Copy",
        "Rimuovi": "Remove",
        "Esci": "Sign out",
        "Accedi": "Sign in",
        "Registrati": "Sign up",
        # -- Auth --
        "DiviConto — Accedi": "DiviConto — Sign in",
        "Accedi per sincronizzare le spese del tuo viaggio":
            "Sign in to sync your trip expenses",
        "Email": "Email",
        "Password": "Password",
        "Continua senza account (solo su questo telefono)":
            "Continue without an account (this phone only)",
        "Inserisci email e password": "Enter email and password",
        "Connessione…": "Connecting…",
        "Connessione non riuscita": "Connection failed",
        "Accesso eseguito ({user})": "Signed in ({user})",
        "I tuoi viaggi offline sono stati caricati sul tuo account":
            "Your offline trips were uploaded to your account",
        # -- Trips list --
        "DiviConto — Viaggi": "DiviConto — Trips",
        "Sincronizza": "Sync",
        "Unisciti a un viaggio": "Join a trip",
        "Nessun viaggio": "No trips",
        "Tocca + per crearne uno": "Tap + to create one",
        "(nessuna descrizione)": "(no description)",
        "Condiviso con: ": "Shared with: ",
        "Nuovo viaggio": "New trip",
        "Nome del viaggio": "Trip name",
        "Valuta base (es. EUR)": "Base currency (e.g. EUR)",
        "Descrizione (opzionale)": "Description (optional)",
        "Accedi per sincronizzare": "Sign in to sync",
        "Sincronizzazione…": "Syncing…",
        "Sincronizzato": "Synced",
        "Connesso: {user}": "Signed in: {user}",
        "Modalità offline (non connesso)": "Offline mode (not connected)",
        "Disconnesso": "Signed out",
        "Accedi per unirti a un viaggio": "Sign in to join a trip",
        "Codice del viaggio": "Trip code",
        "Unisciti": "Join",
        "Inserisci un codice": "Enter a code",
        "Mi unisco…": "Joining…",
        "Unito al viaggio": "Joined the trip",
        # -- Trip detail / topbar / tabs --
        "Viaggio": "Trip",
        "Condividi": "Share",
        "Gestisci viaggio": "Manage trip",
        "Spese": "Expenses",
        "Persone": "People",
        "Bilancio": "Balance",
        "Nome partecipante": "Participant name",
        # -- Condivisione (share code) --
        "Accedi per condividere il viaggio": "Sign in to share the trip",
        "Recupero codice…": "Getting code…",
        "Sincronizza prima per generare il codice": "Sync first to generate the code",
        "Codice del viaggio": "Trip code",
        "Codice copiato": "Code copied",
        # -- Menu gestione viaggio --
        "Elimina viaggio": "Delete trip",
        "Gestisci condivisione": "Manage sharing",
        "Abbandona viaggio": "Leave trip",
        "Eliminare il viaggio?": "Delete the trip?",
        "Sparirà per tutti i partecipanti alla prossima sincronizzazione.":
            "It will disappear for everyone at the next sync.",
        "Viaggio eliminato": "Trip deleted",
        "Accedi per abbandonare il viaggio": "Sign in to leave the trip",
        "Abbandonare il viaggio?": "Leave the trip?",
        "Verrà rimosso da questo dispositivo; resta per gli altri.":
            "It will be removed from this device; it stays for the others.",
        "Esco dal viaggio…": "Leaving the trip…",
        "Hai abbandonato il viaggio": "You left the trip",
        "Rimuovo…": "Removing…",
        "Rimosso {email}": "Removed {email}",
        "Revoca a tutti + nuovo codice": "Revoke for everyone + new code",
        "Revocare la condivisione a tutti?": "Revoke sharing for everyone?",
        "Gli altri membri vengono rimossi e il codice rigenerato "
        "(il vecchio non funzionerà più).":
            "The other members are removed and the code is regenerated "
            "(the old one stops working).",
        "Revoco…": "Revoking…",
        "Condivisione revocata. Nuovo codice: {code}":
            "Sharing revoked. New code: {code}",
        # -- Spese --
        "Nessuna spesa": "No expenses",
        "Spesa": "Expense",
        "(senza descrizione)": "(no description)",
        "Pagante": "Payer",
        "Tipo": "Type",
        "Importo": "Amount",
        "Quote": "Shares",
        "Parti uguali": "Equal split",
        "Importi esatti": "Exact amounts",
        "Modifica descrizione": "Edit description",
        "Modifica spesa": "Edit expense",
        "Elimina Spesa": "Delete expense",
        "Descrizione": "Description",
        "Descrizione aggiornata": "Description updated",
        "Cancellare la spesa?": "Delete the expense?",
        "Questa azione non si può annullare.": "This action cannot be undone.",
        "Spesa cancellata": "Expense deleted",
        # -- Form nuova spesa --
        "Nuova spesa": "New expense",
        "Salva spesa": "Save expense",
        "Pagante: {name}": "Payer: {name}",
        "Valuta": "Currency",
        "Tasso verso {cur} (solo se valuta diversa)":
            "Rate to {cur} (only if different currency)",
        "Divisione": "Split",
        "Quota di {name}": "{name}'s share",
        "Importo non valido per {name}": "Invalid amount for {name}",
        # -- People / Balance tab --
        "Nessun partecipante": "No participants",
        "Saldi": "Balances",
        "Conti già in pari.": "Accounts already settled.",
        "Pagamenti suggeriti": "Suggested payments",
        # -- Impostazioni --
        "Impostazioni": "Settings",
        "Lingua": "Language",
        "Italiano": "Italian",
        "English": "English",
        "Lingua cambiata": "Language changed",
        # -- spese / conferme / bilancio (aggiunte) --
        "Aggiungi prima un partecipante": "Add a participant first",
        "L'operazione non è annullabile.": "This action cannot be undone.",
        "Cancella": "Delete",
        "Condividi questo codice:\n\n[b]{code}[/b]\n\n"
        "Gli amici lo inseriscono in \"Unisciti a un viaggio\".":
            "Share this code:\n\n[b]{code}[/b]\n\n"
            "Friends enter it in \"Join a trip\".",
        "in credito": "in credit",
        "in debito": "in debt",
        "in pari": "settled",
        "{name}: {net} ({state})  — pagato {paid}, dovuto {owed}":
            "{name}: {net} ({state})  — paid {paid}, owed {owed}",
        "{debtor} deve dare {amount} a {creditor}":
            "{debtor} owes {amount} to {creditor}",
        # -- partecipante: rinomina / elimina --
        "Cosa vuoi fare con questo partecipante?":
            "What do you want to do with this participant?",
        "Correggi nome": "Edit name",
        "Elimina dal viaggio": "Remove from trip",
        "Nuovo nome": "New name",
        "Nome aggiornato": "Name updated",
        "Eliminare {name} dal viaggio?": "Remove {name} from the trip?",
        "I suoi movimenti verranno ridistribuiti agli altri partecipanti.":
            "Their movements will be redistributed to the other participants.",
        "Partecipante eliminato": "Participant removed",
        # -- errori core (messaggi sollevati come ValueError) --
        "la descrizione della spesa è obbligatoria":
            "the expense description is required",
        "nessun partecipante selezionato per la divisione":
            "no participant selected for the split",
        "divisione 'exact' senza importi": "'exact' split without amounts",
        "il nome del viaggio non può essere vuoto": "the trip name cannot be empty",
        "la valuta base è obbligatoria": "the base currency is required",
        "viaggio non trovato: {ref}": "trip not found: {ref}",
        "il nome del partecipante non può essere vuoto":
            "the participant name cannot be empty",
        "partecipante {name} già presente nel viaggio":
            "participant {name} already in the trip",
        "partecipante non trovato nel viaggio: {name}":
            "participant not found in the trip: {name}",
        "aggiungi almeno un partecipante prima di registrare spese":
            "add at least one participant before recording expenses",
        "l'importo della spesa deve essere positivo":
            "the expense amount must be positive",
        "valuta {cur} diversa dalla base {base}: "
        "serve --rate (tasso verso la valuta base)":
            "currency {cur} differs from base {base}: "
            "a --rate is required (rate to base currency)",
        "la somma delle quote ({total}) non corrisponde all'importo "
        "della spesa ({amount} {currency})":
            "the shares total ({total}) does not match the expense "
            "amount ({amount} {currency})",
        "modalità di divisione sconosciuta: {mode}":
            "unknown split mode: {mode}",
        "spesa non trovata": "expense not found",
        # -- CLI (output dei comandi) --
        "Errore: {exc}": "Error: {exc}",
        "Creato viaggio {name} ({cur}) — id {id}": "Created trip {name} ({cur}) — id {id}",
        "Nessun viaggio.": "No trips.",
        "Viaggio {name} cancellato (soft-delete). "
        "Sincronizza dall'app per propagare la cancellazione.":
            "Trip {name} deleted (soft-delete). "
            "Sync from the app to propagate the deletion.",
        "operazione online: devi essere connesso. Accedi dall'app usando lo "
        "stesso DB (variabile DIVICONTO_DB) e riprova.":
            "online operation: you must be signed in. Sign in from the app using "
            "the same DB (DIVICONTO_DB variable) and try again.",
        "Hai abbandonato il viaggio {name} (rimosso solo da questo dispositivo).":
            "You left trip {name} (removed from this device only).",
        "Rimosso {email} dal viaggio {name}.": "Removed {email} from trip {name}.",
        "Condivisione revocata per {name}. Nuovo codice: {code}":
            "Sharing revoked for {name}. New code: {code}",
        "Aggiunto partecipante {name}": "Added participant {name}",
        "Rinominato {old} in {new}": "Renamed {old} to {new}",
        "Eliminato {name}; movimenti ridistribuiti ai rimanenti.":
            "Removed {name}; movements redistributed to the others.",
        "Nessun partecipante.": "No participants.",
        "Registrata spesa {amount} (= {base}){desc}":
            "Expense recorded {amount} (= {base}){desc}",
        "Nessuna spesa.": "No expenses.",
        "Bilancio viaggio {name} (valuta {cur})": "Balance of trip {name} (currency {cur})",
        "Partecipante": "Participant",
        "Pagato": "Paid",
        "Dovuto": "Owed",
        "Saldo": "Balance",
        "Pagamenti suggeriti:": "Suggested payments:",
    },
}
