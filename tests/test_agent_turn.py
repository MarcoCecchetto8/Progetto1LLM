"""Test dell'esecuzione del turno senza stato: modello finto, nessun LM Studio."""

import json
import threading
from datetime import date

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_service.errors import AgentError, classify, empty_answer
from agent_service.turn import EventRecorder, Suspended, TurnCancelled, resume_turn, run_turn
from assistant.config import Settings
from assistant.graph import build_graph
from assistant.mcp_client import MCPConnectionError
from assistant.notes import NotesConnectionError, build_confirmation_check, build_note_tools
from assistant.router import REFUSAL, Route
from notes_service.app import create_app
from tests.fakes import fake, fake_clock as clock, tool_call

SETTINGS = Settings(base_url="http://localhost:1234/v1", model="m", timeout=120, temperature=0, max_steps=5,
                    default_timezone="Europe/Rome", log_level="INFO")
TODAY = date(2026, 11, 9)
REQUEST = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")


def ask(text):
    return [HumanMessage(text)]


def test_turn_with_tool():
    graph = build_graph(fake(tool_call({}, "c1"), AIMessage("Sono le 14:32.")), [clock], 5)
    out = run_turn(graph, "sistema", [], ask("che ore sono?"), "", SETTINGS)
    assert out.status == "completato"
    assert out.answer == "Sono le 14:32."
    assert out.tools == [{"nome": "get_current_time", "argomenti": {},
                          "esito": "Europe/Rome: 2026-10-26T14:32:05+01:00", "errore": False}]
    assert len(out.history) == 4
    assert not any(isinstance(m, SystemMessage) for m in out.history)
    assert out.confirmations == [] and out.suspended is None


def test_emit_order():
    events = []
    graph = build_graph(fake(tool_call({}, "c1"), AIMessage("Sono le 14:32.")), [clock], 5)
    run_turn(graph, "sistema", [], ask("ora?"), "", SETTINGS, emit=lambda name, data: events.append((name, data)))
    assert [name for name, _ in events] == ["strumento", "esito_strumento", "risposta"]
    assert events[0][1] == {"nome": "get_current_time", "argomenti": {}}
    assert events[1][1] == {"nome": "get_current_time", "contenuto": "Europe/Rome: 2026-10-26T14:32:05+01:00",
                            "errore": False}
    assert events[2][1] == {"testo": "Sono le 14:32."}


def test_agent_keeps_no_state():
    graph = build_graph(fake(AIMessage("uno"), AIMessage("due")), [clock], 5)
    first = run_turn(graph, "sistema", [], ask("a"), "", SETTINGS)
    old = [HumanMessage("vecchia"), AIMessage("risposta vecchia")]
    second = run_turn(graph, "sistema", old, ask("b"), "riassunto", SETTINGS)
    assert [m.content for m in first.history] == ["a", "uno"]
    assert [m.content for m in second.history] == ["vecchia", "risposta vecchia", "b", "due"]
    assert second.summary == "riassunto"


def test_refusal_in_lines_and_answer():
    def router(messages, summary):
        return Route(categoria="fuori_ambito", motivo="cucina")

    graph = build_graph(fake(), [clock], 5, router=router)
    out = run_turn(graph, "sistema", [], ask("carbonara?"), "", SETTINGS)
    expected = REFUSAL.format(motivo="cucina")
    assert out.answer == expected
    assert out.lines == [expected]


def test_event_recorder_fifo_and_lines():
    events = []
    recorder = EventRecorder(lambda n, d: events.append((n, d)))
    recorder.tool_call("a", {"x": 1})
    recorder.tool_call("b", {})
    recorder.tool_result("a", "ok", False)
    recorder.tool_result("b", "Errore: no", True)
    recorder.extra("riga ⚠ «è»")
    recorder.reasoning("penso")
    recorder.finish()
    assert recorder.tools == [{"nome": "a", "argomenti": {"x": 1}, "esito": "ok", "errore": False},
                              {"nome": "b", "argomenti": {}, "esito": "Errore: no", "errore": True}]
    assert recorder.lines == ["riga ⚠ «è»"]
    assert events[-2:] == [("riga", {"testo": "riga ⚠ «è»"}), ("ragionamento", {"testo": "penso"})]


