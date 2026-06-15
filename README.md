# DiviConto

CLI per dividere le spese di un viaggio tra amici. Scritta in **Python con
sola libreria standard** (nessuna dipendenza esterna) → gira su **Linux
(Fedora 41)** e su **Android via Termux**. I dati sono salvati in un DB
**SQLite** locale, con un'architettura predisposta per una futura
sincronizzazione tra dispositivi e per una UI.

## Requisiti
- Python 3.9+ (su Fedora già presente; su Android: `pkg install python` in Termux)

## Uso rapido

Senza installazione, dalla cartella del progetto:

```bash
./divc -h                  # help generale
python -m diviconto -h     # equivalente
```

Help di ogni sottocomando con `-h`, es. `./divc expense add -h`.

### Esempio completo

```bash
./divc trip create --name "Spagna" --currency EUR --desc "Estate"
./divc person add --trip Spagna --name Anna
./divc person add --trip Spagna --name Bob

# Spesa in valuta base, divisa in parti uguali tra tutti
./divc expense add --trip Spagna --payer Anna --amount 100 --desc Cena --split equal

# Spesa in valuta diversa: serve il tasso verso la valuta base
./divc expense add --trip Spagna --payer Bob --amount 50 --currency USD \
    --rate 0.92 --desc Benzina --split equal:Anna,Bob

# Spesa con importi esatti (nella valuta della spesa)
./divc expense add --trip Spagna --payer Anna --amount 60 --desc Hotel \
    --split exact:Anna=40,Bob=20

./divc expense list --trip Spagna
./divc balance --trip Spagna
```

## Posizione del database
Default: `~/.diviconto/diviconto.db`. Si può cambiare con `--db PATH`
oppure con la variabile d'ambiente `DIVICONTO_DB`.

## Criteri di divisione
- `equal` — parti uguali tra tutti i partecipanti
- `equal:Anna,Bob` — parti uguali solo tra i nominati
- `exact:Anna=30,Bob=20` — importi esatti (nella valuta della spesa); la
  somma deve coincidere con l'importo della spesa

## Multi-valuta
Ogni viaggio ha una **valuta base**. Le spese in altra valuta richiedono il
tasso di cambio (`--rate`), inserito manualmente: tutto il bilancio è
calcolato nella valuta base.

## Bilancio
`balance` mostra, per ogni persona, quanto ha **pagato**, quanto **doveva** e
il **saldo netto**, più i **pagamenti minimi** suggeriti per pareggiare i conti.

## Installazione (opzionale)
```bash
pip install --user .
diviconto -h
```

## Test
```bash
python -m unittest discover -s tests
```

## Architettura
- `diviconto/money.py` — importi con `Decimal` e conversione valuta
- `diviconto/models.py` — dataclasses del dominio
- `diviconto/db.py` — storage SQLite (unico punto di persistenza)
- `diviconto/balance.py` — saldi netti + pagamenti di pareggio
- `diviconto/core.py` — logica di business (riusabile dalla futura UI)
- `diviconto/cli.py` — interfaccia a riga di comando

I prossimi passi previsti: UI (Kivy/BeeWare per Android), sincronizzazione
del DB, divisione per percentuale/quote.
