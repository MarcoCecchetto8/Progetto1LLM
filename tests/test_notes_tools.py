"""Test dei tool delle note: servizio FastAPI in memoria tramite TestClient, nessun modello."""

import logging
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import ToolException

from assistant.graph import build_graph
from assistant.reviewer import feedback_message
from assistant.notes import (DELETE_WARNING, SAVE_WARNING, NotesConnectionError,
                             build_confirmation_check, build_note_tools, check_note_claims, due_phrase)
from notes_service.app import create_app
from tests.fakes import fake, tool_call

TODAY = date(2026, 11, 9)


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "n.db"))


def make_tools(client):
    tools = build_note_tools(client, lambda: TODAY)
    return {t.name: t for t in tools}


def decided(decisions):
    return {"configurable": {"note_decisions": decisions}}


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


def test_delete_note_has_no_config_argument(client):
    assert "config" not in make_tools(client)["delete_note"].args


def test_delete_note_confirmed(client):
    tools = make_tools(client)
    tools["add_note"].invoke({"text": "consegnare il report", "due_date": "2026-11-13"})
    out = tools["delete_note"].invoke({"note_id": 1}, config=decided({1: True}))
    assert out == "Nota 1 eliminata: «consegnare il report»."
    assert client.get("/notes/1").status_code == 404


def test_delete_note_declined(client, caplog):
    tools = make_tools(client)
    tools["add_note"].invoke({"text": "tenere"})
    with caplog.at_level(logging.INFO, logger="assistant.notes"):
        out = tools["delete_note"].invoke({"note_id": 1}, config=decided({1: False}))
    assert out == "Eliminazione della nota 1 annullata dall'utente."
    assert client.get("/notes/1").status_code == 200
    assert "annullata dall'utente" in caplog.text


def test_delete_note_without_decision_is_cancelled(client, caplog):
    tools = make_tools(client)
    tools["add_note"].invoke({"text": "tenere"})
    with caplog.at_level(logging.WARNING, logger="assistant.notes"):
        out = tools["delete_note"].invoke({"note_id": 1})
    assert out == "Eliminazione della nota 1 annullata dall'utente."
    assert client.get("/notes/1").status_code == 200
    assert "eliminazione della nota 1 senza conferma: annullata" in caplog.text


def test_delete_note_missing(client):
    with pytest.raises(ToolException) as exc:
        make_tools(client)["delete_note"].invoke({"note_id": 99}, config=decided({99: True}))
    assert str(exc.value) == "Nessuna nota con ID 99: nulla è stato eliminato."


def delete_call(note_id, id="d"):
    return {"name": "delete_note", "args": {"note_id": note_id}, "id": id}


def test_confirmation_check_question(client):
    make_tools(client)["add_note"].invoke({"text": "report"})
    check = build_confirmation_check(client, lambda: TODAY)
    assert check([delete_call(1)], {}) == [
        {"id_nota": 1, "domanda": "Elimino la nota 1 «report» · senza scadenza? [s/N] "}]


def test_confirmation_check_skips_missing_decided_and_repeated(client):
    tools = make_tools(client)
    tools["add_note"].invoke({"text": "uno"})
    tools["add_note"].invoke({"text": "due"})
    check = build_confirmation_check(client, lambda: TODAY)
    calls = [delete_call(99, "a"), delete_call(1, "b"), delete_call(2, "c"), delete_call(2, "d"),
             {"name": "add_note", "args": {"text": "x"}, "id": "e"}]
    assert [c["id_nota"] for c in check(calls, {1: False})] == [2]


def test_confirmation_check_digit_string_id(client):
    # I modelli locali passano spesso l'ID come stringa: senza conferma il ToolNode lo convertirebbe e annullerebbe
    make_tools(client)["add_note"].invoke({"text": "report"})
    check = build_confirmation_check(client, lambda: TODAY)
    assert [c["id_nota"] for c in check([delete_call("1", "a"), delete_call(1, "b")], {})] == [1]
    assert check([delete_call("1")], {1: True}) == []
    assert check([delete_call(True), delete_call("x"), delete_call(" 1"), delete_call("-1")], {}) == []