@pytest.fixture
def notes(tmp_path):
    return TestClient(create_app(tmp_path / "n.db"))


def notes_graph(client, *answers):
    tools = build_note_tools(client, lambda: TODAY)
    return build_graph(fake(*answers), tools, 5, confirmation_check=build_confirmation_check(client, lambda: TODAY))


def test_suspend_and_resume(notes):
    notes.post("/notes", json={"text": "report"})
    graph = notes_graph(notes, tool_call({"limit": 10}, "l1", name="list_notes"),
                        tool_call({"note_id": 1}, "d1", name="delete_note"), AIMessage("Eliminata."))
    out = run_turn(graph, "sistema", [], ask("elimina report"), "", SETTINGS)
    assert out.status == "conferma_richiesta"
    assert out.confirmations == [{"id_nota": 1, "domanda": "Elimino la nota 1 «report» · senza scadenza? [s/N] "}]
    suspended = out.suspended
    assert not any(isinstance(m, SystemMessage) for m in suspended.messages)
    assert suspended.messages[-1].tool_calls[0]["id"] == "d1"
    assert notes.get("/notes").json()["total"] == 1

    copy = Suspended.from_dict(json.loads(json.dumps(suspended.to_dict(), ensure_ascii=False)))
    assert copy.to_dict() == suspended.to_dict()
    assert copy.decisions == suspended.decisions

    events = []
    done = resume_turn(graph, "sistema", copy, {1: True}, SETTINGS, emit=lambda n, d: events.append(n))
    assert done.status == "completato"
    assert done.answer == "Eliminata."
    assert [t["nome"] for t in done.tools] == ["list_notes", "delete_note"]
    assert done.tools[1]["esito"] == "Nota 1 eliminata: «report»."
    assert events == ["esito_strumento", "risposta"]
    assert notes.get("/notes").json()["total"] == 0
    assert [type(m).__name__ for m in done.history] == [
        "HumanMessage", "AIMessage", "ToolMessage", "AIMessage", "ToolMessage", "AIMessage"]


def test_second_suspension_keeps_decisions(notes):
    notes.post("/notes", json={"text": "uno"})
    notes.post("/notes", json={"text": "due"})
    graph = notes_graph(notes, tool_call({"note_id": 1}, "d1", name="delete_note"),
                        tool_call({"note_id": 2}, "d2", name="delete_note"), AIMessage("Fatto."))
    out = run_turn(graph, "sistema", [], ask("elimina"), "", SETTINGS)
    out = resume_turn(graph, "sistema", out.suspended, {1: False}, SETTINGS)
    assert out.status == "conferma_richiesta"
    assert out.suspended.decisions == {1: False}
    done = resume_turn(graph, "sistema", Suspended.from_dict(out.suspended.to_dict()), {2: True}, SETTINGS)
    assert [t["esito"] for t in done.tools] == ["Eliminazione della nota 1 annullata dall'utente.",
                                               "Nota 2 eliminata: «due»."]


def valid_dict():
    return Suspended(messages=[HumanMessage("x")], steps=1, reviews=0, summary="", decisions={1: True},
                     tools=[], lines=[]).to_dict()


@pytest.mark.parametrize("change", [
    lambda d: {"messaggi": "x"},
    lambda d: {**d, "passaggi": "1"},
    lambda d: {**d, "passaggi": True},
    lambda d: {**d, "revisioni": None},
    lambda d: {**d, "riassunto": 3},
    lambda d: {**d, "decisioni": {"a": True}},
    lambda d: {**d, "decisioni": {"1": "sì"}},
    lambda d: {**d, "strumenti": "x"},
    lambda d: {**d, "strumenti": [{"nome": "a", "argomenti": {}, "errore": False}]},
    lambda d: {**d, "strumenti": [{"nome": "a", "argomenti": [], "esito": None, "errore": False}]},
    lambda d: {**d, "righe": [1]},
    lambda d: {**d, "messaggi": [{"tipo": "boh"}]},
    lambda d: [],
])
def test_suspended_from_dict_invalid(change):
    with pytest.raises(ValueError, match="stato sospeso non valido"):
        Suspended.from_dict(change(valid_dict()))


