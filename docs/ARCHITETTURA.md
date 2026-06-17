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
| [sync.py](../diviconto/sync.py) | Sincronizzazione con Supabase (auth + push/pull) | HTTP con `urllib` (stdlib); `certifi` solo per i CA su Android |
| [sync_config.py](../diviconto/sync_config.py) | URL + chiave anon del progetto Supabase | Valori pubblici, override da env |
| [tools/supabase_admin.py](../tools/supabase_admin.py) | Manutenzione DB server (elenco/purge) via `service_role` | Solo stdlib; chiave da env; dry-run di default |

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
- **Membri di un viaggio**: a ogni sync `_pull_members()` rilegge `trip_members`
  (la RLS restituisce solo i membri dei viaggi propri) e rimpiazza una **cache
  locale di sola lettura** (`trip_members(trip_id, email, role)`), usata dalla UI
  per mostrare "Condiviso con: …". L'`email` del membro è catturata sul server
  alla creazione (trigger owner) e all'adesione (`join_trip`), leggendo
  `auth.users` in `SECURITY DEFINER` (i client non vi accedono direttamente).
- **Unirsi a un viaggio** (`join_trip`): dopo la RPC che aggiunge la membership,
  i watermark di pull vengono **azzerati** prima del sync. Un viaggio appena unito
  ha un `updated_at` precedente, spesso più vecchio del watermark corrente: il
  pull incrementale lo salterebbe (e scaricare le spese senza il viaggio padre
  darebbe un errore FK). Azzerando i watermark il pull riscarica, in ordine di
  dipendenza, tutto ciò di cui si è ora membri.

> **Le cancellazioni si propagano solo come soft-delete.** Poiché il pull scarica
> le righe con `updated_at > watermark`, una riga **rimossa fisicamente** dal
> server non genera nulla da scaricare: i dispositivi continuano a mostrare la
> loro copia locale (e una copia `dirty` la ricrea al push successivo). Per far
> sparire un dato ovunque si deve marcare `deleted=true` (il trigger aggiorna
> `updated_at`, il pull lo propaga, `list_*` filtra `deleted=0`). Vale anche per
> la manutenzione lato server: vedi `tools/supabase_admin.py` (soft-delete di
> default, `--hard` solo per spazzatura di account usa-e-getta).

### Un account per volta nel DB locale
Il SQLite locale **non** rispecchia la membership del server (non ha `owner_id`
né `trip_members`): è una cache legata a **un solo account per volta**, marcato
da `sync_state["session_user"]`. A ogni login (`_store_session`):
- se l'utente è **diverso** dal proprietario corrente — oppure, su DB precedenti
  senza marcatore, esistono già dati sincronizzati (`dirty=0`) di un altro
  account — si chiama `db.clear_synced_data()` (svuota trips/participants/
  expenses/splits + watermark `wm:*`) e si riparte dai dati del nuovo account;
- se è lo **stesso** utente, o è il **primo login da offline** (dati solo
  `dirty=1`, mai sincronizzati), la cache si **mantiene**: il lavoro offline
  resta e al sync diventa di questo utente.

Il `logout` cancella solo i token, **non** `session_user`: così un account
diverso che accede in seguito fa scattare l'azzeramento. Dopo il login l'app
fa un sync per popolare subito la lista (altrimenti, dopo un azzeramento,
resterebbe vuota). Senza questo meccanismo, su un dispositivo condiviso i viaggi
di account diversi si sarebbero accumulati nello stesso DB, mostrati a tutti.

**Conseguenza "lavora ora, condividi poi":** chi usa l'app *senza account*
("Continua senza account") lavora in locale (righe `dirty`, `session_user` nullo);
al primo login quei dati non vengono azzerati ma **caricati** sul server dal sync
(owner = quell'account), e quindi condivisibili col codice. La schermata di
accesso lo rileva prima del login (`session_user` nullo + viaggi `dirty`) e dopo
l'upload mostra "I tuoi viaggi offline sono stati caricati sul tuo account".
Coperto dal test `test_offline_accountant_can_upload_and_share`.

### TLS su Android
Su desktop `urllib` usa i certificati CA di sistema. Nell'APK quei file non sono
nei path standard di OpenSSL, quindi la verifica TLS fallirebbe: `_get_ssl_context()`
in `sync.py` costruisce un contesto con il bundle di **`certifi`** (incluso
nell'APK), con fallback al trust store Android e infine al default desktop. Per
questo `certifi` è nei `requirements` di `buildozer.spec` ed è l'unica dipendenza
di terze parti del runtime. Serve anche il permesso `android.permission.INTERNET`
(sotto `[app]`, non `[android]`, altrimenti viene ignorato).

### Sicurezza lato server (RLS)
Row Level Security su tutte le tabelle: un utente vede/scrive solo i viaggi di cui
è membro (`trip_members`), via funzione `is_member()` *SECURITY DEFINER* (evita la
ricorsione RLS). Un trigger registra il creatore come owner; la RPC `join_trip(code)`
aggiunge un membro tramite il codice condiviso. Le policy di `trips` includono
`owner_id = auth.uid()` (oltre a `is_member`) per coprire la finestra di bootstrap:
al primo upsert la membership owner non è ancora visibile (creata da un trigger
AFTER INSERT) e senza quella clausola SELECT/UPDATE fallirebbero.

## UI: tastiera software su Android

Due accorgimenti in `ui/` per la scrittura nei form su Android:
- **`Window.softinput_mode = "below_target"`** (in `app.py`): all'apertura della
  tastiera la vista scorre per tenere il campo a fuoco **sopra** la tastiera,
  altrimenti i campi in basso (es. la descrizione della spesa) restano coperti.
- **`FormTextField`** (`ui/widgets.py`, usato dalla form spese): su Android la
  tastiera chiusa col tasto Indietro **non azzera il `focus`** del campo, quindi
  ritoccando lo stesso campo non si riaprirebbe. Il widget, in `on_touch_down`,
  se il campo è già a fuoco fa un breve `focus = False` così il tocco (gestito da
  super) lo rifocalizza e riapre la tastiera.

## Estensioni previste

- **Nuovi criteri di divisione** (`%`, quote): aggiungere un `mode` e la logica
  in `core._build_splits`; lo schema regge già (`splits.mode` + `share_base`).
- **Sync in tempo reale** (Supabase Realtime) al posto del sync manuale/su apertura.
- **Cancellazione di un viaggio dalla UI** (oggi si modifica/cancella la singola
  spesa; lo schema con `deleted`/`updated_at` è già pronto a propagarlo).

## Test

`tests/` usa `unittest` (stdlib):
- `test_money.py` — arrotondamenti e conversioni
- `test_core.py` — divisioni, valuta, validazioni, settlement (in DB `:memory:`)
- `test_cli.py` — flusso end-to-end via `subprocess`
- `test_sync.py` — push/pull/watermark/LWW/tombstone/auth, cambio account
  (azzeramento cache), unione a un viaggio "vecchio", membri condivisi e flusso
  offline→carica→condividi, con un finto Supabase in memoria (intercetta
  `SyncClient._http`, più client con DB distinti)

```bash
./run-tests        # oppure: make test, oppure: python -m unittest discover -s tests
```
