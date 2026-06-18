# Piano: DiviConto — CLI per dividere spese tra amici

> Piano approvato e implementato nella fase 1 (CLI). Conservato per riferimento
> e per pianificare le fasi successive (UI, sincronizzazione).

## Context

Serve un'app per dividere le spese di un viaggio tra N amici. Si parte da una
**CLI** (questa fase) e in seguito si aggiungerà una **UI**, con l'obiettivo di
girare sia su **Linux (Fedora 41)** sia su **Android**. I dati vanno in un DB
che oggi è **locale** ma il codice deve essere progettato per aggiungere
**sync/condivisione in futuro** senza riscrivere tutto.

Decisioni concordate con l'utente:
- **DB:** file locale ora (SQLite), progettato per sync futura.
- **Partecipanti:** N per viaggio.
- **Valuta:** multi-valuta, **tasso di cambio inserito a mano** per spesa, con una valuta base del viaggio.
- **Divisione spesa:** *parti uguali* + *importi esatti* (design estensibile per % e quote in futuro).
- **Balance:** saldo netto per persona **+** pagamenti minimi suggeriti (chi paga chi).

## Scelta tecnologica

**Python 3 + solo libreria standard** (`sqlite3`, `argparse`, `decimal`, `uuid`, `datetime`, `json`).

Perché Python (non C):
- `sqlite3` e `argparse` (con `-h` automatico) sono già nella stdlib → **zero dipendenze esterne**, massima portabilità.
- Gira nativamente su Fedora 41 e su Android via **Termux** (CPython). La futura UI Android userà framework Python (Kivy/BeeWare) e potrà **riusare lo stesso modulo core**.
- `decimal.Decimal` per i soldi → niente errori di arrotondamento dei float.

## Architettura (a strati, per riusare il core con UI e sync futuri)

Package `src/` (storicamente chiamato `diviconto/`):
- `money.py` — helper `Decimal`, arrotondamento a 2 decimali, conversione `amount * rate → base`.
- `models.py` — dataclasses: `Trip`, `Participant`, `Expense`, `Split`.
- `db.py` — connessione SQLite, creazione schema/migrazioni, repository (CRUD). **Unico punto che tocca lo storage** → in futuro si sostituisce/affianca con un backend sync senza toccare il resto.
- `core.py` — logica di business pura (crea viaggio, aggiungi partecipante/spesa, calcola balance). Nessun `print` → riusabile dalla UI.
- `balance.py` — calcolo saldo netto + algoritmo greedy dei pagamenti minimi (chi paga chi).
- `cli.py` — strato sottile su `core` con `argparse` (sottocomandi + `-h`).
- `__main__.py` — permette `python -m src`.
- Script wrapper `divc` (eseguibile) in root.

### Scelte pro-sync futura (a costo quasi zero ora)
- **PK come UUID testo** (non autoincrement) → niente collisioni di id tra dispositivi quando si introdurrà il merge.
- Colonne `created_at`, `updated_at` (ISO 8601) e `deleted` (soft-delete) su ogni tabella → base per una sincronizzazione futura.

## Modello dati (SQLite)

- `trips(id PK uuid, name, description, base_currency, created_at, updated_at, deleted)`
- `participants(id PK uuid, trip_id FK, name, created_at, updated_at, deleted)`
- `expenses(id PK uuid, trip_id FK, payer_id FK, amount, currency, rate_to_base, amount_base, description, created_at, updated_at, deleted)`
- `splits(id PK uuid, expense_id FK, participant_id FK, mode, share_base, created_at, updated_at, deleted)`
  - `mode` = `equal` | `exact`. Si memorizza la **quota dovuta risolta in valuta base** (`share_base`) per ogni partecipante coinvolto → il balance diventa una semplice SUM e resta verificabile.

Importi salvati come **TEXT** e riletti come `Decimal` per fedeltà.

### Logica valuta
Ogni spesa salva `amount` + `currency` + `rate_to_base` (1.0 se = valuta base) + `amount_base = amount * rate`. Tutti i balance sono in valuta base del viaggio.

### Logica divisione
- `equal`: importo base diviso tra i partecipanti selezionati (default tutti); l'ultima quota assorbe l'arrotondamento così la somma torna esatta.
- `exact`: importo esplicito per partecipante (in valuta della spesa); si valida che la somma delle quote == importo della spesa.

### Balance
Per ogni partecipante: `netto = (somma pagato come payer) − (somma share_base dovute)`. Netto positivo = creditore.
**Settlement:** algoritmo greedy che abbina il maggior creditore al maggior debitore finché tutti tornano a zero → numero minimo di pagamenti.

## Interfaccia CLI

`diviconto -h` e `-h` su ogni sottocomando (gratis con argparse). Posizione DB: default `~/.diviconto/diviconto.db`, override con `--db` o env `DIVICONTO_DB` (path valido anche su Termux/Android).

Comandi:
- `diviconto trip create --name --currency EUR [--desc ...]`
- `diviconto trip list`
- `diviconto person add --trip <id|nome> --name <nome>`
- `diviconto person list --trip <id|nome>`
- `diviconto expense add --trip <t> --payer <nome> --amount 50 [--currency USD --rate 0.92] --desc "Cena" --split equal`
  (`--split equal:Anna,Bob` / `--split exact:Anna=30,Bob=20`)
- `diviconto expense list --trip <t>`
- `diviconto balance --trip <t>` → tabella saldi netti + lista "X deve dare N€ a Y"

## Stato implementazione (fase 1 — completata)

- [x] Package a strati con sola libreria standard
- [x] Schema SQLite + repository
- [x] Divisione `equal` ed `exact`, multi-valuta con tasso manuale
- [x] Bilancio netto + pagamenti di pareggio
- [x] CLI con `-h` su tutti i comandi
- [x] 19 test (unittest) + verifica end-to-end

## Fuori scope (fasi successive)
- UI (Kivy/BeeWare per Android), riusando `core.py` e `db.py`
- Sincronizzazione/condivisione reale del DB (cloud file o server)
- Recupero tassi via API
- Divisione per percentuale e per quote
