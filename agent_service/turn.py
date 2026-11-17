"""Esecuzione di un turno senza stato: cronologia in ingresso, esito completato o sospeso in uscita."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AnyMessage, SystemMessage

from agent_service.errors import classify, empty_answer
from agent_service.messages import dump_state_messages, load_state_messages
from assistant.config import Settings
from assistant.stream_view import stream_turn

Emit = Callable[[str, dict], None]
INVALID_SUSPENDED = "stato sospeso non valido"


class TurnCancelled(Exception):
    """Turno annullato (Ctrl+C o cliente andato via): ferma il thread del modello."""


class CancelOnInterrupt(BaseCallbackHandler):
    # Senza raise_error LangChain registrerebbe l'eccezione e lascerebbe proseguire il modello
    raise_error = True

    def __init__(self, cancelled: threading.Event):
        self._cancelled = cancelled

    def on_llm_new_token(self, token, **kwargs) -> None:
        if self._cancelled.is_set():
            raise TurnCancelled


class EventRecorder:
    """Osservatore con l'interfaccia di TurnView: inoltra gli eventi e accumula strumenti e righe del turno."""

    def __init__(self, emit: Emit | None = None, tools: list[dict] | None = None, lines: list[str] | None = None):
        self._emit = emit or (lambda name, data: None)
        self.tools = [dict(t) for t in tools or []]
        self.lines = list(lines or [])

    def reasoning(self, text: str) -> None:
        self._emit("ragionamento", {"testo": text})

    def answer(self, text: str) -> None:
        self._emit("risposta", {"testo": text})

    def tool_call(self, name: str, args: dict) -> None:
        # esito None: chiamata in attesa del risultato (anche oltre una sospensione)
        self.tools.append({"nome": name, "argomenti": args, "esito": None, "errore": False})
        self._emit("strumento", {"nome": name, "argomenti": args})

    def tool_result(self, name: str, content: str, error: bool) -> None:
        # Il ToolNode restituisce i risultati nell'ordine delle chiamate
        pending = next((t for t in self.tools if t["esito"] is None), None)
        if pending is None:
            pending = {"nome": name, "argomenti": {}}
            self.tools.append(pending)
        pending.update(esito=content, errore=error)
        self._emit("esito_strumento", {"nome": name, "contenuto": content, "errore": error})

    def extra(self, text: str) -> None:
        self.lines.append(text)
        self._emit("riga", {"testo": text})

    def finish(self) -> None:
        pass


@dataclass
class Suspended:
    messages: list[AnyMessage]  # senza messaggio di sistema; l'ultimo è l'AIMessage con le chiamate
    steps: int
    reviews: int
    summary: str
    decisions: dict[int, bool]
    tools: list[dict]
    lines: list[str]

    def to_dict(self) -> dict:
        return {"messaggi": dump_state_messages(self.messages), "passaggi": self.steps, "revisioni": self.reviews,
                "riassunto": self.summary, "decisioni": {str(k): v for k, v in self.decisions.items()},
                "strumenti": self.tools, "righe": self.lines}

    @classmethod
    def from_dict(cls, data: dict) -> "Suspended":
        # Lo stato torna dal cliente: va controllato come qualsiasi input
        try:
            messages, steps, reviews = data["messaggi"], data["passaggi"], data["revisioni"]
            summary, decisions = data["riassunto"], data["decisioni"]
            tools, lines = data["strumenti"], data["righe"]
        except (KeyError, TypeError):
            raise ValueError(INVALID_SUSPENDED) from None
        valid = (isinstance(messages, list) and _is_int(steps) and _is_int(reviews) and isinstance(summary, str)
                 and isinstance(decisions, dict) and all(isinstance(v, bool) for v in decisions.values())
                 and isinstance(tools, list) and all(isinstance(t, dict) for t in tools)
                 and isinstance(lines, list) and all(isinstance(r, str) for r in lines))
        if not valid:
            raise ValueError(INVALID_SUSPENDED)
        try:
            decisions = {int(k): v for k, v in decisions.items()}
        except ValueError:
            raise ValueError(INVALID_SUSPENDED) from None
        return cls(load_state_messages(messages), steps, reviews, summary, decisions, tools, lines)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass
class TurnOutcome:
    status: str  # completato o conferma_richiesta
    answer: str = ""
    tools: list[dict] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    history: list[AnyMessage] = field(default_factory=list)
    summary: str = ""
    confirmations: list[dict] = field(default_factory=list)
    suspended: Suspended | None = None


def _execute(graph, state: dict, recorder: EventRecorder, settings: Settings,
             cancelled: threading.Event | None) -> TurnOutcome:
    config = {"callbacks": [CancelOnInterrupt(cancelled or threading.Event())]}
    try:
        final = stream_turn(graph, state, recorder, config)
    except TurnCancelled:
        raise
    except Exception as error:
        raise classify(error, settings) from error
    messages = final["messages"]
    confirmations = final.get("confirmations") or []
    if confirmations:
        suspended = Suspended(messages[1:], final["steps"], final.get("reviews", 0), final.get("summary", ""),
                              dict(final.get("decisions", {})), recorder.tools, recorder.lines)
        return TurnOutcome("conferma_richiesta", confirmations=confirmations, suspended=suspended)
    answer = messages[-1].content
    if not isinstance(answer, str) or not answer.strip():
        # es. chiamata allo strumento con JSON non valido: il turno non entra in cronologia
        raise empty_answer()
    # Le chiamate mai eseguite (limite di passaggi) non hanno esito
    tools = [t for t in recorder.tools if t["esito"] is not None]
    return TurnOutcome("completato", answer, tools, recorder.lines, messages[1:], final.get("summary", ""))


def run_turn(graph, system: str, history: list[AnyMessage], new: list[AnyMessage], summary: str,
             settings: Settings, emit: Emit | None = None, cancelled: threading.Event | None = None) -> TurnOutcome:
    state = {"messages": [SystemMessage(system), *history, *new], "steps": 0, "summary": summary}
    return _execute(graph, state, EventRecorder(emit), settings, cancelled)


def resume_turn(graph, system: str, suspended: Suspended, decisions: dict[int, bool], settings: Settings,
                emit: Emit | None = None, cancelled: threading.Event | None = None) -> TurnOutcome:
    state = {"messages": [SystemMessage(system), *suspended.messages], "steps": suspended.steps,
             "reviews": suspended.reviews, "summary": suspended.summary,
             "decisions": {**suspended.decisions, **decisions}}
    # Il registratore riparte da quanto prodotto prima della sospensione: l'esito copre tutto il turno
    return _execute(graph, state, EventRecorder(emit, suspended.tools, suspended.lines), settings, cancelled)
