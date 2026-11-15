"""Test dei tool delle note: servizio FastAPI in memoria tramite TestClient, nessun modello."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import ToolException

from assistant.graph import build_graph
from assistant.notes import (DELETE_WARNING, SAVE_WARNING, NotesConnectionError, ask_in_terminal,
                             build_note_tools, check_note_claims, due_phrase)
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


def test_delete_note_confirmations_are_serialized(client):
    windows = []

    def slow_confirm(question):
        start = time.monotonic()
        time.sleep(0.2)
        windows.append((start, time.monotonic()))
        return True

    tools = make_tools(client, slow_confirm)
    tools["add_note"].invoke({"text": "uno"})
    tools["add_note"].invoke({"text": "due"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: tools["delete_note"].invoke({"note_id": i}), [1, 2]))
    assert len(results) == 2 and len(windows) == 2
    first, second = sorted(windows)
    assert first[1] <= second[0]
    assert client.get("/notes/1").status_code == 404
    assert client.get("/notes/2").status_code == 404


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


def turn(answer, *tools, history=()):
    return [SystemMessage("s"), *history, HumanMessage("q"), *tools, AIMessage(answer)]


def tool_msg(content, name, status="success"):
    return ToolMessage(content, tool_call_id="t", name=name, status=status)


@pytest.mark.parametrize("answer", [
    'Ho salvato la nota: "comprare il latte".',
    'Ho salvato un promemoria per te: "consegnare il report" venerdì.',
    'Ho salvato il promemoria: "comprare il latte".',
])
def test_claim_without_add_note_warns(answer):
    assert check_note_claims(turn(answer)) == [SAVE_WARNING]


@pytest.mark.parametrize("answer", ["La nota è stata salvata.", "La nota e' stata memorizzata"])
def test_claim_passive_and_accents_warn(answer):
    assert check_note_claims(turn(answer)) == [SAVE_WARNING]


@pytest.mark.parametrize("answer", ["L'ho salvata nelle tue note.", "Ok, l'ho aggiunta alle note.",
                                    "Ho aggiunto il promemoria."])
def test_claim_clitic_and_added_note_warn(answer):
    # il participio concorda con il pronome: l'ho salvata, l'ho aggiunta
    assert check_note_claims(turn(answer)) == [SAVE_WARNING]


def test_added_days_is_not_a_claim():
    # «aggiunto» senza la parola nota/promemoria parla d'altro (es. add_days)
    days = tool_msg("2026-11-13", "add_days")
    assert check_note_claims(turn("Ho aggiunto 5 giorni a oggi: sarà venerdì 13 novembre.", days)) == []


def test_add_note_success_confirms():
    msgs = turn("Ho salvato la nota.", tool_msg("Nota 1 salvata: «x»", "add_note"))
    assert check_note_claims(msgs) == []


def test_add_note_error_does_not_confirm():
    msgs = turn("Ho salvato la nota.", tool_msg("Nota 1 salvata: «x»", "add_note", "error"))
    assert check_note_claims(msgs) == [SAVE_WARNING]


def test_previous_turn_does_not_confirm():
    history = [HumanMessage("prima"), tool_msg("Nota 1 salvata: «x»", "add_note"), AIMessage("Fatto")]
    assert check_note_claims(turn("Ho salvato la nota.", history=history)) == [SAVE_WARNING]


def test_other_tool_does_not_confirm():
    msgs = turn('Ho salvato un promemoria per venerdì.', tool_msg("2026-11-13", "add_days"))
    assert check_note_claims(msgs) == [SAVE_WARNING]


@pytest.mark.parametrize("answer", ["Ho eliminato la nota 3.", "La nota 3 è stata cancellata."])
def test_delete_claim_without_tool_warns(answer):
    assert check_note_claims(turn(answer)) == [DELETE_WARNING]


def test_delete_clitic_claim_warns():
    assert check_note_claims(turn("Fatto! L'ho eliminata.")) == [DELETE_WARNING]


def test_delete_cancelled_confirms():
    cancelled = tool_msg("Eliminazione della nota 3 annullata dall'utente.", "delete_note")
    assert check_note_claims(turn("Va bene, non ho eliminato nulla.", cancelled)) == []


def test_both_claims_warn_in_order():
    answer = "Ho salvato la nuova nota e ho eliminato la vecchia."
    assert check_note_claims(turn(answer)) == [SAVE_WARNING, DELETE_WARNING]


@pytest.mark.parametrize("answer", [
    "Non hai note salvate.",
    "Nessuna nota salvata.",
    "Non è stata trovata alcuna nota con l'ID 99 da eliminare.",
    "Dovrai prima confermare l'eliminazione della nota con ID 99.",
    "Sono le 14:32.",
    "Ti ricordo di consegnare il report venerdì.",
])
def test_no_claim_no_warning(answer):
    assert check_note_claims(turn(answer)) == []


def test_non_string_answer_ignored():
    answer = AIMessage(content=[{"type": "text", "text": "Ho salvato la nota."}])
    assert check_note_claims([SystemMessage("s"), HumanMessage("q"), answer]) == []


def test_graph_appends_save_warning(client):
    tools = list(make_tools(client).values())
    out = build_graph(fake(AIMessage("Ho salvato la nota.")), tools, 5,
                      answer_check=check_note_claims).invoke(_start("annota latte"))
    assert out["messages"][-1].content == "Ho salvato la nota.\n\n" + SAVE_WARNING

    model = fake(tool_call({"text": "latte"}, "a", name="add_note"), AIMessage("Ho salvato la nota."))
    out = build_graph(model, tools, 5, answer_check=check_note_claims).invoke(_start("annota latte"))
    assert out["messages"][-1].content == "Ho salvato la nota."
    assert client.get("/notes/1").status_code == 200
