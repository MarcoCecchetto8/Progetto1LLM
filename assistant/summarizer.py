"""Riassunto della cronologia: funzioni pure per stimare, tagliare e riassumere la conversazione."""

import json
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage

from assistant.reviewer import is_review_feedback

SUMMARIZER_INSTRUCTIONS = (
    "Riassumi la conversazione tra l'utente e l'assistente del laboratorio, in italiano, in al massimo 120 parole. "
    "Conserva sempre, se presenti: il nome dell'utente, il fuso orario o la città che usa, gli ID delle note con il "
    "loro testo, gli argomenti principali di cui si è parlato. "
    "Se la conversazione inizia con un riassunto delle parti precedenti, riporta TUTTE le sue informazioni "
    "(nomi, note, argomenti) e aggiungi quelle nuove. "
    "Scrivi solo il riassunto, senza introduzioni."
)

SUMMARY_HEADER = "Riassunto della conversazione precedente:"


def estimate_tokens(messages: list[AnyMessage], summary: str = "") -> int:
    """Stima grossolana: un token ogni 4 caratteri, senza tokenizzatore."""
    chars = len(summary)
    for message in messages:
        if isinstance(message.content, str):
            chars += len(message.content)
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                chars += len(call["name"]) + len(json.dumps(call["args"], ensure_ascii=False))
    return chars // 4


def turn_starts(messages: list[AnyMessage]) -> list[int]:
    """Indici delle domande vere: le indicazioni del revisore non aprono un turno."""
    return [i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and not is_review_feedback(m)]


def summary_cut(messages: list[AnyMessage], keep_turns: int) -> int:
    """Indice del primo messaggio conservato; 0 se non c'è niente da comprimere."""
    starts = turn_starts(messages)
    # L'ultimo inizio è la domanda corrente: i turni precedenti sono tutti gli altri
    if len(starts) - 1 <= keep_turns:
        return 0
    return starts[-1 - keep_turns]


def transcript(messages: list[AnyMessage]) -> str:
    lines = []
    for message in messages:
        if isinstance(message, HumanMessage):
            lines.append(f"Utente: {message.content}")
        elif isinstance(message, AIMessage):
            if message.content:
                lines.append(f"Assistente: {message.content}")
        elif isinstance(message, ToolMessage):
            lines.append(f"Strumento {message.name}: {message.content}")
    return "\n".join(lines)


def summary_request(previous: str, conversation: str) -> str:
    request = "Conversazione da riassumere:\n"
    if previous:
        request += f"Riassunto delle parti precedenti: {previous}\n"
    return request + conversation


def build_summarizer(model: BaseChatModel) -> Callable[[str, str], str]:
    # Senza ragionamento: il riassunto deve essere rapido
    plain = model.model_copy(update={"reasoning_effort": "none"})

    def summarize(previous: str, conversation: str) -> str:
        reply = plain.invoke(
            [SystemMessage(SUMMARIZER_INSTRUCTIONS), HumanMessage(summary_request(previous, conversation))]
        )
        return reply.content

    return summarize


def with_summary(messages: list[AnyMessage], summary: str) -> list[AnyMessage]:
    """Copia della lista con il riassunto nel prompt di sistema, solo per la chiamata al modello."""
    if not summary:
        return messages
    result = list(messages)
    for i, message in enumerate(result):
        if isinstance(message, SystemMessage):
            result[i] = message.model_copy(update={"content": f"{message.content}\n\n{SUMMARY_HEADER}\n{summary}"})
            break
    return result


def summary_line(messages_before: int, messages_after: int, tokens_before: int, tokens_after: int) -> str:
    return (
        f"[riassunto] {messages_before} → {messages_after} messaggi "
        f"(circa {tokens_before} → {tokens_after} token)"
    )
