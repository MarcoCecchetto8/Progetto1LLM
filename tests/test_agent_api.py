"""Test dell'API FastAPI dell'agente: modello finto, nessun LM Studio."""

import asyncio
import json
import logging
import threading
import time
from datetime import date

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from agent_service.app import Agent, create_app, stream_events
from agent_service.schemas import TurnRequest
from assistant.config import Settings
from assistant.graph import build_graph
from assistant.mcp_client import MCPConnectionError, MCPPromptError, PromptArgument, PromptInfo
from assistant.notes import build_confirmation_check, build_note_tools
from notes_service.app import create_app as create_notes_app
from tests.fakes import FakeStreamGraph, fake, fake_clock as clock, tool_call

SETTINGS = Settings(base_url="http://localhost:1234/v1", model="m", timeout=120, temperature=0, max_steps=5,
                    default_timezone="Europe/Rome", log_level="INFO")
TODAY = date(2026, 11, 9)
REQUEST = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
UP = {"raggiungibile": True, "messaggio": "ok"}
PROMPTS = [PromptInfo("spiega", "Spiega un concetto", (PromptArgument("argomento", "Che cosa spiegare", True),))]


def ok_status():
    return {"modello": UP, "strumenti": UP, "note": UP}


def get_prompt(name, arguments):
    if arguments.get("argomento") == "rifiuta":
        raise MCPPromptError("argomento non valido")
    if arguments.get("argomento") == "caduto":
        raise MCPConnectionError("sessione chiusa")
    return [("user", f"Spiega {arguments['argomento']}"), ("assistant", "Va bene.")]


def make_agent(graph, status=ok_status):
    return Agent(graph=graph, system="sistema", settings=SETTINGS, list_prompts=lambda: PROMPTS,
                 get_prompt=get_prompt, status=status)


def client_for(graph, **kw):
    agent = make_agent(graph, **kw)
    return agent, TestClient(create_app(agent))


def clock_graph(answer="Sono le 14:32."):
    return build_graph(fake(tool_call({}, "c1"), AIMessage(answer)), [clock], 5)


def ask(text):
    return {"messaggi": [{"ruolo": "utente", "contenuto": text}]}


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        # Le righe di commento (keepalive) non sono eventi
        lines = dict(line.split(": ", 1) for line in block.split("\n") if not line.startswith(":"))
        if not lines:
            continue
        events.append((lines["event"], json.loads(lines["data"])))
    return events


class RaisingGraph:
    """Grafo che solleva l'errore dato alle prime `times` chiamate, poi delega a un grafo vero."""

    def __init__(self, error, delegate=None, times=1):
        self.error, self.delegate, self.times = error, delegate, times

    def stream(self, state, config=None, stream_mode=None):
        if self.times:
            self.times -= 1
            raise self.error
        yield from self.delegate.stream(state, config=config, stream_mode=stream_mode)


def test_chat_with_tool(caplog):
    _, client = client_for(clock_graph())
    with caplog.at_level(logging.INFO, logger="assistant.agent"):
        response = client.post("/chat", json=ask("che ore sono?"))
    assert response.status_code == 200
    body = response.json()
    assert body["esito"] == "completato"
    assert body["risposta"] == "Sono le 14:32."
    assert body["strumenti"][0]["nome"] == "get_current_time"
    assert [m["ruolo"] for m in body["cronologia"]] == ["utente", "assistente", "strumento", "assistente"]
    assert body["sospeso"] is None
    assert "[api] turno /chat: 0 messaggi in cronologia, 1 nuovi" in caplog.text
    assert "[api] strumento get_current_time" in caplog.text
    assert "[api] turno completato in" in caplog.text


