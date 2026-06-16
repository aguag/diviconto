# Architettura di DiviConto

Documento tecnico per chi sviluppa. Per l'uso quotidiano vedi il
[README](../README.md).

## Principio guida

Codice **a strati** con un'unica responsabilità per modulo, così la logica di
business è indipendente sia dall'interfaccia (CLI e UI Kivy) sia dallo storage
(SQLite locale, con sincronizzazione opzionale verso Supabase).

```
            ┌─────────────┐        ┌──────────────────┐
            │   cli.py    │        │  ui/ (Kivy/KivyMD)│
            │  (argparse) │        │                  │
            └──────┬──────┘        └────────┬─────────┘
                   │  (stesse chiamate)     │
                   └───────────┬────────────┘
                               ▼
                          ┌─────────┐
                          │ core.py │  logica di business (no I/O di stampa)
                          └────┬────┘
                  ┌────────────┼────────────┐
                  ▼            ▼            ▼
            ┌──────────┐ ┌──────────┐ ┌──────────┐
            │ money.py │ │balance.py│ │  db.py   │ ← unico accesso ai dati
            └──────────┘ └──────────┘ └────┬─────┘
                                           │
                                      ┌────▼────┐     ┌───────────┐
                                      │ SQLite  │◄───►│ sync.py   │──► Supabase
                                      └─────────┘     └───────────┘   (cloud)
```

## Moduli

| Modulo | Responsabilità | Note |
|--------|----------------|------|
| [money.py](../diviconto/money.py) | Importi `Decimal`, arrotondamento a 2 cifre, conversione valuta | Mai `float` per i soldi |
| [models.py](../diviconto/models.py) | Dataclasses: `Trip`, `Participant`, `Expense`, `Split`, `Balance`, `Settlement` | Solo dati |
| [db.py](../diviconto/db.py) | Schema, CRUD, mapping riga↔oggetto | **Unico punto di persistenza** |
| [balance.py](../diviconto/balance.py) | Saldi netti + settlement greedy | Funzioni pure |
| [core.py](../diviconto/core.py) | Orchestrazione: crea viaggio, aggiungi spesa, calcola bilancio | Solleva `ValueError`, non stampa |
| [cli.py](../diviconto/cli.py) | Parsing argomenti e output | Strato sottile su `core` |
| [sync.py](../diviconto/sync.py) | Sincronizzazione con Supabase (auth + push/pull) | Solo `urllib` (stdlib) |
| [sync_config.py](../diviconto/sync_config.py) | URL + chiave anon del progetto Supabase | Valori pubblici, override da env |

## Modello dati

Quattro tabelle (`trips`, `participants`, `expenses`, `splits`). Ogni tabella ha:
- **`id`**: UUID testuale (no autoincrement) → evita collisioni tra dispositivi.
- **`created_at` / `updated_at`**: timestamp ISO 8601 UTC.
- **`deleted`**: flag per soft-delete.
- **`dirty`**: flag locale (1 = riga da inviare al server al prossimo sync).

Queste scelte sono le fondamenta della **sincronizzazione** (merge per id,
last-write-wins su `updated_at`, tombstone via `deleted`). C'è inoltre una
tabella `sync_state(key, value)` per il watermark di pull, i token di sessione
e l'utente corrente. Vedi la sezione *Sincronizzazione*.

### Quote (`splits`)
Per ogni spesa si salva una riga per partecipante coinvolto con la
**quota dovuta già risolta in valuta base** (`share_base`). Vantaggi:
- il bilancio è una semplice somma (`paid - owed`);
- resta verificabile a posteriori com'è stata divisa ogni spesa.

## Calcolo del bilancio

1. `paid[p]` = somma `amount_base` delle spese dove `p` è il payer.
2. `owed[p]` = somma `share_base` delle quote a carico di `p`.
3. `net[p] = paid[p] - owed[p]` (positivo = creditore).
4. **Settlement**: algoritmo greedy che abbina il maggior debitore al maggior
   creditore per la cifra minima tra i due, finché tutti i saldi sono a zero →
   numero minimo di pagamenti.

## Gestione valuta

Ogni viaggio ha una **valuta base**. Una spesa in altra valuta richiede un
`rate_to_base` (inserito a mano). Si memorizzano sia l'importo originale sia
`amount_base = amount * rate`. Tutti i calcoli usano la valuta base.

## Arrotondamenti

Le divisioni possono generare resti di centesimi. Convenzione: l'**ultima quota
assorbe il resto**, così la somma delle quote coincide sempre esattamente con
l'importo della spesa e i netti sommano a zero.

## Sincronizzazione (Supabase)

Backend **offline-first**: il SQLite locale resta la fonte primaria; il sync
scambia solo le righe cambiate. Lo strato è in [sync.py](../diviconto/sync.py)
(classe `SyncClient`) e usa **solo `urllib`** (nessuna dipendenza nuova, identico
su desktop e Android). Schema server in [supabase/schema.sql](../supabase/schema.sql).

- **Auth**: Supabase Auth (GoTrue) via REST — `signup`/`login`/`logout`, refresh
  automatico del token. Token e utente salvati in `sync_state`.
- **Push**: per ogni tabella, le righe `dirty=1` vengono inviate in **upsert**
  (`Prefer: resolution=merge-duplicates`) a PostgREST; poi marcate `dirty=0`.
  L'`updated_at` lo assegna il **server** (trigger `now()`), così gli orologi
  sfasati tra telefoni non contano.
- **Pull**: si scaricano le righe con `updated_at > watermark` (per tabella,
  in `sync_state`), si fa upsert locale con `dirty=0` e si avanza il watermark.
- **Conflitti**: per riga, **last-write-wins** sull'`updated_at` del server;
  le cancellazioni viaggiano come `deleted=true` (tombstone).
- **Ordine**: trips → participants → expenses → splits (rispetta le FK locali).

### Sicurezza lato server (RLS)
Row Level Security su tutte le tabelle: un utente vede/scrive solo i viaggi di cui
è membro (`trip_members`), via funzione `is_member()` *SECURITY DEFINER* (evita la
ricorsione RLS). Un trigger registra il creatore come owner; la RPC `join_trip(code)`
aggiunge un membro tramite il codice condiviso. Le policy di `trips` includono
`owner_id = auth.uid()` (oltre a `is_member`) per coprire la finestra di bootstrap:
al primo upsert la membership owner non è ancora visibile (creata da un trigger
AFTER INSERT) e senza quella clausola SELECT/UPDATE fallirebbero.

## Estensioni previste

- **Nuovi criteri di divisione** (`%`, quote): aggiungere un `mode` e la logica
  in `core._build_splits`; lo schema regge già (`splits.mode` + `share_base`).
- **Sync in tempo reale** (Supabase Realtime) al posto del sync manuale/su apertura.
- **Modifica/cancellazione spese dalla UI** (lo schema con `deleted`/`updated_at`
  è già pronto a propagarle).

## Test

`tests/` usa `unittest` (stdlib):
- `test_money.py` — arrotondamenti e conversioni
- `test_core.py` — divisioni, valuta, validazioni, settlement (in DB `:memory:`)
- `test_cli.py` — flusso end-to-end via `subprocess`
- `test_sync.py` — push/pull/watermark/LWW/tombstone/auth con un finto Supabase
  in memoria (intercetta `SyncClient._http`, due client con DB distinti)

```bash
./run-tests        # oppure: make test, oppure: python -m unittest discover -s tests
```
