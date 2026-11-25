"""Archivio delle chat in PostgreSQL: una connessione per operazione, query parametrizzate."""

from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DEFAULT_TITLE = "Nuova chat"
MAX_TITLE = 100
AUTO_TITLE = 60
_CONNECT_TIMEOUT = 3  # secondi

_CHAT_COLUMNS = "id, titolo, creata, ultimo_messaggio"
_MESSAGE_COLUMNS = "id, ruolo, contenuto, strumenti, righe, creato"


def clean_title(title: str | None) -> str:
    title = (title or "").strip()
    if not title:
        return DEFAULT_TITLE
    if len(title) > MAX_TITLE:
        raise ValueError(
            f"Il titolo è troppo lungo: massimo {MAX_TITLE} caratteri (ricevuti {len(title)})."
        )
    return title


def title_from(question: str) -> str:
    title = " ".join(question.split())
    if len(title) > AUTO_TITLE:
        return title[: AUTO_TITLE - 1] + "…"
    return title


class StoreUnavailable(Exception):
    """Il database non è raggiungibile."""


class ChatStore:
    def create_chat(self, title: str | None = None) -> dict:
        raise NotImplementedError

    def list_chats(self) -> list[dict]:
        raise NotImplementedError

    def get_chat(self, chat_id: int) -> dict | None:
        raise NotImplementedError

    def get_messages(self, chat_id: int) -> list[dict]:
        raise NotImplementedError

    def delete_chat(self, chat_id: int) -> bool:
        raise NotImplementedError

    def set_pending(self, chat_id: int, pending: dict | None) -> bool:
        raise NotImplementedError

    def save_turn(
        self,
        chat_id: int,
        question: str,
        answer: str,
        tools: list[dict],
        lines: list[str],
        history: list[dict],
        summary: str,
    ) -> tuple[dict, dict] | None:
        raise NotImplementedError

    def ping(self) -> None:
        raise NotImplementedError


class PostgresChatStore(ChatStore):
    def __init__(self, url: str, search_path: str | None = None):
        self._url = url
        self._options = f"-c search_path={search_path}" if search_path else None
        self._run(self._create_schema)

    @staticmethod
    def _create_schema(conn) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chat ("
            "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
            "titolo TEXT NOT NULL, "
            "creata TIMESTAMPTZ NOT NULL, "
            "ultimo_messaggio TIMESTAMPTZ, "
            "cronologia JSONB NOT NULL DEFAULT '[]', "
            "riassunto TEXT NOT NULL DEFAULT '', "
            "in_sospeso JSONB)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS messaggio ("
            "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
            "chat_id BIGINT NOT NULL REFERENCES chat(id) ON DELETE CASCADE, "
            "ruolo TEXT NOT NULL, "
            "contenuto TEXT NOT NULL, "
            "strumenti JSONB NOT NULL DEFAULT '[]', "
            "righe JSONB NOT NULL DEFAULT '[]', "
            "creato TIMESTAMPTZ NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS messaggio_chat_id_id ON messaggio (chat_id, id)")

    def _run(self, work):
        """Esegue work(conn) in una transazione, con una connessione nuova."""
        kwargs = {"options": self._options} if self._options else {}
        try:
            # Il timeout evita attese lunghe quando l'indirizzo non risponde (es. firewall).
            with psycopg.connect(
                self._url, row_factory=dict_row, connect_timeout=_CONNECT_TIMEOUT, **kwargs
            ) as conn:
                return work(conn)
        except psycopg.OperationalError as exc:
            raise StoreUnavailable(str(exc)) from exc

    def create_chat(self, title: str | None = None) -> dict:
        title = clean_title(title)
        now = datetime.now(UTC)
        return self._run(
            lambda conn: conn.execute(
                f"INSERT INTO chat (titolo, creata) VALUES (%s, %s) RETURNING {_CHAT_COLUMNS}",
                (title, now),
            ).fetchone()
        )

    def list_chats(self) -> list[dict]:
        return self._run(
            lambda conn: conn.execute(
                f"SELECT {_CHAT_COLUMNS} FROM chat "
                "ORDER BY COALESCE(ultimo_messaggio, creata) DESC, id DESC"
            ).fetchall()
        )

    def get_chat(self, chat_id: int) -> dict | None:
        return self._run(
            lambda conn: conn.execute(
                f"SELECT {_CHAT_COLUMNS}, cronologia, riassunto, in_sospeso FROM chat WHERE id = %s",
                (chat_id,),
            ).fetchone()
        )

    def get_messages(self, chat_id: int) -> list[dict]:
        return self._run(
            lambda conn: conn.execute(
                f"SELECT {_MESSAGE_COLUMNS} FROM messaggio WHERE chat_id = %s ORDER BY id",
                (chat_id,),
            ).fetchall()
        )

    def delete_chat(self, chat_id: int) -> bool:
        return self._run(
            lambda conn: conn.execute("DELETE FROM chat WHERE id = %s", (chat_id,)).rowcount > 0
        )

    def set_pending(self, chat_id: int, pending: dict | None) -> bool:
        value = None if pending is None else Jsonb(pending)
        return self._run(
            lambda conn: conn.execute(
                "UPDATE chat SET in_sospeso = %s WHERE id = %s", (value, chat_id)
            ).rowcount
            > 0
        )

    def save_turn(self, chat_id, question, answer, tools, lines, history, summary):
        now = datetime.now(UTC)

        def work(conn):
            row = conn.execute(
                "SELECT titolo FROM chat WHERE id = %s FOR UPDATE", (chat_id,)
            ).fetchone()
            if row is None:
                return None
            insert = (
                "INSERT INTO messaggio (chat_id, ruolo, contenuto, strumenti, righe, creato) "
                f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING {_MESSAGE_COLUMNS}"
            )
            user = conn.execute(
                insert, (chat_id, "utente", question, Jsonb([]), Jsonb([]), now)
            ).fetchone()
            assistant = conn.execute(
                insert, (chat_id, "assistente", answer, Jsonb(tools), Jsonb(lines), now)
            ).fetchone()
            title = title_from(question) if row["titolo"] == DEFAULT_TITLE else row["titolo"]
            conn.execute(
                "UPDATE chat SET cronologia = %s, riassunto = %s, in_sospeso = NULL, "
                "ultimo_messaggio = %s, titolo = %s WHERE id = %s",
                (Jsonb(history), summary, now, title, chat_id),
            )
            return user, assistant

        return self._run(work)

    def ping(self) -> None:
        self._run(lambda conn: conn.execute("SELECT 1"))
