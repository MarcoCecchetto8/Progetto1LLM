"""Messaggi dell'API in JSON e conversione da e verso LangChain."""

from typing import Literal

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from pydantic import BaseModel, model_validator


class ToolCall(BaseModel):
    id: str
    nome: str
    argomenti: dict


class Message(BaseModel):
    ruolo: Literal["utente", "assistente", "strumento"]
    contenuto: str = ""
    chiamate: list[ToolCall] = []
    id_chiamata: str | None = None
    nome: str | None = None
    errore: bool = False

    @model_validator(mode="after")
    def _coerenza(self) -> "Message":
        if self.ruolo == "strumento" and (not self.id_chiamata or not self.nome):
            raise ValueError("un messaggio dello strumento richiede id_chiamata e nome")
        if self.chiamate and self.ruolo != "assistente":
            raise ValueError("solo l'assistente può avere chiamate")
        return self


def to_langchain(messages: list[Message]) -> list[AnyMessage]:
    out: list[AnyMessage] = []
    for m in messages:
        if m.ruolo == "utente":
            out.append(HumanMessage(m.contenuto))
        elif m.ruolo == "assistente":
            calls = [{"id": c.id, "name": c.nome, "args": c.argomenti, "type": "tool_call"} for c in m.chiamate]
            out.append(AIMessage(m.contenuto, tool_calls=calls))
        else:
            out.append(
                ToolMessage(
                    m.contenuto,
                    tool_call_id=m.id_chiamata,
                    name=m.nome,
                    status="error" if m.errore else "success",
                )
            )
    return out


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def from_langchain(messages: list[AnyMessage]) -> list[Message]:
    out: list[Message] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            out.append(Message(ruolo="utente", contenuto=_text(m.content)))
        elif isinstance(m, AIMessage):
            calls = [ToolCall(id=c["id"], nome=c["name"], argomenti=c["args"]) for c in m.tool_calls]
            out.append(Message(ruolo="assistente", contenuto=_text(m.content), chiamate=calls))
        elif isinstance(m, ToolMessage):
            out.append(
                Message(
                    ruolo="strumento",
                    contenuto=_text(m.content),
                    id_chiamata=m.tool_call_id,
                    nome=m.name,
                    errore=m.status == "error",
                )
            )
    return out


def dump_state_messages(messages: list[AnyMessage]) -> list[dict]:
    return messages_to_dict(messages)


def load_state_messages(data: list[dict]) -> list[AnyMessage]:
    try:
        return messages_from_dict(data)
    except Exception as exc:
        raise ValueError("stato sospeso non valido") from exc
