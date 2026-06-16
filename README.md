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

### Demo (prova a vuoto)

Per vedere il programma in azione senza toccare il tuo database reale:

```bash
./demo
```

Crea un viaggio d'esempio in un **DB temporaneo**, mostra spese e bilancio, poi
cancella tutto automaticamente.

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

### Provare a vuoto (senza toccare il DB reale)
Usa un database temporaneo, poi cancellalo:

```bash
# opzione per comando
./divc --db /tmp/prova.db trip create --name Test --currency EUR
# ... altri comandi ...
rm /tmp/prova.db

# oppure via variabile d'ambiente (vale solo nel terminale corrente)
export DIVICONTO_DB="$(mktemp --suffix=.db)"
./divc trip create --name Test --currency EUR
# ... altri comandi ...
rm -f "$DIVICONTO_DB" && unset DIVICONTO_DB
```

Su Android/Termux usa un percorso scrivibile, es. `$HOME/prova.db`.
Lo script `./demo` fa esattamente questo in automatico.

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

## Interfaccia grafica (UI)

Oltre alla CLI c'è una UI grafica (**Kivy + KivyMD**) che riusa lo stesso core
e gira su **Linux** e su **Android** (APK). Le dipendenze UI sono separate dalla
CLI (la CLI resta a sola libreria standard).

### Avvio su Linux
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-ui.txt    # oppure: pip install -e ".[ui]"
python main.py
```

La UI offre: elenco/creazione viaggi, gestione partecipanti, inserimento spese
(parti uguali o importi esatti, multi-valuta con tasso) e schermata bilancio con
saldi e pagamenti suggeriti. Il database è in `~/.config/diviconto/diviconto.db`
(cartella dati dell'app, valida anche su Android).

### Build dell'APK Android

L'APK si costruisce con **Buildozer**. Due strade:

**A) Docker (consigliata)** — nessuna dipendenza da installare sul sistema,
serve solo Docker attivo:
```bash
make apk            # = docker run … kivy/buildozer android debug
# l'APK risultante è in bin/  (es. diviconto-0.1.0-...-debug.apk)
make apk-clean      # svuota la cache .buildozer/ per un build pulito
```
Il primo build scarica SDK/NDK (~1.5 GB, lungo); i successivi sono veloci grazie
alla cache in `.buildozer/`. Nota: il comando accetta automaticamente le licenze
SDK (`yes |` + `-i`), altrimenti il build fallisce con "aidl not found".

**B) Build nativo su host Fedora** — prerequisiti di sistema (una volta sola):
```bash
sudo dnf install -y java-17-openjdk-devel autoconf automake libtool \
    cmake ccache gcc gcc-c++ make patch zip unzip which file \
    zlib-devel ncurses-devel libffi-devel openssl-devel
pip install buildozer Cython
buildozer -v android debug
```

L'icona dell'app si rigenera con `python tools/make_icon.py`.
La configurazione del build è in [buildozer.spec](buildozer.spec).

### Installare l'APK sul telefono
Copia il file da `bin/` sul telefono e aprilo (abilita "origini sconosciute"),
oppure via `adb install bin/diviconto-*-debug.apk`.

## Sincronizzazione tra dispositivi (Supabase)

La UI può **sincronizzare le spese tra più telefoni**: ogni partecipante accede
con la propria email e tutti vedono le stesse spese di un viaggio. L'app resta
**offline-first** — il SQLite locale è sempre la fonte primaria, la sync scambia
solo le righe cambiate (last-write-wins per riga sull'`updated_at` del server) e
funziona anche dopo periodi offline. Il modulo di sync usa **solo `urllib`**
(nessuna dipendenza aggiuntiva, né su desktop né nell'APK).

### Come funziona per gli amici
- **Chi crea il viaggio** lo apre, tocca **Condividi** e ottiene un **codice**.
- **Gli amici** si registrano nell'app (email+password), toccano **Unisciti a un
  viaggio** e inseriscono il codice. Non serve creare account Supabase: l'account
  è dentro l'app.
- L'icona **Sincronizza** (in alto nella lista viaggi) invia/scarica i dati; i
  viaggi si sincronizzano anche automaticamente all'apertura.

### Setup Supabase (una tantum, lo fa chi gestisce il progetto)
1. Crea un progetto gratis su [supabase.com](https://supabase.com) (region EU,
   salva la password del DB).
2. **Authentication → Sign In / Providers**: abilita **Email**; per i test
   disabilita la **conferma email** (così gli amici accedono subito).
3. **SQL Editor → New query**: incolla ed esegui [supabase/schema.sql](supabase/schema.sql)
   (crea tabelle, Row Level Security, trigger e la funzione `join_trip`).
4. **Project Settings → API**: copia **Project URL** e chiave **anon public** e
   mettile in [diviconto/sync_config.py](diviconto/sync_config.py) (oppure nelle
   variabili d'ambiente `SUPABASE_URL` / `SUPABASE_ANON_KEY`).

> La chiave **anon** è pubblica (protetta dalla RLS): è normale includerla
> nell'APK. NON usare mai la `service_role` key né la password del DB nell'app.

### Provare la sync da desktop (due "dispositivi")
Due DB locali separati simulano due telefoni:
```bash
DIVICONTO_DB=/tmp/a.db python main.py   # dispositivo A: accedi, crea viaggio, Condividi
DIVICONTO_DB=/tmp/b.db python main.py   # dispositivo B: accedi, Unisciti col codice
```

## Installazione CLI (opzionale)
```bash
pip install --user .
diviconto -h
```

## Test
```bash
./run-tests              # tutti i test
./run-tests -v           # output dettagliato
./run-tests tests.test_core   # solo un modulo/classe/test

make test                # equivalente con make (make test-v per il dettaglio)

python -m unittest discover -s tests   # comando diretto (anche su Termux)
```

## Architettura
- `diviconto/money.py` — importi con `Decimal` e conversione valuta
- `diviconto/models.py` — dataclasses del dominio
- `diviconto/db.py` — storage SQLite (unico punto di persistenza)
- `diviconto/balance.py` — saldi netti + pagamenti di pareggio
- `diviconto/core.py` — logica di business (riusata da CLI e UI)
- `diviconto/cli.py` — interfaccia a riga di comando
- `diviconto/sync.py` — sincronizzazione con Supabase (push/pull, auth)
- `diviconto/sync_config.py` — URL e chiave anon del progetto Supabase
- `supabase/schema.sql` — schema, RLS e funzioni lato server (da eseguire una volta)
- `ui/` — interfaccia grafica Kivy/KivyMD (solo presentazione; richiama `core`)
- `main.py` — entry point della UI; `buildozer.spec` — build Android

Dettagli tecnici in [docs/ARCHITETTURA.md](docs/ARCHITETTURA.md).

I prossimi passi previsti: modifica/cancellazione di spese dalla UI,
sync in tempo reale, divisione per percentuale/quote.
