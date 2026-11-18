"""Schemi JSON delle richieste e delle risposte dell'API dell'agente."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agent_service.messages import Message


class Resume(BaseModel):
    sospeso: dict = Field(description="Stato sospeso restituito dall'agente, da rimandare così com'è.")
    decisioni: dict[int, bool] = Field(description="Decisione dell'utente per ogni id di nota: true elimina.")


class TurnRequest(BaseModel):
    messaggi: list[Message] = Field(default=[], description="Messaggi nuovi del turno (utente o assistente). "
                                                            "Vuoto con una ripresa.")
    cronologia: list[Message] = Field(default=[], description="Messaggi precedenti. Vuota con una ripresa.")
    riassunto: str = ""
    ripresa: Resume | None = Field(default=None, description="Ripresa di un turno sospeso per una conferma: "
                                                             "messaggi e cronologia vanno omessi.")

    @model_validator(mode="after")
    def _coerenza(self) -> "TurnRequest":
        if self.ripresa is not None:
            if self.messaggi or self.cronologia:
                raise ValueError("con una ripresa messaggi e cronologia vanno omessi")
            return self
        if not self.messaggi:
            raise ValueError("serve almeno un messaggio nuovo")
        if any(m.ruolo not in ("utente", "assistente") for m in self.messaggi):
            raise ValueError("i messaggi nuovi possono essere solo dell'utente o dell'assistente")
        if any(m.chiamate for m in self.messaggi):
            # Le chiamate si eseguono solo se le ha chieste il modello: il client non può inventarne
            raise ValueError("i messaggi nuovi non possono contenere chiamate agli strumenti")
        return self


class TurnResponse(BaseModel):
    esito: Literal["completato", "conferma_richiesta"]
    risposta: str = ""
    strumenti: list[dict] = []
    righe: list[str] = []
    cronologia: list[Message] = []
    riassunto: str = ""
    conferme: list[dict] = []
    sospeso: dict | None = None


class ErrorBody(BaseModel):
    codice: str
    messaggio: str


class PromptArgumentOut(BaseModel):
    nome: str
    descrizione: str
    obbligatorio: bool


class PromptOut(BaseModel):
    nome: str
    descrizione: str
    argomenti: list[PromptArgumentOut]


class PromptRequest(BaseModel):
    argomenti: dict[str, str] = {}


class PromptMessages(BaseModel):
    messaggi: list[Message]
