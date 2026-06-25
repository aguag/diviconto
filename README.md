# DiviConto

**DiviConto** divide le spese di un viaggio tra amici. Offre una **CLI**
(Python, **sola libreria standard** — il core non ha dipendenze) e una **UI
grafica** (Kivy/KivyMD) che gira su **Linux (Fedora 41)** e su **Android (APK)**,
con **sincronizzazione tra dispositivi** opzionale (Supabase, *offline-first*).
I dati stanno in un DB **SQLite** locale; la sync scambia solo le righe cambiate
e funziona anche dopo periodi offline. La CLI gira anche su **Android via Termux**.

## Requisiti
- Python 3.9+ (su Fedora già presente; su Android: `pkg install python` in Termux)

## Uso rapido

Senza installazione, dalla cartella del progetto:

```bash
./divc -h                # help generale
python -m diviconto -h   # equivalente
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

### Lingua (Italiano / English)
L'app parte nella **lingua del dispositivo** (italiano o inglese; **inglese** per
ogni altra lingua) e ricorda la scelta. Puoi cambiarla dall'icona ⚙️ in alto nella
lista viaggi → **Impostazioni → Lingua**: l'app si ricostruisce subito nella nuova
lingua e la mantiene ai riavvii successivi. La CLI usa la stessa logica: lingua
del sistema, sovrascrivibile con `--lang it|en` o l'env `DIVICONTO_LANG`. La
localizzazione è un dizionario senza dipendenze (vedi `diviconto/i18n.py`); i dati
inseriti (nomi, descrizioni) non vengono tradotti.

### Avvio su Linux
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-ui.txt    # oppure: pip install -e ".[ui]"
python main.py
```

La UI offre: elenco/creazione viaggi, gestione partecipanti, inserimento spese
(parti uguali o importi esatti, multi-valuta con tasso; **descrizione
obbligatoria**) e schermata bilancio con saldi e pagamenti suggeriti. Ogni spesa
mostra **data e ora**; toccandola si apre un riepilogo (pagante, tipo di
divisione e **quota di ciascun partecipante**) da cui si può **modificare la
descrizione** o **cancellarla**. Per gli **importi esatti** la somma delle quote
deve coincidere con l'importo (validato al salvataggio). Dalla pagina del viaggio si può **Sincronizzare** e
**Condividere** il codice. Nella lista, i viaggi condivisi mostrano una riga
**"Condiviso con: …"** con le email degli altri membri. Dal menu **⋮** (in alto
nel dettaglio): il creatore può **eliminare il viaggio** o **gestire la
condivisione** (rimuovere un membro, oppure revocare a tutti rigenerando il
codice); un partecipante può **abbandonare** il viaggio. Il database è in `~/.config/diviconto/diviconto.db`
(cartella dati dell'app, valida anche su Android); la variabile `DIVICONTO_DB`
lo sovrascrive (utile per provare più "dispositivi" sullo stesso PC).

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

> **Attenzione a `buildozer.spec`:** tutte le chiavi `android.*` (permessi, api,
> archs…) devono stare sotto la sezione **`[app]`**. Buildozer **non** ha una
> sezione `[android]`: se ce le metti vengono ignorate e si usano i default —
> sintomo tipico è l'APK senza permesso INTERNET, con errore di login a Supabase
> `[Errno 7] No address associated with hostname` (la risoluzione DNS fallisce).

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
funziona anche dopo periodi offline. Il modulo di sync usa **`urllib`** (stdlib)
per l'HTTP; l'unica dipendenza di terze parti è **`certifi`**, inclusa nell'APK
solo per fornire il bundle di certificati CA alla verifica TLS (su desktop si
usano i CA di sistema).

### Come funziona per gli amici
- **Chi crea il viaggio** lo apre, tocca **Condividi** e ottiene un **codice**.
- **Gli amici** si registrano nell'app (email+password), toccano **Unisciti a un
  viaggio** e inseriscono il codice. Non serve creare account Supabase: l'account
  è dentro l'app.
- L'icona **Sincronizza** (in alto nella lista viaggi) invia/scarica i dati; i
  viaggi si sincronizzano anche automaticamente all'apertura.
- Nella lista, un viaggio condiviso mostra **"Condiviso con: …"** con le email
  degli altri membri.
- **Cancellare / uscire / rimuovere** (menu **⋮** nel dettaglio del viaggio):
  il **creatore** può **eliminare** il viaggio (sparisce per tutti) o **gestire
  la condivisione** — rimuovere un singolo membro o **revocare a tutti** (rigenera
  il codice). Un **partecipante** può **abbandonare** il viaggio (sparisce solo
  dal suo dispositivo). Da CLI: `divc trip delete|leave|kick|revoke`.

  > Limite del modello offline-first: rimuovere/escludere un membro gli **revoca
  > gli accessi futuri**, ma la copia **già scaricata** gli resta sul telefono —
  > da remoto non possiamo cancellargliela.

### Usare l'app senza account (offline)
All'avvio si può toccare **"Continua senza account (solo su questo telefono)"**:
l'app funziona del tutto in locale, senza registrazione né cloud — utile quando
**un'unica persona tiene i conti** del gruppo sul proprio telefono.

Non è un vicolo cieco: è "**lavora ora, condividi poi**". Se più tardi crei un
account e accedi, i viaggi creati offline **non vanno persi** — vengono caricati
sul server (con un messaggio di conferma) e puoi condividerli col codice come
qualsiasi altro viaggio. Il database locale è legato a **un account per volta**:
se accede un utente diverso sullo stesso telefono, la cache locale viene azzerata
e si riscaricano i suoi dati dal server (il lavoro offline non ancora caricato è
l'unica cosa che andrebbe persa nel passaggio).

### Setup Supabase (una tantum, lo fa chi gestisce il progetto)
1. Crea un progetto gratis su [supabase.com](https://supabase.com) (region EU,
   salva la password del DB).
2. **Authentication → Sign In / Providers**: abilita **Email**; per i test
   disabilita la **conferma email** (così gli amici accedono subito).
3. **SQL Editor → New query**: incolla ed esegui [supabase/schema.sql](supabase/schema.sql)
   (crea tabelle, Row Level Security, trigger e la funzione `join_trip`). È
   **idempotente**: rieseguendolo dopo un aggiornamento applica le modifiche (es.
   la colonna `email` in `trip_members` per mostrare con chi è condiviso un
   viaggio, oppure la tabella `admins` + RPC per i comandi `divc admin`).
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

### Manutenzione del DB server (amministrazione)
I comandi `admin` della CLI (in [diviconto/admin.py](diviconto/admin.py), solo
stdlib) ispezionano e ripuliscono il backend. Per usarli ci si autentica come
**utente admin**: un normale account Auth il cui id è nella tabella `admins`.
Non serve la `service_role` — basta un account elevato, più sicuro da usare
anche da telefono (Termux).

**Una tantum — rendere admin un account** (lo fa chi gestisce il progetto):

1. **Crea l'account** dalla dashboard: *Authentication → Add user* (email +
   password, spunta *Auto Confirm User*). In alternativa, registrati dall'app con
   quell'email. Non si crea con una query SQL (serve l'hashing della password).