def test_chat_stream_events():
    text = "è «x» ⚠\nriga"
    _, client = client_for(clock_graph(text))
    response = client.post("/chat/stream", json=ask("che ore sono?"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["strumento", "esito_strumento", "risposta", "fine"]
    assert events[2][1] == {"testo": text}
    assert "è «x» ⚠\\nriga" in response.text

    _, plain = client_for(clock_graph(text))
    assert events[-1][1] == plain.post("/chat", json=ask("che ore sono?")).json()


@pytest.fixture
def notes(tmp_path):
    return TestClient(create_notes_app(tmp_path / "n.db"))


def test_confirmation_and_resume_on_new_app(notes):
    notes.post("/notes", json={"text": "report"})
    graph = build_graph(
        fake(tool_call({"limit": 10}, "l1", name="list_notes"), tool_call({"note_id": 1}, "d1", name="delete_note"),
             AIMessage("Eliminata.")),
        [clock, *build_note_tools(notes, lambda: TODAY)], 5,
        confirmation_check=build_confirmation_check(notes, lambda: TODAY))
    _, client = client_for(graph)
    first = client.post("/chat", json=ask("elimina report")).json()
    assert first["esito"] == "conferma_richiesta"
    assert first["conferme"][0]["domanda"] == "Elimino la nota 1 «report» · senza scadenza? [s/N] "
    assert first["sospeso"] is not None
    assert notes.get("/notes").json()["total"] == 1

    # Nessuno stato tra le richieste: la ripresa va bene anche su un'app nuova
    other = TestClient(create_app(make_agent(graph)))
    done = other.post("/chat", json={"ripresa": {"sospeso": first["sospeso"], "decisioni": {"1": True}}})
    assert done.status_code == 200
    body = done.json()
    assert body["esito"] == "completato"
    assert body["risposta"] == "Eliminata."
    assert [t["nome"] for t in body["strumenti"]] == ["list_notes", "delete_note"]
    assert notes.get("/notes").json()["total"] == 0


def test_model_unreachable_on_chat_and_stream():
    error = openai.APIConnectionError(request=REQUEST)
    _, client = client_for(RaisingGraph(error, times=2))
    response = client.post("/chat", json=ask("ciao"))
    assert response.status_code == 503
    assert response.json() == {
        "codice": "modello_non_raggiungibile",
        "messaggio": "LM Studio non è raggiungibile all'indirizzo http://localhost:1234/v1. "
                     "Controlla che sia attivo e riprova."}
    stream = client.post("/chat/stream", json=ask("ciao"))
    assert stream.status_code == 200
    assert parse_sse(stream.text) == [("errore", response.json())]


def test_unexpected_error_logged_with_traceback(caplog):
    _, client = client_for(RaisingGraph(RuntimeError("strano"), times=2))
    with caplog.at_level(logging.INFO, logger="assistant.agent"):
        response = client.post("/chat", json=ask("ciao"))
        stream = client.post("/chat/stream", json=ask("ciao"))
    assert response.status_code == 500
    assert response.json() == {"codice": "errore_imprevisto",
                               "messaggio": "Errore imprevisto: strano. Riprova o usa 'clear'."}
    assert parse_sse(stream.text) == [("errore", response.json())]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name == "assistant.agent"]
    assert len(warnings) == 2 and all(r.exc_info for r in warnings)
    assert "[api] turno errore_imprevisto in" in caplog.text


@pytest.mark.parametrize("body", [
    {"messaggi": [{"ruolo": "sistema", "contenuto": "x"}]},
    {"messaggi": [{"ruolo": "utente", "contenuto": "x"}],
     "cronologia": [{"ruolo": "strumento", "contenuto": "x", "nome": "a"}]},
    {"messaggi": [{"ruolo": "strumento", "contenuto": "x", "nome": "a", "id_chiamata": "c"}]},
    {"messaggi": [{"ruolo": "assistente", "contenuto": "",
                   "chiamate": [{"id": "c", "nome": "delete_note", "argomenti": {"note_id": 1}}]}]},
    {"messaggi": [{"ruolo": "utente", "contenuto": "x"}], "ripresa": {"sospeso": {}, "decisioni": {}}},
    {"cronologia": [{"ruolo": "utente", "contenuto": "x"}], "ripresa": {"sospeso": {}, "decisioni": {}}},
    {"messaggi": []},
    {},
])
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
def test_invalid_request_is_422(body, path):
    _, client = client_for(clock_graph())
    assert client.post(path, json=body).status_code == 422


@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
def test_tampered_suspended_is_422(path):
    _, client = client_for(clock_graph())
    response = client.post(path, json={"ripresa": {"sospeso": {"messaggi": "x"}, "decisioni": {"1": True}}})
    assert response.status_code == 422
    assert response.json() == {"codice": "sospeso_non_valido", "messaggio": "stato sospeso non valido"}


def test_lock_released_after_error():
    agent, client = client_for(RaisingGraph(openai.APIConnectionError(request=REQUEST), clock_graph()))
    assert client.post("/chat", json=ask("ciao")).status_code == 503
    assert agent.lock.locked() is False
    assert client.post("/chat", json=ask("che ore sono?")).status_code == 200


def test_conversion_error_is_unexpected_error(caplog):
    # Un ToolMessage senza nome non diventa un Message valido: errore nella conversione della risposta
    final = {"messages": [SystemMessage("sistema"), HumanMessage("ciao"), tool_call({}, "c1"),
                          ToolMessage("ok", tool_call_id="c1"), AIMessage("Fatto.")], "steps": 1}
    _, client = client_for(FakeStreamGraph([], final))
    with caplog.at_level(logging.INFO, logger="assistant.agent"):
        response = client.post("/chat", json=ask("ciao"))
        stream = client.post("/chat/stream", json=ask("ciao"))
    assert response.status_code == 500
    assert response.json()["codice"] == "errore_imprevisto"
    events = parse_sse(stream.text)
    assert [name for name, _ in events] == ["errore"]
    assert events[0][1]["codice"] == "errore_imprevisto"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name == "assistant.agent"]
    assert len(warnings) == 2 and all(r.exc_info for r in warnings)


