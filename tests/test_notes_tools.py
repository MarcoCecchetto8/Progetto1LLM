"""Test dei tool delle note: servizio FastAPI in memoria tramite TestClient, nessun modello."""

import logging
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import ToolException

from assistant.graph import build_graph
from assistant.notes import NotesConnectionError, ask_in_terminal, build_note_tools, due_phrase
from notes_service.app import create_app
from tests.fakes import fake, tool_call

TODAY = date(2026, 11, 9)


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "n.db"))


def make_tools(client, confirm=lambda q: True):
    tools = build_note_tools(client, lambda: TODAY, confirm)
    return {t.name: t for t in tools}


@pytest.mark.parametrize("due, expected", [
    (None, "senza scadenza"),
    ("2026-11-13", "scadenza 2026-11-13 (fra 4 giorni)"),
    ("2026-11-10", "scadenza 2026-11-10 (fra 1 giorno)"),
    ("2026-11-09", "scadenza 2026-11-09 (scade oggi)"),
    ("2026-11-07", "scadenza 2026-11-07 (scaduta da 2 giorni)"),
    ("2026-11-08", "scadenza 2026-11-08 (scaduta da 1 giorno)"),
])
def test_due_phrase(due, expected):
    assert due_phrase(due, TODAY) == expected


def test_add_note(client):
    out = make_tools(client)["add_note"].invoke({"text": "consegnare il report", "due_date": "2026-11-13"})
    assert out == "Nota 1 salvata: «consegnare il report» · scadenza 2026-11-13 (fra 4 giorni)."


def test_add_note_invalid_date(client):
    with pytest.raises(ToolException, match="AAAA-MM-GG"):
        make_tools(client)["add_note"].invoke({"text": "x", "due_date": "venerdì"})


def test_add_note_empty_date_means_none(client):
    out = make_tools(client)["add_note"].invoke({"text": "x", "due_date": ""})
    assert out.endswith("· senza scadenza.")


def test_list_notes_empty(client):
    assert make_tools(client)["list_notes"].invoke({}) == "Nessuna nota salvata."


def test_list_notes_truncated(client):
    tools = make_tools(client)
    for t in ("a", "b", "c"):
        tools["add_note"].invoke({"text": t})
    lines = tools["list_notes"].invoke({"limit": 2}).splitlines()
    assert lines[0] == "3 note, mostrate 2:" and len(lines) == 3
    assert lines[1].startswith("- ") and ": " in lines[1] and "senza scadenza" in lines[1]


def test_list_notes_single(client):
    tools = make_tools(client)
    tools["add_note"].invoke({"text": "a"})
    assert tools["list_notes"].invoke({}).splitlines()[0] == "1 nota:"


def test_delete_note_confirmed(client):
    questions = []
    tools = make_tools(client, lambda q: questions.append(q) or True)
    tools["add_note"].invoke({"text": "consegnare il report", "due_date": "2026-11-13"})
    out = tools["delete_note"].invoke({"note_id": 1})
    assert out == "Nota 1 eliminata: «consegnare il report»."
    assert questions == ["Elimino la nota 1 «consegnare il report» · scadenza 2026-11-13 (fra 4 giorni)? [s/N] "]
    assert client.get("/notes/1").status_code == 404


def test_delete_note_declined(client, caplog):
    tools = make_tools(client, lambda q: False)
    tools["add_note"].invoke({"text": "tenere"})
    with caplog.at_level(logging.INFO, logger="assistant.notes"):
        out = tools["delete_note"].invoke({"note_id": 1})
    assert out == "Eliminazione della nota 1 annullata dall'utente."
    assert client.get("/notes/1").status_code == 200
    assert "annullata dall'utente" in caplog.text


def test_delete_note_missing_does_not_ask(client):
    calls = []
    tools = make_tools(client, lambda q: calls.append(q) or True)
    with pytest.raises(ToolException) as exc:
        tools["delete_note"].invoke({"note_id": 99})
    assert str(exc.value) == "Nessuna nota con ID 99: nulla è stato eliminato."
    assert calls == []


@pytest.mark.parametrize("answer", ["s", "Sì", " SI "])
def test_ask_in_terminal_yes(answer):
    assert ask_in_terminal("?", lambda q: answer) is True


@pytest.mark.parametrize("answer", ["", "n", "forse"])
def test_ask_in_terminal_no(answer):
    assert ask_in_terminal("?", lambda q: answer) is False


def test_ask_in_terminal_eof():
    def eof(q):
        raise EOFError
    assert ask_in_terminal("?", eof) is False


def test_connection_error():
    dead = httpx.Client(base_url="http://127.0.0.1:9", timeout=0.5)
    with pytest.raises(NotesConnectionError, match="non risponde"):
        make_tools(dead)["list_notes"].invoke({})


def test_server_error_is_tool_exception():
    dead = httpx.Client(base_url="http://x", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(ToolException, match="HTTP 500"):
        make_tools(dead)["list_notes"].invoke({})


def test_list_validation_detail_not_string():
    body = {"detail": [{"msg": "x"}]}
    c = httpx.Client(base_url="http://x", transport=httpx.MockTransport(lambda r: httpx.Response(422, json=body)))
    with pytest.raises(ToolException, match="Richiesta non valida al servizio delle note."):
        make_tools(c)["list_notes"].invoke({})


def _start(text):
    return {"messages": [SystemMessage("s"), HumanMessage(text)], "steps": 0}


def test_graph_add_note(client):
    tools = list(make_tools(client).values())
    model = fake(tool_call({"text": "report"}, "n1", name="add_note"), AIMessage("Fatto"))
    out = build_graph(model, tools, 5).invoke(_start("annota report"))
    msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [(m.tool_call_id, m.status) for m in msgs] == [("n1", "success")]
    assert "Nota 1 salvata" in msgs[0].content


def test_graph_delete_declined(client):
    t = make_tools(client, lambda q: False)
    t["add_note"].invoke({"text": "report"})
    model = fake(tool_call({"note_id": 1}, "d1", name="delete_note"), AIMessage("Ok"))
    out = build_graph(model, list(t.values()), 5).invoke(_start("elimina"))
    msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert msgs[0].status == "success" and "annullata" in msgs[0].content
    assert client.get("/notes/1").status_code == 200