2. **Promuovilo** con una query nel **SQL Editor** (trova da sé lo *user id*
   dall'email):
   ```sql
   insert into public.admins (user_id)
   select id from auth.users where email = 'admin@tuodominio.it'
   on conflict do nothing;
   ```
   Verificare chi è admin, oppure revocarne uno:
   ```sql
   select u.email from public.admins a join auth.users u on u.id = a.user_id;

   delete from public.admins
   where user_id = (select id from auth.users where email = 'admin@tuodominio.it');
   ```

> Usa un account **dedicato** all'amministrazione: per via della RLS estesa, un
> admin vede tutti i dati **anche nell'app normale**. Tienilo separato dal tuo
> account personale.

**Uso:**
```bash
./divc admin login                       # email+password (input nascosto); salva la sessione
./divc admin users                       # elenca gli utenti Auth
./divc admin trips                       # elenca i viaggi (owner + conteggi)
./divc admin purge-trip <id> --yes       # cancella un viaggio
./divc admin purge-user <email> --yes    # soft (marca i viaggi); con --hard rimuove anche l'utente
./divc admin logout                      # rimuove la sessione
```
I comandi `purge-*` fanno un **dry-run** finché non aggiungi `--yes`. La sessione
admin è salvata in `~/.config/diviconto/admin_session.json` (permessi 0600); gli
altri comandi (`trip`, `expense`, …) sono locali e non richiedono il login.

> **Soft-delete vs hard-delete.** Di default `purge-*` fa un **soft-delete**
> (`deleted=true`): è l'unico modo che **si propaga ai dispositivi** via sync
> (al prossimo sync l'app nasconde il viaggio ovunque). L'opzione `--hard` rimuove
> fisicamente la riga: NON si propaga (un dispositivo offline-first non "vede" una
> riga sparita e può perfino ricrearla col push successivo se la sua copia è
> `dirty`), quindi va usata **solo** per la spazzatura di account usa-e-getta.

## Installazione CLI (opzionale)

Per avere il comando `diviconto` disponibile ovunque, **conviene `pipx`**: installa
l'app in un venv **isolato** e ne espone solo il comando nel PATH, senza sporcare
il tuo ambiente Python.

```bash
pipx install .            # crea un venv dedicato e mette `diviconto` nel PATH
diviconto -h
pipx uninstall diviconto  # rimozione pulita
```
(pipx si installa una volta: su Fedora `sudo dnf install pipx`, altrimenti
`pip install --user pipx`.)

> Evita `pip install --user .`: oltre a `diviconto` installerebbe nel tuo
> *user site-packages* anche il package top-level **`ui`** (nome generico →
> rischio di collisione con altri progetti). `pipx`, isolando tutto in un venv
> dedicato, elimina il problema.
>
> Per **sviluppare** non serve installare nulla: usa il venv del progetto e
> lancia `./divc`, `python -m diviconto` o la UI con `python main.py`.

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
- `diviconto/admin.py` — comandi `divc admin` (manutenzione cloud; login utente admin)
- `diviconto/i18n.py` — localizzazione Italiano/Inglese (`tr`), senza dipendenze
- `supabase/schema.sql` — schema, RLS e funzioni lato server (da eseguire una volta)
- `ui/` — interfaccia grafica Kivy/KivyMD (solo presentazione; richiama `core`)
- `main.py` — entry point della UI; `buildozer.spec` — build Android

Dettagli tecnici in [docs/ARCHITETTURA.md](docs/ARCHITETTURA.md).

