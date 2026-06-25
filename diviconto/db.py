"""Storage SQLite — unico modulo che tocca la persistenza.

Isolando qui tutto l'accesso ai dati, in futuro si potrà introdurre una
sincronizzazione (file su cloud o server) sostituendo/affiancando questo
modulo senza modificare la logica di business.

Scelte pro-sync futura:
- chiavi primarie UUID testuali (niente collisioni tra dispositivi);
- colonne created_at/updated_at (ISO 8601) e deleted (soft-delete).

Gli importi sono salvati come TEXT e riletti come Decimal per fedeltà.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .models import Expense, Participant, Split, Trip

DEFAULT_DB_PATH = Path.home() / ".diviconto" / "diviconto.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    base_currency TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    deleted       INTEGER NOT NULL DEFAULT 0,
    dirty         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS participants (
    id         TEXT PRIMARY KEY,
    trip_id    TEXT NOT NULL REFERENCES trips(id),
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted    INTEGER NOT NULL DEFAULT 0,
    dirty      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS expenses (
    id           TEXT PRIMARY KEY,
    trip_id      TEXT NOT NULL REFERENCES trips(id),
    payer_id     TEXT NOT NULL REFERENCES participants(id),
    amount       TEXT NOT NULL,
    currency     TEXT NOT NULL,
    rate_to_base TEXT NOT NULL,
    amount_base  TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    deleted      INTEGER NOT NULL DEFAULT 0,
    dirty        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS splits (
    id              TEXT PRIMARY KEY,
    expense_id      TEXT NOT NULL REFERENCES expenses(id),
    participant_id  TEXT NOT NULL REFERENCES participants(id),
    mode            TEXT NOT NULL,
    share_base      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    deleted         INTEGER NOT NULL DEFAULT 0,
    dirty           INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Cache di sola lettura dei membri di ogni viaggio (chi vi accede), riempita
-- dal server a ogni sync. Serve a mostrare nell'app con chi è condiviso un
-- viaggio; non viene mai inviata al server (no dirty).
CREATE TABLE IF NOT EXISTS trip_members (
    trip_id TEXT NOT NULL,
    email   TEXT NOT NULL,
    role    TEXT NOT NULL DEFAULT 'member',
    PRIMARY KEY (trip_id, email)
);

CREATE INDEX IF NOT EXISTS idx_participants_trip ON participants(trip_id);
CREATE INDEX IF NOT EXISTS idx_expenses_trip ON expenses(trip_id);
CREATE INDEX IF NOT EXISTS idx_splits_expense ON splits(expense_id);
"""

# Colonne locali (e ordine) usate dalla sincronizzazione, escluse id/dirty.
SYNC_COLUMNS = {
    "trips": ["name", "description", "base_currency", "created_at", "updated_at", "deleted"],
    "participants": ["trip_id", "name", "created_at", "updated_at", "deleted"],
    "expenses": [
        "trip_id", "payer_id", "amount", "currency", "rate_to_base",
        "amount_base", "description", "created_at", "updated_at", "deleted",
    ],
    "splits": [
        "expense_id", "participant_id", "mode", "share_base",
        "created_at", "updated_at", "deleted",
    ],
}


