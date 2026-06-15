# Architettura di DiviConto

Documento tecnico per chi sviluppa. Per l'uso quotidiano vedi il
[README](../README.md).

## Principio guida

Codice **a strati** con un'unica responsabilità per modulo, così la logica di
business è indipendente sia dall'interfaccia (oggi CLI, domani UI) sia dallo
storage (oggi SQLite locale, domani con sincronizzazione).

```
            ┌─────────────┐        ┌──────────────────┐
            │   cli.py    │        │  UI futura       │
            │  (argparse) │        │  (Kivy/BeeWare)  │
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
            └──────────┘ └──────────┘ └──────────┘
                                            │
                                       ┌────▼────┐
                                       │ SQLite  │
                                       └─────────┘
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

## Modello dati

Quattro tabelle (`trips`, `participants`, `expenses`, `splits`). Ogni tabella ha:
- **`id`**: UUID testuale (no autoincrement) → evita collisioni tra dispositivi.
- **`created_at` / `updated_at`**: timestamp ISO 8601 UTC.
- **`deleted`**: flag per soft-delete.

Queste tre scelte sono le fondamenta per una **sincronizzazione futura**
(merge per id, last-write-wins su `updated_at`, tombstone via `deleted`) senza
modifiche allo schema.

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

## Estensioni previste

- **Nuovi criteri di divisione** (`%`, quote): aggiungere un `mode` e la logica
  in `core._build_splits`; lo schema regge già (`splits.mode` + `share_base`).
- **Sincronizzazione**: implementare un nuovo backend con la stessa interfaccia
  di `db.Database`, oppure un livello di sync sopra SQLite.
- **UI**: importare `core` e `db` e sostituire solo lo strato di presentazione.

## Test

`tests/` usa `unittest` (stdlib):
- `test_money.py` — arrotondamenti e conversioni
- `test_core.py` — divisioni, valuta, validazioni, settlement (in DB `:memory:`)
- `test_cli.py` — flusso end-to-end via `subprocess`

```bash
python -m unittest discover -s tests
```
