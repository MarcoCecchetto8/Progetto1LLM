"""Modello e strumento finti per i test del grafo (nessun modello reale, nessun server MCP)."""

import json

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import ToolException, tool


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        # Il modello finto di base in streaming perde le chiamate agli strumenti
        # e non emette nulla per un contenuto vuoto: qui il messaggio esce intero.
        msg = next(self.messages)
        chunk = AIMessageChunk(
            content=msg.content,
            additional_kwargs=msg.additional_kwargs,
            tool_call_chunks=[
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(msg.tool_calls)
            ],
        )
        yield ChatGenerationChunk(message=chunk)


def tool_call(args: dict, id: str, name: str = "get_current_time") -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": id}])


def fake(*msgs: AIMessage) -> FakeToolModel:
    return FakeToolModel(messages=iter(msgs))


FAKE_TIMES = {"Europe/Rome": "Europe/Rome: 2026-10-26T14:32:05+01:00",
              "Asia/Tokyo": "Asia/Tokyo: 2026-10-26T22:32:05+09:00"}


@tool
def fake_clock(timezone: str | None = None) -> str:
    """Orologio finto con istante fisso, come quello del server MCP."""
    name = timezone or "Europe/Rome"
    if name not in FAKE_TIMES:
        raise ToolException(f'Fuso orario sconosciuto: "{name}". Usa un nome IANA, es. Europe/Rome.')
    return FAKE_TIMES[name]


fake_clock.name = "get_current_time"


class FakeStreamGraph:
    """Grafo finto: restituisce gli eventi dati e, alla fine, lo stato finale."""

    def __init__(self, events: list[tuple[str, object]], final: dict):
        self.events = events
        self.final = final

    def stream(self, state, config=None, stream_mode=None):
        yield from self.events
        yield ("values", self.final)


def done(history: list[dict] | None = None, summary: str = "") -> tuple[str, dict]:
    """Evento `fine` di un turno completato."""
    return "fine", {"esito": "completato", "risposta": "", "cronologia": history or [], "riassunto": summary}


def confirmation(*questions: tuple[int, str], suspended: dict | None = None) -> tuple[str, dict]:
    """Evento `fine` di un turno sospeso in attesa di conferma."""
    return "fine", {"esito": "conferma_richiesta", "sospeso": suspended or {"stato": "x"},
                    "conferme": [{"id_nota": note_id, "domanda": question} for note_id, question in questions]}


class FakeAgent:
    """Agente finto per la CLI: ogni chiamata a stream_turn consuma una sequenza di eventi
    (o un'eccezione da sollevare). Senza sequenze, il turno si chiude con «ok» in cronologia."""

    def __init__(self, *turns, prompt=None):
        self.turns = list(turns)
        self.payloads: list[dict] = []
        self.closed = 0
        self._prompt = prompt
        self.prompt_calls: list[tuple[str, dict]] = []

    def stream_turn(self, payload):
        self.payloads.append(payload)
        turn = self.turns.pop(0) if self.turns else None
        try:
            if turn is None:
                reply = {"ruolo": "assistente", "contenuto": "ok"}
                yield "risposta", {"testo": "ok"}
                yield done(payload.get("cronologia", []) + payload.get("messaggi", []) + [reply])
                return
            if isinstance(turn, BaseException):
                raise turn
            for item in turn:
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            # Registra la chiusura del generatore (Ctrl+C durante lo streaming)
            self.closed += 1

    def get_prompt(self, name, arguments):
        self.prompt_calls.append((name, arguments))
        if callable(self._prompt):
            return self._prompt(name, arguments)
        return self._prompt if self._prompt is not None else [("user", "Spiega MCP in breve.")]
