"""Router dell'ambito: classifica l'ultima domanda con un'uscita strutturata."""

from collections.abc import Callable
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from assistant.summarizer import SUMMARY_HEADER

ROUTER_CONTEXT_MESSAGES = 6

ROUTER_INSTRUCTIONS = (
    "Sei il router dell'assistente del laboratorio. Non rispondi alla domanda: "
    "decidi solo se l'ultima domanda dell'utente rientra nell'ambito.\n"
    "Non devi saper rispondere tu: anche se servono strumenti o dati in tempo reale, "
    "se l'argomento è in ambito la categoria è 'conversazione'.\n"
    "Il motivo è una frase breve in italiano."
)

REFUSAL = (
    "Posso aiutarti solo con gli strumenti del laboratorio, i linguaggi di programmazione, "
    "l'informatica e l'intelligenza artificiale. Motivo: {motivo}"
)


class Route(BaseModel):
    categoria: Literal["conversazione", "fuori_ambito"] = Field(
        description="'conversazione' se la domanda rientra nell'ambito, 'fuori_ambito' altrimenti."
    )
    motivo: str = Field(description="Frase breve in italiano che spiega la scelta.")


def router_prompt(scope: str, summary: str = "") -> str:
    prompt = f"{ROUTER_INSTRUCTIONS}\n\n{scope}"
    # Dopo un riassunto i primi turni non sono più fra gli ultimi messaggi: il riassunto li sostituisce
    return f"{prompt}\n\n{SUMMARY_HEADER}\n{summary}" if summary else prompt


def router_context(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Solo domande e risposte testuali, senza traffico degli strumenti; ultimi messaggi."""
    kept = [
        m for m in messages
        if isinstance(m, (HumanMessage, AIMessage))
        and isinstance(m.content, str) and m.content
        and not (isinstance(m, AIMessage) and m.tool_calls)
    ]
    kept = kept[-ROUTER_CONTEXT_MESSAGES:]
    # Alcuni template di chat rifiutano un messaggio dell'assistente subito dopo quello di sistema
    while kept and isinstance(kept[0], AIMessage):
        kept = kept[1:]
    return kept


def build_router(model: BaseChatModel, scope: str) -> Callable[[list[AnyMessage], str], Route]:
    # Senza ragionamento: la classificazione deve essere rapida
    structured = model.model_copy(update={"reasoning_effort": "none"}).with_structured_output(
        Route, method="json_schema"
    )

    def route(messages: list[AnyMessage], summary: str = "") -> Route:
        return structured.invoke([SystemMessage(router_prompt(scope, summary)), *router_context(messages)])

    return route


def refusal_text(route: Route) -> str:
    return REFUSAL.format(motivo=route.motivo.strip() or "argomento fuori ambito")