def test_suspended_decision_keys_become_int():
    data = {**valid_dict(), "decisioni": {"3": False}}
    assert Suspended.from_dict(data).decisions == {3: False}


class RaisingGraph:
    def __init__(self, error):
        self.error = error

    def stream(self, state, config=None, stream_mode=None):
        raise self.error
        yield


def test_connection_error_becomes_agent_error():
    graph = RaisingGraph(openai.APIConnectionError(request=REQUEST))
    with pytest.raises(AgentError) as exc:
        run_turn(graph, "sistema", [], ask("ciao"), "", SETTINGS)
    assert (exc.value.status, exc.value.code) == (503, "modello_non_raggiungibile")
    assert exc.value.message == ("LM Studio non è raggiungibile all'indirizzo http://localhost:1234/v1. "
                                 "Controlla che sia attivo e riprova.")


def test_resume_error_becomes_agent_error():
    suspended = Suspended.from_dict(valid_dict())
    with pytest.raises(AgentError) as exc:
        resume_turn(RaisingGraph(NotesConnectionError("giù")), "sistema", suspended, {}, SETTINGS)
    assert exc.value.code == "note_non_raggiungibili"


@pytest.mark.parametrize("error, status, code, message", [
    (openai.APITimeoutError(request=REQUEST), 504, "modello_timeout",
     "Il modello non ha risposto entro 120 secondi. Riprova."),
    (openai.APIConnectionError(request=REQUEST), 503, "modello_non_raggiungibile",
     "LM Studio non è raggiungibile all'indirizzo http://localhost:1234/v1. Controlla che sia attivo e riprova."),
    (openai.APIError("context length exceeded", REQUEST, body=None), 422, "contesto_pieno",
     "Il contesto del modello è pieno: usa 'clear' per svuotare la cronologia."),
    (openai.APIError("boom", REQUEST, body=None), 502, "errore_modello", "Errore dell'API del modello: boom"),
    (MCPConnectionError("x"), 503, "strumenti_non_raggiungibili",
     "Il server degli strumenti non risponde: riavvia l'agente (in locale basta riavviare l'assistente)."),
    (NotesConnectionError("x"), 503, "note_non_raggiungibili",
     "Il servizio delle note non risponde: riavvia l'agente (in locale basta riavviare l'assistente)."),
    (RuntimeError("strano"), 500, "errore_imprevisto", "Errore imprevisto: strano. Riprova o usa 'clear'."),
])
def test_classify(error, status, code, message):
    result = classify(error, SETTINGS)
    assert (result.status, result.code, result.message) == (status, code, message)
    assert str(result) == message


def test_empty_answer():
    graph = build_graph(fake(AIMessage("")), [clock], 5)
    with pytest.raises(AgentError) as exc:
        run_turn(graph, "sistema", [], ask("ciao"), "", SETTINGS)
    assert (exc.value.status, exc.value.code, exc.value.message) == (
        502, "risposta_vuota", "Il modello non ha dato una risposta: riprova.")
    assert empty_answer().code == "risposta_vuota"


def test_cancelled_then_next_turn_works():
    graph = build_graph(fake(AIMessage("non deve arrivare"), AIMessage("Ciao!")), [clock], 5)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(TurnCancelled):
        run_turn(graph, "sistema", [], ask("ciao"), "", SETTINGS, cancelled=cancelled)
    out = run_turn(graph, "sistema", [], ask("ciao"), "", SETTINGS, cancelled=threading.Event())
    assert out.answer == "Ciao!"