def test_confirmation_check_tool_error_is_left_to_the_tool():
    # Un errore del servizio diverso dal 404 non deve rompere il turno: lo strumento lo riporterà al modello
    broken = httpx.Client(base_url="http://x", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert build_confirmation_check(broken, lambda: TODAY)([delete_call(1)], {}) == []


def test_confirmation_check_connection_error():
    dead = httpx.Client(base_url="http://127.0.0.1:9", timeout=0.5)
    with pytest.raises(NotesConnectionError):
        build_confirmation_check(dead, lambda: TODAY)([delete_call(1)], {})


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


def confirming_graph(client, *answers):
    tools = list(make_tools(client).values())
    return build_graph(fake(*answers), tools, 5,
                       confirmation_check=build_confirmation_check(client, lambda: TODAY))


def resume(out, decisions):
    return {"messages": out["messages"], "steps": out["steps"], "decisions": decisions}


def tool_messages(out):
    return [m for m in out["messages"] if isinstance(m, ToolMessage)]


def test_graph_delete_suspends_and_resumes(client):
    make_tools(client)["add_note"].invoke({"text": "report"})
    both = AIMessage("", tool_calls=[{"name": "add_note", "args": {"text": "nuova"}, "id": "a1"},
                                     {"name": "delete_note", "args": {"note_id": 1}, "id": "d1"}])
    graph = confirming_graph(client, both, AIMessage("Fatto"))
    out = graph.invoke(_start("aggiungi nuova ed elimina report"))
    assert out["confirmations"] == [{"id_nota": 1, "domanda": "Elimino la nota 1 «report» · senza scadenza? [s/N] "}]
    assert tool_messages(out) == []
    assert client.get("/notes").json()["total"] == 1

    out = graph.invoke(resume(out, {1: True}))
    assert out["confirmations"] == []
    assert client.get("/notes/1").status_code == 404
    assert [n["text"] for n in client.get("/notes").json()["notes"]] == ["nuova"]
    assert [m.tool_call_id for m in tool_messages(out)] == ["a1", "d1"]
    assert out["messages"][-1].content == "Fatto"


def test_graph_decided_note_does_not_suspend_again(client):
    make_tools(client)["add_note"].invoke({"text": "report"})
    graph = confirming_graph(client, tool_call({"note_id": 1}, "d1", name="delete_note"),
                             tool_call({"note_id": 1}, "d2", name="delete_note"), AIMessage("Ok"))
    out = graph.invoke(_start("elimina"))
    assert len(out["confirmations"]) == 1
    out = graph.invoke(resume(out, {1: False}))
    assert out["confirmations"] == []
    assert [m.content for m in tool_messages(out)] == ["Eliminazione della nota 1 annullata dall'utente."] * 2
    assert client.get("/notes/1").status_code == 200


def test_graph_two_deletes_two_confirmations(client):
    tools = make_tools(client)
    tools["add_note"].invoke({"text": "uno"})
    tools["add_note"].invoke({"text": "due"})
    two = AIMessage("", tool_calls=[delete_call(1, "d1"), delete_call(2, "d2")])
    out = confirming_graph(client, two).invoke(_start("elimina tutto"))
    assert [c["id_nota"] for c in out["confirmations"]] == [1, 2]
    assert tool_messages(out) == []


def turn(answer, *tools, history=()):
    return [SystemMessage("s"), *history, HumanMessage("q"), *tools, AIMessage(answer)]


def tool_msg(content, name, status="success"):
    return ToolMessage(content, tool_call_id="t", name=name, status=status)


def asked(question, answer, *tools, history=()):
    return [SystemMessage("s"), *history, HumanMessage(question), *tools, AIMessage(answer)]


SAVE_REQUESTS = ["Salva una nota: comprare il pane", "Annota che domani ho il dentista",
                 "Segnati che venerdì devo chiamare Luca", "Aggiungi una nota: pagare la bolletta",
                 "Ricordami di innaffiare le piante", "Crea un promemoria per la riunione di lunedì",
                 "Nota: comprare le uova", "Scrivi una nota: riportare il libro",
                 "Per favore, salvami un promemoria: x"]
DELETE_REQUESTS = ["Elimina la nota 1", "Cancella la nota 2", "Rimuovi il promemoria 3", "elimina le note 4 e 5"]
OTHER_TOPICS = ["Ricordami come mi chiamo", "Ricordami cosa abbiamo detto", "Cos'è una nota a piè di pagina?",
                "Come si cancella un file in Python?", "Come elimino un elemento da una lista in Python?",
                "Come si salva un file in Python?", "Che differenza c'è tra annotazioni e commenti in Python?",
                "Salva il mondo dalla noia: spiegami cos'è il machine learning",
                "Qual è la nota più alta di un pianoforte?", "Che note ho?", "Mi ricordi di cosa parla la nota 3?",
                "Ricordami di cosa parlava la nota 3", "Ricordami di che colore è il cielo",
                "Rimuovi le note a piè di pagina dal documento", "Cancella le note dal pentagramma",
                "Elimina le note duplicate dalla mia lista Python",
                "Dimmi cosa è un pianoforte, e rimuovi le note stonate", "Scrivi che ore sono",
                "Annota che cos'è un type hint", "Segna che il gol è valido", "Aggiungi note al codice",
                "Crea un promemoria in Python", "Crea una nota musicale in Python con pygame",
                "Scrivi note per una presentazione sul machine learning",
                "Crea note di studio per l'esame di fisica", "Nota: questa funzione è lenta, perché?",
                "Salva una nota: x?", "Elimina la nota 3?"]


@pytest.mark.parametrize("question", SAVE_REQUESTS)
def test_save_request_without_tool_warns(question):
    assert check_note_claims(asked(question, "Ti ricordo di farlo.")) == [SAVE_WARNING]


@pytest.mark.parametrize("question", SAVE_REQUESTS)
def test_save_request_with_tool_no_warning(question):
    assert check_note_claims(asked(question, "Fatto.", tool_msg("Nota 1 salvata: «x»", "add_note"))) == []


@pytest.mark.parametrize("question", DELETE_REQUESTS)
def test_delete_request_without_tool_warns(question):
    assert check_note_claims(asked(question, "Dovrai prima confermare l'eliminazione.")) == [DELETE_WARNING]


@pytest.mark.parametrize("question", OTHER_TOPICS)
def test_other_topics_never_warn(question):
    assert check_note_claims(asked(question, "Ecco la risposta.")) == []


def test_request_and_claim_give_one_warning():
    assert check_note_claims(asked("Salva una nota: x", "Nota salvata.")) == [SAVE_WARNING]


def test_save_and_delete_request_both_warn():
    assert check_note_claims(asked("Salva una nota: x ed elimina la nota 3", "Ok.")) == [SAVE_WARNING, DELETE_WARNING]


def test_clarifying_question_no_request_warning():
    assert check_note_claims(asked("Salva una nota", "Che testo vuoi salvare?  ")) == []


def test_false_claim_with_question_still_warns():
    assert check_note_claims(asked("Salva una nota: x", "Ho salvato la tua nota. Vuoi una scadenza?")) == [SAVE_WARNING]


def test_failed_tool_warns():
    msgs = asked("Elimina la nota 99", "Non esiste.", tool_msg("Nessuna nota con ID 99…", "delete_note", "error"))
    assert check_note_claims(msgs) == [DELETE_WARNING]


def test_review_feedback_keeps_request():
    msgs = [SystemMessage("s"), HumanMessage("Salva una nota: x"), AIMessage("bozza"),
            feedback_message("manca lo strumento"), AIMessage("Ok.")]
    assert check_note_claims(msgs) == [SAVE_WARNING]


def test_previous_turn_request_not_counted():
    history = [HumanMessage("Salva una nota: x"), AIMessage("…")]
    assert check_note_claims(asked("Che ore sono?", "Sono le 10.", history=history)) == []


def test_non_text_question_ignored():
    msgs = [SystemMessage("s"), HumanMessage(content=[{"type": "text", "text": "Salva una nota: x"}]),
            AIMessage("Ok.")]
    assert check_note_claims(msgs) == []


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


def test_add_note_before_review_feedback_still_confirms():
    # l'indicazione del revisore non è una nuova domanda: il turno parte dalla domanda vera
    msgs = [SystemMessage("s"), HumanMessage("q"), tool_msg("Nota 1 salvata: «x»", "add_note"),
            AIMessage("bozza"), feedback_message("manca X."), AIMessage("Ho salvato la nota.")]
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
    "Hai 2 note salvate.",
    "Ecco le note salvate finora: nessuna.",
])
def test_no_claim_no_warning(answer):
    assert check_note_claims(turn(answer)) == []


