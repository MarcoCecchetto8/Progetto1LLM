"""Errori del back-end: codice, stato HTTP e testo in italiano (tabella 7.4 della specifica)."""


class BackendError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


AGENT_DOWN = "L'agente non risponde: controlla che sia avviato (python -m agent_service) e riprova."
DB_DOWN = "Il database non risponde: controlla che PostgreSQL sia avviato."
BUSY = "C'è già una risposta in corso in questa chat: attendi che finisca."
PENDING = "Rispondi prima alla conferma in attesa."
NO_PENDING = "Non c'è nessuna conferma in attesa in questa chat."


def chat_not_found(chat_id: int) -> BackendError:
    return BackendError(404, "chat_non_trovata", f"La chat {chat_id} non esiste.")
