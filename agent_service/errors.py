"""Errori del turno classificati in codice HTTP, codice e messaggio in italiano."""

import logging

import openai

from assistant.config import Settings
from assistant.mcp_client import MCPConnectionError
from assistant.notes import NotesConnectionError

logger = logging.getLogger("agent_service.errors")


class AgentError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def classify(error: BaseException, settings: Settings) -> AgentError:
    # APITimeoutError è figlia di APIConnectionError: va controllata prima
    if isinstance(error, openai.APITimeoutError):
        return AgentError(504, "modello_timeout",
                          f"Il modello non ha risposto entro {settings.timeout:g} secondi. Riprova.")
    if isinstance(error, openai.APIConnectionError):
        return AgentError(503, "modello_non_raggiungibile",
                          f"LM Studio non è raggiungibile all'indirizzo {settings.base_url}. "
                          "Controlla che sia attivo e riprova.")
    if isinstance(error, openai.APIError):
        if "context" in str(error).lower():
            return AgentError(422, "contesto_pieno",
                              "Il contesto del modello è pieno: usa 'clear' per svuotare la cronologia.")
        return AgentError(502, "errore_modello", f"Errore dell'API del modello: {error}")
    if isinstance(error, MCPConnectionError):
        logger.warning("[mcp] collegamento con il server perso: %s", error)
        return AgentError(503, "strumenti_non_raggiungibili",
                          "Il server degli strumenti non risponde: riavvia l'agente "
                          "(in locale basta riavviare l'assistente).")
    if isinstance(error, NotesConnectionError):
        logger.warning("[note] collegamento con il servizio perso: %s", error)
        return AgentError(503, "note_non_raggiungibili",
                          "Il servizio delle note non risponde: riavvia l'agente "
                          "(in locale basta riavviare l'assistente).")
    logger.debug("Errore imprevisto durante il turno", exc_info=error)
    return AgentError(500, "errore_imprevisto", f"Errore imprevisto: {error}. Riprova o usa 'clear'.")


def empty_answer() -> AgentError:
    return AgentError(502, "risposta_vuota", "Il modello non ha dato una risposta: riprova.")