def now_iso() -> str:
    """Timestamp corrente in ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def resolve_db_path(path: Optional[str] = None) -> Path:
    """Determina il percorso del DB: argomento > env DIVICONTO_DB > default."""
    if path:
        return Path(path).expanduser()
    env = os.environ.get("DIVICONTO_DB")
    if env:
        return Path(env).expanduser()
    return DEFAULT_DB_PATH


class Database:
    """Wrapper sottile su SQLite con i metodi CRUD del dominio."""

    def __init__(self, path: Optional[str] = None):
        self.path = resolve_db_path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: il sync gira in un thread separato dalla UI
        # (l'accesso è comunque serializzato, niente scritture concorrenti).
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Migrazioni idempotenti per DB creati con versioni precedenti."""
        for table in ("trips", "participants", "expenses", "splits"):
            cols = {
                row["name"]
                for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "dirty" not in cols:
                # Le righe preesistenti sono locali e non ancora sincronizzate.
                self.conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN dirty INTEGER NOT NULL DEFAULT 1"
                )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- Trip -------------------------------------------------------------
    def add_trip(self, name: str, base_currency: str, description: str = "") -> Trip:
        ts = now_iso()
        trip = Trip(
            id=new_id(),
            name=name,
            base_currency=base_currency,
            description=description,
            created_at=ts,
            updated_at=ts,
        )
        self.conn.execute(
            "INSERT INTO trips (id, name, description, base_currency, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (trip.id, trip.name, trip.description, trip.base_currency, ts, ts),
        )
        self.conn.commit()
        return trip

    def list_trips(self) -> list[Trip]:
        rows = self.conn.execute(
            "SELECT * FROM trips WHERE deleted = 0 ORDER BY created_at"
        ).fetchall()
        return [self._row_to_trip(r) for r in rows]

    def get_trip(self, ref: str) -> Optional[Trip]:
        """Cerca un viaggio per id esatto oppure per nome (case-insensitive)."""
        row = self.conn.execute(
            "SELECT * FROM trips WHERE deleted = 0 AND id = ?", (ref,)
        ).fetchone()
        if row:
            return self._row_to_trip(row)
        rows = self.conn.execute(
            "SELECT * FROM trips WHERE deleted = 0 AND name = ? COLLATE NOCASE", (ref,)
        ).fetchall()
        if len(rows) == 1:
            return self._row_to_trip(rows[0])
        if len(rows) > 1:
            raise ValueError(
                f"più viaggi con nome {ref!r}: usa l'id per disambiguare"
            )
        return None

    # ---- Participant ------------------------------------------------------
    def add_participant(self, trip_id: str, name: str) -> Participant:
        ts = now_iso()
        p = Participant(id=new_id(), trip_id=trip_id, name=name, created_at=ts, updated_at=ts)
        self.conn.execute(
            "INSERT INTO participants (id, trip_id, name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (p.id, p.trip_id, p.name, ts, ts),
        )
        self.conn.commit()
        return p

    def list_participants(self, trip_id: str) -> list[Participant]:
        rows = self.conn.execute(
            "SELECT * FROM participants WHERE deleted = 0 AND trip_id = ? ORDER BY created_at",
            (trip_id,),
        ).fetchall()
        return [self._row_to_participant(r) for r in rows]

    def get_participant_by_name(self, trip_id: str, name: str) -> Optional[Participant]:
        row = self.conn.execute(
            "SELECT * FROM participants WHERE deleted = 0 AND trip_id = ? "
            "AND name = ? COLLATE NOCASE",
            (trip_id, name),
        ).fetchone()
        return self._row_to_participant(row) if row else None

    # ---- Expense ----------------------------------------------------------
    def add_expense(self, expense: Expense) -> Expense:
        ts = now_iso()
        expense.created_at = ts
        expense.updated_at = ts
        with self.conn:  # transazione: spesa + quote insieme
            self.conn.execute(
                "INSERT INTO expenses (id, trip_id, payer_id, amount, currency, "
                "rate_to_base, amount_base, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    expense.id, expense.trip_id, expense.payer_id,
                    str(expense.amount), expense.currency, str(expense.rate_to_base),
                    str(expense.amount_base), expense.description, ts, ts,
                ),
            )
            for s in expense.splits:
                self.conn.execute(
                    "INSERT INTO splits (id, expense_id, participant_id, mode, "
                    "share_base, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (s.id, s.expense_id, s.participant_id, s.mode, str(s.share_base), ts, ts),
                )
        return expense

    def list_expenses(self, trip_id: str) -> list[Expense]:
        rows = self.conn.execute(
            "SELECT * FROM expenses WHERE deleted = 0 AND trip_id = ? ORDER BY created_at",
            (trip_id,),
        ).fetchall()
        expenses = []
        for r in rows:
            exp = self._row_to_expense(r)
            exp.splits = self._splits_for(exp.id)
            expenses.append(exp)
        return expenses

    def update_expense_description(self, expense_id: str, description: str) -> None:
        """Aggiorna la descrizione di una spesa (la marca dirty per il sync)."""
        self.conn.execute(
            "UPDATE expenses SET description = ?, updated_at = ?, dirty = 1 WHERE id = ?",
            (description, now_iso(), expense_id),
        )
        self.conn.commit()

    def delete_expense(self, expense_id: str) -> None:
        """Soft-delete di una spesa e delle sue quote (tombstone per il sync)."""
        ts = now_iso()
        with self.conn:  # spesa + quote nella stessa transazione
            self.conn.execute(
                "UPDATE expenses SET deleted = 1, updated_at = ?, dirty = 1 WHERE id = ?",
                (ts, expense_id),
            )
            self.conn.execute(
                "UPDATE splits SET deleted = 1, updated_at = ?, dirty = 1 WHERE expense_id = ?",
                (ts, expense_id),
            )

    def _splits_for(self, expense_id: str) -> list[Split]:
        rows = self.conn.execute(
            "SELECT * FROM splits WHERE deleted = 0 AND expense_id = ?", (expense_id,)
        ).fetchall()
        return [
            Split(
                id=r["id"],
                expense_id=r["expense_id"],
                participant_id=r["participant_id"],
                mode=r["mode"],
                share_base=Decimal(r["share_base"]),
            )
            for r in rows
        ]

    def list_splits(self, expense_id: str) -> list[Split]:
        """Quote (split) non cancellate di una spesa, una per partecipante."""
        return self._splits_for(expense_id)

    # ---- Sincronizzazione -------------------------------------------------
    def dirty_rows(self, table: str) -> list[dict]:
        """Righe locali da inviare al server (dirty=1), come dizionari."""
        rows = self.conn.execute(
            f"SELECT * FROM {table} WHERE dirty = 1"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_clean(self, table: str, ids: list[str]) -> None:
        """Segna come sincronizzate (dirty=0) le righe inviate con successo."""
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        self.conn.execute(
            f"UPDATE {table} SET dirty = 0 WHERE id IN ({placeholders})", ids
        )
        self.conn.commit()

    def upsert_from_remote(self, table: str, row: dict) -> None:
        """Inserisce/aggiorna una riga arrivata dal server (resta dirty=0).

        Considera solo le colonne locali (scarta gli extra del server, es.
        owner_id/share_code) e normalizza i booleani ``deleted`` in 0/1.
        """
        cols = ["id"] + SYNC_COLUMNS[table]
        values = []
        for c in cols:
            v = row.get(c)
            if c == "deleted":
                v = 1 if v in (True, 1, "true", "1") else 0
            values.append(v)
        col_list = ", ".join(cols)
        placeholders = ", ".join("?" * len(cols))
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "id")
        self.conn.execute(
            f"INSERT INTO {table} ({col_list}, dirty) VALUES ({placeholders}, 0) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}, dirty = 0",
            values,
        )
        self.conn.commit()

    def get_state(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM sync_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO sync_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def delete_state(self, key: str) -> None:
        self.conn.execute("DELETE FROM sync_state WHERE key = ?", (key,))
        self.conn.commit()

    def has_synced_data(self) -> bool:
        """True se esistono righe già sincronizzate (dirty=0), cioè scaricate
        da un account. Serve a distinguere i dati di un account precedente
        (da azzerare al cambio utente) dal lavoro offline non ancora inviato."""
        row = self.conn.execute(
            "SELECT 1 FROM trips WHERE dirty = 0 LIMIT 1"
        ).fetchone()
        return row is not None

    def clear_synced_data(self) -> None:
        """Svuota tutti i dati dei viaggi e i watermark di pull.

        Usato al cambio account: il DB locale è legato a un solo utente per
        volta, quindi quando accede un utente diverso si azzera la cache e si
        riscarica dal server. NON tocca i token di sessione né ``session_user``.
        L'ordine (figli→genitori) rispetta i vincoli FK locali.
        """
        for table in ("splits", "expenses", "participants", "trips", "trip_members"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.execute("DELETE FROM sync_state WHERE key LIKE 'wm:%'")
        self.conn.commit()

    def replace_trip_members(self, rows: list[dict]) -> None:
        """Rimpiazza la cache locale dei membri con quanto arrivato dal server."""
        self.conn.execute("DELETE FROM trip_members")
        self.conn.executemany(
            "INSERT OR IGNORE INTO trip_members (trip_id, email, role) VALUES (?, ?, ?)",
            [
                (r.get("trip_id"), r.get("email") or "", r.get("role") or "member")
                for r in rows
                if r.get("trip_id") and r.get("email")
            ],
        )
        self.conn.commit()

    def members_by_trip(self) -> dict[str, list[str]]:
        """Mappa trip_id → email dei membri (per mostrare con chi è condiviso)."""
        out: dict[str, list[str]] = {}
        for r in self.conn.execute(
            "SELECT trip_id, email FROM trip_members WHERE email != '' ORDER BY email"
        ):
            out.setdefault(r["trip_id"], []).append(r["email"])
        return out

    def trip_members_detail(self, trip_id: str) -> list[dict]:
        """Membri di un viaggio con ruolo ({email, role}), per la UI di gestione."""
        rows = self.conn.execute(
            "SELECT email, role FROM trip_members WHERE trip_id = ? AND email != '' "
            "ORDER BY role DESC, email",
            (trip_id,),
        ).fetchall()
        return [{"email": r["email"], "role": r["role"]} for r in rows]

    def delete_trip(self, trip_id: str) -> None:
        """Soft-delete dell'intero viaggio (trip + figli) come tombstone dirty.

        Si propaga via sync (deleted=true) → il viaggio sparisce per tutti i
        membri. Usata dall'owner per cancellare il viaggio.
        """
        ts = now_iso()
        self.conn.execute(
            "UPDATE splits SET deleted = 1, updated_at = ?, dirty = 1 "
            "WHERE expense_id IN (SELECT id FROM expenses WHERE trip_id = ?)",
            (ts, trip_id),
        )
        for table in ("expenses", "participants"):
            self.conn.execute(
                f"UPDATE {table} SET deleted = 1, updated_at = ?, dirty = 1 WHERE trip_id = ?",
                (ts, trip_id),
            )
        self.conn.execute(
            "UPDATE trips SET deleted = 1, updated_at = ?, dirty = 1 WHERE id = ?",
            (ts, trip_id),
        )
        self.conn.commit()

    def drop_trip_local(self, trip_id: str) -> None:
        """Rimuove un viaggio SOLO dal DB locale, senza tombstone (non si propaga).

        Per "abbandona": tolgo la mia copia, ma il viaggio resta per gli altri
        (la mia membership sul server la rimuove la RPC ``leave_trip``).
        """
        self.conn.execute(
            "DELETE FROM splits WHERE expense_id IN (SELECT id FROM expenses WHERE trip_id = ?)",
            (trip_id,),
        )
        for table in ("expenses", "participants", "trip_members"):
            self.conn.execute(f"DELETE FROM {table} WHERE trip_id = ?", (trip_id,))
        self.conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
        self.conn.commit()

    # ---- row mappers ------------------------------------------------------
    @staticmethod
    def _row_to_trip(r: sqlite3.Row) -> Trip:
        return Trip(
            id=r["id"], name=r["name"], base_currency=r["base_currency"],
            description=r["description"], created_at=r["created_at"], updated_at=r["updated_at"],
        )

    @staticmethod
    def _row_to_participant(r: sqlite3.Row) -> Participant:
        return Participant(
            id=r["id"], trip_id=r["trip_id"], name=r["name"],
            created_at=r["created_at"], updated_at=r["updated_at"],
        )

    @staticmethod
    def _row_to_expense(r: sqlite3.Row) -> Expense:
        return Expense(
            id=r["id"], trip_id=r["trip_id"], payer_id=r["payer_id"],
            amount=Decimal(r["amount"]), currency=r["currency"],
            rate_to_base=Decimal(r["rate_to_base"]), amount_base=Decimal(r["amount_base"]),
            description=r["description"], created_at=r["created_at"], updated_at=r["updated_at"],
        )
