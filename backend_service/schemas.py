"""Corpi JSON dell'API del back-end (in italiano)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from backend_service.store import clean_title


class CreateChat(BaseModel):
    titolo: str | None = None

    @field_validator("titolo")
    @classmethod
    def _check_title(cls, value: str | None) -> str | None:
        return None if value is None else clean_title(value)


class ChatSummary(BaseModel):
    id: int
    titolo: str
    creata: datetime
    ultimo_messaggio: datetime | None = None


class MessageOut(BaseModel):
    id: int
    ruolo: str
    contenuto: str
    strumenti: list[dict] = []
    righe: list[str] = []
    creato: datetime


class Confirmation(BaseModel):
    id_nota: int
    domanda: str


class ChatDetail(ChatSummary):
    messaggi: list[MessageOut]
    conferme: list[Confirmation]


class SendMessage(BaseModel):
    testo: str

    @field_validator("testo")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Il testo del messaggio è vuoto.")
        return value


class ConfirmRequest(BaseModel):
    decisioni: dict[int, bool]


class TurnResult(BaseModel):
    esito: Literal["completato", "conferma_richiesta"]
    domanda: MessageOut | None = None
    risposta: MessageOut | None = None
    righe: list[str] = []
    conferme: list[Confirmation] = []


class ErrorBody(BaseModel):
    codice: str
    messaggio: str