@pytest.mark.parametrize("answer", [
    "Nota salvata.", "Ok, nota salvata!", "Fatto: promemoria registrato.", "Nota 6 salvata: «x».",
    "Perfetto, la nota è stata aggiunta.", "Ho creato un promemoria per lunedì.", "La nota è stata creata.",
])
def test_short_and_passive_save_claims_warn(answer):
    assert check_note_claims(turn(answer)) == [SAVE_WARNING]


@pytest.mark.parametrize("answer", ["Nota 6 eliminata.", "Ok, nota cancellata.", "Promemoria 3 rimosso."])
def test_short_delete_claims_warn(answer):
    assert check_note_claims(turn(answer)) == [DELETE_WARNING]


def test_short_claim_confirmed_by_tool():
    assert check_note_claims(turn("Nota 6 salvata: «x».", tool_msg("Nota 6 salvata: «x»", "add_note"))) == []


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


@pytest.mark.parametrize("question", ["Salva una nota: x, poi cancella la nota 2", "Salva una nota: x, rimuovi il promemoria 3",
                                       "Ok, elimina la nota 4", "Ehi, elimina la nota 4"])
def test_delete_after_conjunction_or_prefix_warns(question):
    assert DELETE_WARNING in check_note_claims(asked(question, "Ok."))


@pytest.mark.parametrize("question", ["Ok, salva una nota: x", "Ehi, annota che x"])
def test_save_with_prefix_warns(question):
    assert check_note_claims(asked(question, "Ok.")) == [SAVE_WARNING]


def test_delete_without_number_not_a_request():
    assert check_note_claims(asked("Elimina la nota di ieri", "Ok.")) == []