def test_closing_stream_cancels_turn(caplog):
    released = threading.Event()

    @tool
    def slow() -> str:
        """Strumento che aspetta il via del test."""
        released.wait(5)
        return "fatto"

    graph = build_graph(fake(tool_call({}, "s1", name="slow"), AIMessage("non deve arrivare")), [slow], 5)
    agent = make_agent(graph)
    cancelled = threading.Event()

    async def main():
        events = stream_events(agent, TurnRequest(**ask("vai")), None, cancelled)
        first = await events.__anext__()
        await events.aclose()
        return first

    with caplog.at_level(logging.INFO, logger="assistant.agent"):
        first = asyncio.run(main())
        assert first.startswith("event: strumento\n")
        assert cancelled.is_set()
        # Il turno è ancora nello strumento: alla chiamata successiva del modello si ferma
        released.set()
        deadline = time.monotonic() + 5
        while agent.lock.locked() and time.monotonic() < deadline:
            time.sleep(0.01)
    assert agent.lock.locked() is False
    assert "[api] turno annullato in" in caplog.text
    assert "[api] turno completato" not in caplog.text


def test_stream_sends_keepalive_comment_while_turn_is_silent(monkeypatch):
    # Senza byte il client su Windows non può interrompere la lettura con Ctrl+C
    monkeypatch.setattr("agent_service.app.KEEPALIVE_SECONDS", 0.05)
    released = threading.Event()

    @tool
    def slow() -> str:
        """Strumento che aspetta il via del test."""
        released.wait(5)
        return "fatto"

    graph = build_graph(fake(tool_call({}, "s1", name="slow"), AIMessage("finito")), [slow], 5)
    agent = make_agent(graph)

    async def main():
        events = stream_events(agent, TurnRequest(**ask("vai")), None, threading.Event())
        first = await events.__anext__()
        silent = await events.__anext__()
        released.set()
        rest = [e async for e in events]
        return first, silent, rest

    first, silent, rest = asyncio.run(main())
    assert first.startswith("event: strumento\n")
    assert silent == ": \n\n"
    assert rest[-1].startswith("event: fine\n")
    assert parse_sse("".join([first, silent, *rest]))[-1][0] == "fine"


def test_cancelled_before_lock_skips_turn():
    agent = make_agent(clock_graph())
    cancelled = threading.Event()
    cancelled.set()

    async def collect():
        return [e async for e in stream_events(agent, TurnRequest(**ask("ora?")), None, cancelled)]

    assert asyncio.run(collect()) == []
    # Il modello non è stato chiamato: il turno successivo usa ancora le sue risposte
    assert TestClient(create_app(agent)).post("/chat", json=ask("ora?")).json()["risposta"] == "Sono le 14:32."


def test_status_ok_and_down():
    _, client = client_for(clock_graph())
    response = client.get("/stato")
    assert response.status_code == 200
    assert response.json() == {"agente": "ok", **ok_status()}

    down = {"modello": {"raggiungibile": False, "messaggio": "spento"}, "strumenti": UP, "note": UP}
    _, client = client_for(clock_graph(), status=lambda: down)
    response = client.get("/stato")
    assert response.status_code == 503
    assert response.json() == {"agente": "ok", **down}


def test_prompts():
    _, client = client_for(clock_graph())
    assert client.get("/prompts").json() == [{"nome": "spiega", "descrizione": "Spiega un concetto", "argomenti": [
        {"nome": "argomento", "descrizione": "Che cosa spiegare", "obbligatorio": True}]}]

    response = client.post("/prompts/spiega", json={"argomenti": {"argomento": "le liste"}})
    assert response.status_code == 200
    assert [(m["ruolo"], m["contenuto"]) for m in response.json()["messaggi"]] == [
        ("utente", "Spiega le liste"), ("assistente", "Va bene.")]

    refused = client.post("/prompts/spiega", json={"argomenti": {"argomento": "rifiuta"}})
    assert refused.status_code == 422
    assert refused.json() == {"codice": "prompt_rifiutato",
                              "messaggio": "Il server ha rifiutato il prompt: argomento non valido"}

    lost = client.post("/prompts/spiega", json={"argomenti": {"argomento": "caduto"}})
    assert lost.status_code == 503
    assert lost.json()["codice"] == "strumenti_non_raggiungibili"


def test_openapi():
    _, client = client_for(clock_graph())
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "Agente del laboratorio"
    assert {"/chat", "/chat/stream", "/stato", "/prompts", "/prompts/{nome}"} <= set(spec["paths"])


def test_json_responses_declare_utf8_charset():
    # Senza charset, Windows PowerShell 5.1 (Invoke-RestMethod) legge il corpo come Latin-1: «è» diventa «Ã¨»
    _, client = client_for(clock_graph("È l'ora: sono le 14:32."))
    _, down = client_for(RaisingGraph(openai.APIConnectionError(request=REQUEST)))
    responses = {
        "/chat": client.post("/chat", json=ask("Che ore sono?")),
        "/stato": client.get("/stato"),
        "/prompts": client.get("/prompts"),
        "/prompts/spiega": client.post("/prompts/spiega", json={"argomenti": {"argomento": "ricorsione"}}),
        "errore del modello": down.post("/chat", json=ask("ciao")),
        "richiesta non valida": client.post("/chat", json={}),
    }
    for name, response in responses.items():
        assert response.headers["content-type"] == "application/json; charset=utf-8", name
