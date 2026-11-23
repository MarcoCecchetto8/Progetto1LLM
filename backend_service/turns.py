"""Turni di conversazione: un turno per chat alla volta, corpi per l'agente e salvataggio dell'esito."""

import logging
import threading
from contextlib import contextmanager

from assistant.agent_http import AgentRequestError, AgentUnavailable
from backend_service.errors import (
    AGENT_DOWN,
    BUSY,
    NO_PENDING,
    PENDING,
    BackendError,
    chat_not_found,
)
from backend_service.store import ChatStore

logger = logging.getLogger("backend_service")

INVALID_REPLY = "L'agente ha risposto in un formato non comprensibile."


class ChatTurns:
    def __init__(self, store: ChatStore):
        self._store = store
        self._lock = threading.Lock()
        self._busy: set[int] = set()

    def acquire(self, chat_id: int) -> None:
        """Segna la chat come occupata; 409 se lo è già."""
        with self._lock:
            if chat_id in self._busy:
                raise BackendError(409, "turno_in_corso", BUSY)
            self._busy.add(chat_id)

    def release(self, chat_id: int) -> None:
        with self._lock:
            self._busy.discard(chat_id)

    @contextmanager
    def busy(self, chat_id: int):
        """Come `acquire`, e la chat si libera sempre all'uscita."""
        self.acquire(chat_id)
        try:
            yield
        finally:
            self.release(chat_id)

    def _chat(self, chat_id: int) -> dict:
        chat = self._store.get_chat(chat_id)
        if chat is None:
            raise chat_not_found(chat_id)
        return chat

    def message_payload(self, chat_id: int, text: str) -> tuple[dict, str]:
        chat = self._chat(chat_id)
        if chat.get("in_sospeso"):
            raise BackendError(409, "conferma_in_attesa", PENDING)
        body = {"messaggi": [{"ruolo": "utente", "contenuto": text}],
                "cronologia": chat["cronologia"], "riassunto": chat["riassunto"]}
        return body, text

    def confirm_payload(self, chat_id: int, decisions: dict[int, bool]) -> tuple[dict, str]:
        pending = self._chat(chat_id).get("in_sospeso")
        if not pending:
            raise BackendError(409, "nessuna_conferma", NO_PENDING)
        expected = sorted(c["id_nota"] for c in pending["conferme"])
        if sorted(decisions) != expected:
            ids = ", ".join(str(i) for i in expected)
            raise BackendError(422, "decisioni_non_valide", f"Servono le decisioni per le note: {ids}.")
        body = {"ripresa": {"sospeso": pending["sospeso"],
                            "decisioni": {str(i): decisions[i] for i in expected}}}
        return body, pending["domanda"]

    def finish(self, chat_id: int, question: str, body: dict) -> dict:
        """Dal corpo finale dell'agente al corpo di TurnResult; salva o sospende."""
        outcome = body.get("esito") if isinstance(body, dict) else None
        try:
            if outcome == "completato":
                saved = self._store.save_turn(chat_id, question, body["risposta"], body["strumenti"],
                                              body["righe"], body["cronologia"], body["riassunto"])
                if saved is None:
                    self._vanished(chat_id)
                asked, answer = saved
                return {"esito": "completato", "domanda": asked, "risposta": answer, "righe": body["righe"]}
            if outcome == "conferma_richiesta":
                pending = {"sospeso": body["sospeso"], "domanda": question, "conferme": body["conferme"]}
                if not self._store.set_pending(chat_id, pending):
                    self._vanished(chat_id)
                return {"esito": "conferma_richiesta", "conferme": body["conferme"]}
        except (KeyError, TypeError) as error:
            raise BackendError(502, "risposta_agente_non_valida", INVALID_REPLY) from error
        raise BackendError(502, "risposta_agente_non_valida", INVALID_REPLY)

    @staticmethod
    def _vanished(chat_id: int):
        logger.info("[backend] chat %d eliminata durante il turno: risposta non salvata", chat_id)
        raise chat_not_found(chat_id)


def agent_error(error: AgentUnavailable | AgentRequestError) -> BackendError:
    if isinstance(error, AgentUnavailable):
        return BackendError(503, "agente_non_raggiungibile", AGENT_DOWN)
    return BackendError(error.status or 502, error.code, error.message)
