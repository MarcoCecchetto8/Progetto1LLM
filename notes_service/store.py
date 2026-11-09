"""Archivio SQLite delle note: una connessione per operazione, query parametrizzate."""

import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

MAX_TEXT = 500
MAX_LIMIT = 50
DEFAULT_LIMIT = 10

_DATE_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2}")
# Prima le note con scadenza (la più vicina in alto), poi quelle senza (la più recente in alto)
_ORDER = "ORDER BY due_date IS NULL, due_date, CASE WHEN due_date IS NULL THEN -id ELSE id END"


def _clean_text(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("Il testo della nota è vuoto.")
    if len(text) > MAX_TEXT:
        raise ValueError(
            f"Il testo della nota è troppo lungo: massimo {MAX_TEXT} caratteri (ricevuti {len(text)})."
        )
    return text


def _clean_due_date(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if not _DATE_FORMAT.fullmatch(value):
        raise ValueError(f'Scadenza "{value}" non valida: formato atteso AAAA-MM-GG (es. 2026-11-13).')
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(f'Scadenza "{value}" inesistente.') from None
    return value


def _to_note(row: sqlite3.Row) -> dict:
    return dict(row)


class NoteStore:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS notes ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, "
                "due_date TEXT, created_at TEXT NOT NULL)"
            )

    def _connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return _Connection(conn)

    def add(self, text: str, due_date: str | None = None) -> dict:
        text = _clean_text(text)
        due_date = _clean_due_date(due_date)
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notes (text, due_date, created_at) VALUES (?, ?, ?)",
                (text, due_date, created_at),
            )
            note_id = cur.lastrowid
        return {"id": note_id, "text": text, "due_date": due_date, "created_at": created_at}

    def list_notes(self, limit: int = DEFAULT_LIMIT) -> tuple[int, list[dict]]:
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit deve essere compreso fra 1 e {MAX_LIMIT}.")
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            rows = conn.execute(f"SELECT * FROM notes {_ORDER} LIMIT ?", (limit,)).fetchall()
        return total, [_to_note(r) for r in rows]

    def get(self, note_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return _to_note(row) if row else None

    def delete(self, note_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            if row:
                conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return _to_note(row) if row else None


class _Connection:
    """Connessione che fa commit/rollback e poi si chiude davvero."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self._conn.__enter__()

    def __exit__(self, *exc):
        try:
            return self._conn.__exit__(*exc)
        finally:
            self._conn.close()
