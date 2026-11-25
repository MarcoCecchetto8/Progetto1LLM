import logging
import os
import sys
from datetime import date

import httpx
import openai
import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from assistant.graph import (LIMIT_MESSAGE, build_graph, explain_multiplication, system_prompt, today_line,
                            with_today)
from assistant.llm import REASONING_KEY
from assistant.mcp_client import MCPClient, MCPConnectionError
from assistant.reviewer import Review, feedback_message, is_review_feedback
from assistant.router import REFUSAL, Route
from assistant.summarizer import AGENT_SUMMARY_HEADER
from lab_server.preferences import Preferences
from tests.fakes import FakeToolModel, fake, fake_clock as clock, tool_call


def prefs(lingua="italiano", fuso="Europe/Rome", stile="sintetico"):
    return Preferences(lingua, fuso, stile)


def start(text, history=None):
    history = history if history is not None else [SystemMessage("s")]
    return {"messages": history + [HumanMessage(text)], "steps": 0}


def test_direct_answer():
    out = build_graph(fake(AIMessage("Ciao!")), [clock], 5).invoke(start("ciao"))
    assert out["messages"][-1].content == "Ciao!" and out["steps"] == 1


def test_tool_round_trip():
    out = build_graph(fake(tool_call({}, "a"), AIMessage("Sono le 14:32")), [clock], 5).invoke(start("che ora è?"))
    kinds = [type(m).__name__ for m in out["messages"]]
    assert kinds == ["SystemMessage", "HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert out["messages"][3].content == "Europe/Rome: 2026-10-26T14:32:05+01:00"


def test_step_limit_cleans_history():
    model = fake(*[tool_call({}, f"c{i}") for i in range(10)])
    out = build_graph(model, [clock], 5).invoke(start("che ora è?"))
    assert out["steps"] == 5
    assert [m.content for m in out["messages"][1:]] == ["che ora è?", LIMIT_MESSAGE]
    assert not any(isinstance(m, ToolMessage) for m in out["messages"])


def test_step_limit_starts_from_real_question():
    model = fake(*[tool_call({}, f"c{i}") for i in range(10)])
    state = start("che ora è?")
    state["messages"] += [AIMessage("bozza"), feedback_message("manca X.")]
    out = build_graph(model, [clock], 5).invoke(state)
    assert [m.content for m in out["messages"][1:]] == ["che ora è?", LIMIT_MESSAGE]


def test_previous_turns_survive_cleanup():
    # un turno completo, poi un turno che arriva al limite: il primo turno resta intatto
    first = build_graph(fake(tool_call({}, "a"), AIMessage("Sono le 14:32")), [clock], 5).invoke(start("che ora è?"))
    first_turn = first["messages"]
    assert len(first_turn) == 5
    model = fake(*[tool_call({}, f"c{i}") for i in range(10)])
    out = build_graph(model, [clock], 5).invoke(start("e a Tokyo?", history=first_turn))
    assert [m.id for m in out["messages"][:5]] == [m.id for m in first_turn]
    assert [m.content for m in out["messages"][:5]] == [m.content for m in first_turn]
    assert [m.content for m in out["messages"][5:]] == ["e a Tokyo?", LIMIT_MESSAGE]


def test_two_calls_in_one_message():
    msg = AIMessage("", tool_calls=[{"name": "get_current_time", "args": {}, "id": "a"},
                                    {"name": "get_current_time", "args": {"timezone": "Asia/Tokyo"}, "id": "b"}])
    out = build_graph(fake(msg, AIMessage("ok")), [clock], 5).invoke(start("ora a Roma e Tokyo?"))
    assert sum(isinstance(m, ToolMessage) for m in out["messages"]) == 2


def test_system_prompt_mentions_timezone_and_tool():
    p = system_prompt(prefs(fuso="Asia/Tokyo"))
    assert "Asia/Tokyo" in p and "get_current_time" in p and "italiano" in p


BLOCK_START = "Preferenze dell'utente (dalla resource utente://preferenze):\n- Rispondi sempre in inglese.\n"


def test_system_prompt_starts_with_preferences_block():
    p = system_prompt(prefs("inglese", "America/New_York"))
    assert p.startswith(BLOCK_START)
    assert p.split("\n\n")[0].count("\n") == 2
    assert "America/New_York" in p
    assert "Fuso orario predefinito" not in p.split("\n\n")[0]
    assert "Se l'utente non indica un fuso orario usa `America/New_York`" in p
    assert "Rispondi sempre in italiano, in modo chiaro e conciso" not in p
    assert "\n\nSei l'assistente del laboratorio. Quando l'utente ti saluta, presentati brevemente." in p


def test_system_prompt_style_texts():
    assert "- Stile: sintetico: rispondi in una o due frasi, solo con ciò che è chiesto." in system_prompt(prefs(stile="sintetico"))
    assert ("- Stile: dettagliato: aggiungi alla risposta il contesto utile preso dai risultati degli "
            "strumenti, in qualche frase o in un breve elenco.") in system_prompt(prefs(stile="dettagliato"))


def test_limit_logged(caplog):
    model = fake(*[tool_call({}, f"c{i}") for i in range(10)])
    with caplog.at_level(logging.INFO, logger="assistant.graph"):
        build_graph(model, [clock], 5).invoke(start("che ora è?"))
    assert any(r.name == "assistant.graph" and r.levelno == logging.INFO
               and "limite di passaggi" in r.getMessage() for r in caplog.records)


def test_removed_messages_logged_at_debug(caplog):
    model = fake(*[tool_call({}, f"c{i}") for i in range(10)])
    with caplog.at_level(logging.DEBUG, logger="assistant.graph"):
        build_graph(model, [clock], 5).invoke(start("che ora è?"))
    text = " ".join(r.getMessage() for r in caplog.records if r.name == "assistant.graph")
    assert "rimosso" in text and "get_current_time" in text


def test_tool_error_returns_error_status():
    out = build_graph(fake(tool_call({"timezone": "Marte/Base"}, "a"), AIMessage("ok")), [clock], 5).invoke(start("ora?"))
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.status for m in tool_msgs] == ["error"]
    assert tool_msgs[0].content.startswith("Errore: Fuso orario sconosciuto")
    assert out["messages"][-1].content == "ok"


def test_unknown_tool_name():
    out = build_graph(fake(tool_call({}, "a", name="inesistente"), AIMessage("ok")), [clock], 5).invoke(start("ora?"))
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.status for m in tool_msgs] == ["error"]
    assert out["messages"][-1].content == "ok"


def test_connection_error_propagates():
    @tool
    def get_current_time() -> str:
        """Server caduto."""
        raise MCPConnectionError("Il server degli strumenti non risponde")

    with pytest.raises(MCPConnectionError):
        build_graph(fake(tool_call({}, "a"), AIMessage("ok")), [get_current_time], 5).invoke(start("ora?"))


def test_tool_call_logged_with_call_id(caplog):
    model = fake(tool_call({}, "a"), tool_call({"timezone": "Marte/Base"}, "b"), AIMessage("ok"))
    with caplog.at_level(logging.DEBUG, logger="assistant.graph"):
        build_graph(model, [clock], 5).invoke(start("ora?"))
    assert ("[strumento] get_current_time call_id=a argomenti={} esito=ok → "
            "Europe/Rome: 2026-10-26T14:32:05+01:00") in caplog.text
    assert '[strumento] get_current_time call_id=b argomenti={"timezone": "Marte/Base"} esito=errore' in caplog.text


def test_tool_call_not_logged_at_info(caplog):
    model = fake(tool_call({}, "a"), AIMessage("ok"))
    with caplog.at_level(logging.INFO, logger="assistant.graph"):
        build_graph(model, [clock], 5).invoke(start("ora?"))
    assert "[strumento]" not in caplog.text


def test_reasoning_not_saved_in_history():
    extra = {REASONING_KEY: "pensiero", "altro": 1}
    out = build_graph(fake(AIMessage("ok", additional_kwargs=dict(extra))), [clock], 5).invoke(start("ciao"))
    last = out["messages"][-1]
    assert last.content == "ok" and last.additional_kwargs == {"altro": 1}
    with_call = AIMessage("", tool_calls=[{"name": "get_current_time", "args": {}, "id": "a"}],
                          additional_kwargs=dict(extra))
    out = build_graph(fake(with_call, AIMessage("ok")), [clock], 5).invoke(start("ora?"))
    ai = out["messages"][-3]
    assert ai.tool_calls[0]["id"] == "a" and REASONING_KEY not in ai.additional_kwargs
    assert ai.additional_kwargs["altro"] == 1 and isinstance(out["messages"][-2], ToolMessage)


def test_graph_with_mcp_tool():
    with MCPClient([sys.executable, "-m", "tests.mcp_test_server"], os.environ) as tools:
        model = fake(tool_call({"text": "ciao"}, "m1", name="echo"), AIMessage("fatto"))
        out = build_graph(model, tools, 5).invoke(start("ripeti ciao"))
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [(m.tool_call_id, m.content, m.status) for m in tool_msgs] == [("m1", "ciao", "success")]
    assert out["messages"][-1].content == "fatto"


def test_system_prompt_mentions_tools_and_errors():
    p = system_prompt(prefs())
    assert "convert_units" in p and "non inventare" in p and "errore" in p


def test_system_prompt_mentions_calculator_and_equations():
    p = system_prompt(prefs())
    assert "calculate" in p and "2x = 28" in p and "28 / 2" in p


def test_system_prompt_mentions_date_tools():
    p = system_prompt(prefs())
    assert all(name in p for name in ("date_info", "find_holiday", "add_days", "days_between", "AAAA-MM-GG"))


def test_system_prompt_forbids_counting_days():
    p = system_prompt(prefs())
    assert "non contare tu i giorni" in p and "days_between" in p


def test_system_prompt_mentions_catalog():
    p = system_prompt(prefs())
    assert "search_catalog" in p and "get_item" in p and "max_results" in p


def test_system_prompt_requires_catalog_lookup():
    p = system_prompt(prefs())
    assert "chiama sempre gli strumenti del catalogo prima di rispondere" in p
    assert "non dire mai che un dato non c'è senza averlo cercato" in p
    assert "chiama subito `get_item` con quel codice" in p


def test_graph_catalog_search_then_detail():
    with MCPClient([sys.executable, "-m", "lab_server"], os.environ) as tools:
        model = fake(tool_call({"query": "Haskell"}, "s1", name="search_catalog"),
                     tool_call({"code": "HS"}, "g1", name="get_item"),
                     AIMessage("Haskell è del 1990."))
        out = build_graph(model, tools, 5).invoke(start("parlami di Haskell"))
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [(m.tool_call_id, m.status) for m in tool_msgs] == [("s1", "success"), ("g1", "success")]
    assert tool_msgs[1].content.startswith("Haskell (HS)")
    assert out["messages"][-1].content == "Haskell è del 1990." and out["steps"] == 3


def test_system_prompt_mentions_notes_tools():
    prompt = system_prompt(prefs())
    for word in ("add_note", "list_notes", "delete_note", "ID esatto", "chiederà conferma"):
        assert word in prompt


def test_system_prompt_notes_weekday_rule():
    prompt = system_prompt(prefs())
    for word in ("«venerdì»", "non chiedergli la data", "così com'è", "«Nota N salvata»"):
        assert word in prompt
    assert "ricavala tu con `get_current_time` e `add_days`" not in prompt
    assert "non chiedere tu conferma" not in prompt


def test_answer_check_appends_warnings():
    check = lambda msgs: ["⚠ A", "⚠ B"]
    out = build_graph(fake(AIMessage("Fatto.")), [clock], 5, answer_check=check).invoke(start("x"))
    last = out["messages"][-1]
    assert isinstance(last, AIMessage) and last.content == "Fatto.\n\n⚠ A\n⚠ B"
    assert out["steps"] == 1 and len(out["messages"]) == 3


def test_answer_check_without_warnings_leaves_answer():
    out = build_graph(fake(AIMessage("Fatto.")), [clock], 5, answer_check=lambda msgs: []).invoke(start("x"))
    assert out["messages"][-1].content == "Fatto."


def test_answer_check_receives_turn_messages():
    seen = []
    check = lambda msgs: seen.append(list(msgs)) or []
    model = fake(tool_call({}, "a"), AIMessage("Sono le 14:32"))
    build_graph(model, [clock], 5, answer_check=check).invoke(start("che ora è?"))
    assert len(seen) == 1
    assert any(isinstance(m, ToolMessage) and m.name == "get_current_time" for m in seen[0])
    assert isinstance(seen[0][-1], AIMessage) and seen[0][-1].content == "Sono le 14:32"


def test_answer_check_skipped_on_step_limit():
    calls = []
    check = lambda msgs: calls.append(1) or ["⚠"]
    model = fake(*[tool_call({}, f"c{i}") for i in range(10)])
    out = build_graph(model, [clock], 5, answer_check=check).invoke(start("che ora è?"))
    assert out["messages"][-1].content == LIMIT_MESSAGE and calls == []


def test_answer_check_skips_non_string_content():
    content = [{"type": "text", "text": "Fatto."}]
    out = build_graph(fake(AIMessage(content=content)), [clock], 5, answer_check=lambda msgs: ["⚠"]).invoke(start("x"))
    assert out["messages"][-1].content == content


def test_answer_check_logged(caplog):
    check = lambda msgs: ["⚠ A", "⚠ B"]
    with caplog.at_level(logging.INFO, logger="assistant.graph"):
        build_graph(fake(AIMessage("Fatto.")), [clock], 5, answer_check=check).invoke(start("x"))
    assert "[controllo] falso successo: avviso all'utente → ⚠ A | ⚠ B" in caplog.text


def make_router(category="conversazione", reason="saluto", error=None):
    calls = []

    def router(messages, summary):
        calls.append((messages, summary))
        if error:
            raise error
        return Route(categoria=category, motivo=reason)

    router.calls = calls
    return router


def test_router_in_scope_runs_agent(caplog):
    router = make_router()
    with caplog.at_level(logging.INFO, logger="assistant.graph"):
        out = build_graph(fake(AIMessage("Ciao!")), [clock], 5, router=router).invoke(start("ciao"))
    assert out["messages"][-1].content == "Ciao!"
    assert len(router.calls) == 1
    assert "[router] categoria=conversazione motivo=saluto → agente" in caplog.text


def test_router_out_of_scope_refuses_without_agent(caplog):
    model = fake(AIMessage("non deve comparire"))
    router = make_router("fuori_ambito", "cucina")
    with caplog.at_level(logging.DEBUG, logger="assistant.graph"):
        out = build_graph(model, [clock], 5, router=router).invoke(start("come si fa la carbonara?"))
    assert out["messages"][-1].content == REFUSAL.format(motivo="cucina")
    assert next(model.messages).content == "non deve comparire"
    assert out["steps"] == 0
    assert "[router] categoria=fuori_ambito motivo=cucina → rifiuto" in caplog.text
    assert "[grafo] nodo model" not in caplog.text


def test_router_invalid_output_falls_back_to_agent(caplog):
    router = make_router(error=OutputParserException("x"))
    with caplog.at_level(logging.WARNING, logger="assistant.graph"):
        out = build_graph(fake(AIMessage("Ciao!")), [clock], 5, router=router).invoke(start("ciao"))
    assert out["messages"][-1].content == "Ciao!"
    assert any(r.levelno == logging.WARNING and "[router] risposta non valida" in r.getMessage()
               for r in caplog.records)


def test_router_api_error_propagates():
    error = openai.APIConnectionError(request=httpx.Request("POST", "http://localhost:1234/v1"))
    graph = build_graph(fake(AIMessage("Ciao!")), [clock], 5, router=make_router(error=error))
    with pytest.raises(openai.APIConnectionError):
        graph.invoke(start("ciao"))


def test_router_receives_summary():
    router = make_router()
    state = start("dove vivo?")
    state["summary"] = "Marco vive a Roma."
    build_graph(fake(AIMessage("A Roma.")), [clock], 5, router=router).invoke(state)
    assert router.calls[0][1] == "Marco vive a Roma."
    build_graph(fake(AIMessage("Ciao!")), [clock], 5, router=router).invoke(start("ciao"))
    assert router.calls[1][1] == ""


def test_router_does_not_add_messages():
    out = build_graph(fake(AIMessage("Ciao!")), [clock], 5, router=make_router()).invoke(start("ciao"))
    assert [type(m) for m in out["messages"]] == [SystemMessage, HumanMessage, AIMessage]


def make_reviewer(*verdicts):
    # verdicts: (coerente, motivo) oppure un'eccezione; registra (domanda, risposta), (riassunto, recente) e strumenti
    calls = []
    contexts = []
    tools = []
    queue = iter(verdicts)

    def reviewer(question, answer, summary, recent, tool_results):
        calls.append((question, answer))
        contexts.append((summary, recent))
        tools.append(tool_results)
        verdict = next(queue)
        if isinstance(verdict, Exception):
            raise verdict
        return Review(coerente=verdict[0], motivo=verdict[1])

    reviewer.calls = calls
    reviewer.contexts = contexts
    reviewer.tools = tools
    return reviewer


def test_reviewer_approves_first_time(caplog):
    reviewer = make_reviewer((True, "ok"))
    with caplog.at_level(logging.DEBUG, logger="assistant.graph"):
        out = build_graph(fake(AIMessage("Ciao!")), [clock], 5, reviewer=reviewer).invoke(start("ciao"))
    assert [m.content for m in out["messages"]] == ["s", "ciao", "Ciao!"]
    assert out["reviews"] == 0 and reviewer.calls == [("ciao", "Ciao!")]
    assert "[revisore] coerente=sì motivo=ok revisione 0/3" in caplog.text


def test_reviewer_rejects_then_approves():
    seen = []

    class RecordingModel(FakeToolModel):
        def invoke(self, messages, *args, **kwargs):
            seen.append(list(messages))
            return super().invoke(messages, *args, **kwargs)

    model = RecordingModel(messages=iter([AIMessage("A Tokyo sono le 19:03."),
                                          AIMessage("A Tokyo sono le 19:03 e il 15% di 80 fa 12.")]))
    reviewer = make_reviewer((False, "manca il calcolo."), (True, "ok"))
    out = build_graph(model, [clock], 5, reviewer=reviewer).invoke(start("ora a Tokyo e il 15% di 80"))
    assert reviewer.calls[0][0] == reviewer.calls[1][0] == "ora a Tokyo e il 15% di 80"
    assert "manca il calcolo." in seen[1][-1].content and is_review_feedback(seen[1][-1])
    assert [type(m).__name__ for m in out["messages"]] == ["SystemMessage", "HumanMessage", "AIMessage"]
    assert out["messages"][-1].content.endswith("fa 12.") and out["reviews"] == 1


def test_reviewer_limit(caplog):
    model = fake(*[AIMessage(f"r{i}") for i in range(4)])
    reviewer = make_reviewer(*[(False, "no")] * 4)
    with caplog.at_level(logging.DEBUG, logger="assistant.graph"):
        out = build_graph(model, [clock], 5, reviewer=reviewer, max_reviews=3).invoke(start("q"))
    assert len(reviewer.calls) == 4 and out["reviews"] == 3
    assert "[revisore] limite raggiunto (3 revisioni): resta l'ultima risposta" in caplog.text
    assert [m.content for m in out["messages"]] == ["s", "q", "r3"]


def test_reviewer_zero_reviews():
    reviewer = make_reviewer((False, "no"))
    out = build_graph(fake(AIMessage("r0")), [clock], 5, reviewer=reviewer, max_reviews=0).invoke(start("q"))
    assert len(reviewer.calls) == 1 and out["review_outcome"] == "limit"
    assert [m.content for m in out["messages"]] == ["s", "q", "r0"]


def test_reviewer_invalid_output_approves(caplog):
    reviewer = make_reviewer(OutputParserException("x"))
    out = build_graph(fake(AIMessage("Ciao!")), [clock], 5, reviewer=reviewer).invoke(start("ciao"))
    assert out["messages"][-1].content == "Ciao!" and out["review_outcome"] == "invalid"
    assert any(r.levelno == logging.WARNING and "[revisore] risposta non valida" in r.getMessage()
               for r in caplog.records)


def test_reviewer_without_context():
    reviewer = make_reviewer((True, "ok"))
    build_graph(fake(AIMessage("Ciao!")), [clock], 5, reviewer=reviewer).invoke(start("ciao"))
    assert reviewer.contexts == [("", "")]


def test_reviewer_receives_summary_and_recent_text():
    history = [SystemMessage("s"), HumanMessage("chi ha creato Rust?"), tool_call({}, "c1"),
               ToolMessage("Graydon Hoare", tool_call_id="c1", name="get_item"), AIMessage("Graydon Hoare.")]
    state = start("di cosa abbiamo parlato?", history=history)
    state["summary"] = "Marco vive a Roma."
    reviewer = make_reviewer((False, "manca qualcosa."), (True, "ok"))
    build_graph(fake(AIMessage("bozza"), AIMessage("Di Rust.")), [clock], 5, reviewer=reviewer).invoke(state)
    expected = ("Marco vive a Roma.", "Utente: chi ha creato Rust?\nAssistente: Graydon Hoare.")
    # Al secondo giudizio la recente non contiene né la bozza né l'indicazione del revisore
    assert reviewer.contexts == [expected, expected]
    assert reviewer.calls[1] == ("di cosa abbiamo parlato?", "Di Rust.")
    # I risultati degli strumenti del turno precedente non sono del turno corrente
    assert reviewer.tools == ["", ""]


def test_reviewer_receives_tool_results_of_turn():
    reviewer = make_reviewer((False, "manca qualcosa."), (True, "ok"))
    model = fake(tool_call({"timezone": "Asia/Tokyo"}, "c1"), AIMessage("bozza"), AIMessage("Sono le 22:32."))
    build_graph(model, [clock], 5, reviewer=reviewer).invoke(start("che ore sono a Tokyo?"))
    # Anche al secondo giudizio: il risultato del primo tentativo resta nel turno
    assert reviewer.tools == ["get_current_time: Asia/Tokyo: 2026-10-26T22:32:05+09:00"] * 2


def test_reviewer_skipped():
    reviewer = make_reviewer()
    router = make_router("fuori_ambito", "cucina")
    build_graph(fake(AIMessage("x")), [clock], 5, router=router, reviewer=reviewer).invoke(start("carbonara?"))
    build_graph(fake(*[tool_call({}, f"c{i}") for i in range(5)]), [clock], 2, reviewer=reviewer).invoke(start("ora?"))
    build_graph(fake(AIMessage("")), [clock], 5, reviewer=reviewer).invoke(start("ciao"))
    assert reviewer.calls == []


def test_reviewer_keeps_tool_traffic():
    model = fake(tool_call({}, "a"), AIMessage("Sono le 14:32."), AIMessage("Sono le 14:32 e 12 è il calcolo."))
    reviewer = make_reviewer((False, "manca."), (True, "ok"))
    out = build_graph(model, [clock], 5, reviewer=reviewer).invoke(start("ora e calcolo"))
    kinds = [type(m).__name__ for m in out["messages"]]
    assert kinds == ["SystemMessage", "HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert out["messages"][2].tool_calls and out["messages"][-1].content.endswith("calcolo.")


def test_reviewer_resets_steps():
    model = fake(tool_call({}, "a"), AIMessage("bozza"), tool_call({}, "b"), AIMessage("finale"))
    reviewer = make_reviewer((False, "manca."), (True, "ok"))
    out = build_graph(model, [clock], 2, reviewer=reviewer).invoke(start("ora?"))
    assert all(m.content != LIMIT_MESSAGE for m in out["messages"])
    assert out["messages"][-1].content == "finale"


def test_reviewer_then_answer_check():
    model = fake(AIMessage("bozza"), AIMessage("Nota salvata."))
    reviewer = make_reviewer((False, "manca."), (True, "ok"))
    out = build_graph(model, [clock], 5, answer_check=lambda m: ["Attenzione: falso successo."],
                      reviewer=reviewer).invoke(start("salva una nota"))
    assert out["messages"][-1].content == "Nota salvata.\n\nAttenzione: falso successo."
    assert [m.content for m in out["messages"]][:2] == ["s", "salva una nota"] and len(out["messages"]) == 3



def test_reviewer_skips_blank_answer():
    reviewer = make_reviewer()
    build_graph(fake(AIMessage("   ")), [clock], 5, reviewer=reviewer).invoke(start("ciao"))
    assert reviewer.calls == []


@pytest.mark.parametrize("motivo,expected", [("manca\nil  calcolo.", "manca il calcolo."),
                                             ("  ", "il motivo non è stato indicato")])
def test_reviewer_reason_normalized(motivo, expected):
    # Il motivo finisce in una riga del terminale e nell'indicazione all'agente: una riga sola, mai vuoto
    reviewer = make_reviewer((False, motivo))
    out = build_graph(fake(AIMessage("bozza")), [clock], 5, reviewer=reviewer, max_reviews=0).invoke(start("q"))
    assert out["review_reason"] == expected


def test_reviewer_logs_only_at_debug(caplog):
    # Le righe del revisore compaiono già nello streaming: a INFO il log non le ripete
    reviewer = make_reviewer((False, "manca."))
    with caplog.at_level(logging.INFO, logger="assistant.graph"):
        build_graph(fake(AIMessage("bozza")), [clock], 5, reviewer=reviewer, max_reviews=0).invoke(start("q"))
    assert "[revisore]" not in caplog.text


# --- Riassunto della cronologia ---

def past_history(turns):
    history = [SystemMessage("s")]
    for i in range(1, turns + 1):
        history += [HumanMessage(f"domanda {i}"), AIMessage(f"risposta {i}")]
    return history


def recording_summarizer(text="RIASSUNTO"):
    calls = []

    def summarize(previous, conversation):
        calls.append((previous, conversation))
        return text

    summarize.calls = calls
    return summarize


def test_summarizer_below_threshold_not_called():
    summarize = recording_summarizer()
    state = start("ultima", history=past_history(3))
    out = build_graph(fake(AIMessage("ok")), [clock], 5, summarizer=summarize, summary_threshold=10_000,
                      summary_keep_turns=2).invoke(state)
    assert summarize.calls == []
    assert len(out["messages"]) == 9
    assert "summary" not in out


def test_summarizer_compresses_old_turns():
    summarize = recording_summarizer()
    out = build_graph(fake(AIMessage("ok")), [clock], 5, summarizer=summarize, summary_threshold=1,
                      summary_keep_turns=2).invoke(start("ultima", history=past_history(3)))
    assert summarize.calls == [("", "Utente: domanda 1\nAssistente: risposta 1")]
    assert [m.content for m in out["messages"]] == ["s", "domanda 2", "risposta 2", "domanda 3", "risposta 3",
                                                    "ultima", "ok"]
    assert out["summary"] == "RIASSUNTO"
    assert out["summary_line"].startswith("[riassunto] 8 → 6 messaggi (circa ")


def test_summarizer_replaces_previous_summary():
    summarize = recording_summarizer("NUOVO")
    state = start("ultima", history=past_history(3))
    state["summary"] = "VECCHIO"
    out = build_graph(fake(AIMessage("ok")), [clock], 5, summarizer=summarize, summary_threshold=1,
                      summary_keep_turns=2).invoke(state)
    assert summarize.calls[0][0] == "VECCHIO"
    assert out["summary"] == "NUOVO"


def test_summarizer_failure_keeps_history(caplog):
    def failing(previous, conversation):
        raise openai.APIConnectionError(request=httpx.Request("POST", "http://x"))

    for summarize, reason in ((failing, "Connection error"), (lambda p, c: "  ", "testo vuoto")):
        caplog.clear()
        state = start("ultima", history=past_history(3))
        with caplog.at_level(logging.WARNING, logger="assistant.graph"):
            out = build_graph(fake(AIMessage("ok")), [clock], 5, summarizer=summarize, summary_threshold=1,
                              summary_keep_turns=2).invoke(state)
        assert [m.content for m in out["messages"]][:-1] == [m.content for m in state["messages"]]
        assert out["messages"][-1].content == "ok"
        assert "summary" not in out
        assert any("cronologia invariata" in r.message and reason in r.message for r in caplog.records)


def test_model_receives_summary_in_system_prompt():
    seen = []

    class Recording(FakeToolModel):
        def _generate(self, messages, *args, **kwargs):
            seen.append(list(messages))
            return super()._generate(messages, *args, **kwargs)

    state = start("ciao")
    state["summary"] = "R"
    out = build_graph(Recording(messages=iter([AIMessage("ok")])), [clock], 5).invoke(state)
    assert seen[0][0].content == f"s\n\n{AGENT_SUMMARY_HEADER}\nR"
    assert out["messages"][0].content == "s"


def today_recorder():
    seen = []

    class Recording(FakeToolModel):
        def _generate(self, messages, *args, **kwargs):
            seen.append(list(messages))
            return super()._generate(messages, *args, **kwargs)

    return seen, Recording


def test_today_line_italian():
    assert today_line(date(2026, 11, 19), "Europe/Rome") == \
        "Oggi è giovedì 19 novembre 2026 (2026-11-19), fuso orario Europe/Rome."
    assert today_line(date(2027, 1, 3), "Asia/Tokyo") == \
        "Oggi è domenica 3 gennaio 2027 (2027-01-03), fuso orario Asia/Tokyo."


def test_with_today_only_for_call():
    messages = [SystemMessage("s"), HumanMessage("q")]
    assert with_today(messages, "") is messages
    result = with_today(messages, "Oggi è X.")
    assert result[0].content == "s\n\nOggi è X." and messages[0].content == "s"


def test_model_receives_today_line():
    seen, Recording = today_recorder()
    out = build_graph(Recording(messages=iter([AIMessage("ok")])), [clock], 5,
                      today=lambda: "Oggi è X.").invoke(start("ciao"))
    assert seen[0][0].content == "s\n\nOggi è X."
    assert out["messages"][0].content == "s"


def test_today_line_before_summary():
    seen, Recording = today_recorder()
    state = start("ciao")
    state["summary"] = "R"
    build_graph(Recording(messages=iter([AIMessage("ok")])), [clock], 5, today=lambda: "Oggi è X.").invoke(state)
    assert seen[0][0].content == f"s\n\nOggi è X.\n\n{AGENT_SUMMARY_HEADER}\nR"


def test_today_line_on_every_call():
    seen, Recording = today_recorder()
    out = build_graph(Recording(messages=iter([tool_call({}, "a"), AIMessage("ok")])), [clock], 5,
                      today=lambda: "Oggi è X.").invoke(start("che ora è?"))
    assert len(seen) == 2 and all(call[0].content == "s\n\nOggi è X." for call in seen)
    assert all("Oggi è X." not in str(m.content) for m in out["messages"])


def test_today_line_follows_the_clock():
    seen, Recording = today_recorder()
    days = iter(["Oggi è A.", "Oggi è B."])
    graph = build_graph(Recording(messages=iter([AIMessage("1"), AIMessage("2")])), [clock], 5,
                        today=lambda: next(days))
    graph.invoke(start("uno"))
    graph.invoke(start("due"))
    assert seen[0][0].content.endswith("A.") and seen[1][0].content.endswith("B.")


def test_without_today_unchanged():
    seen, Recording = today_recorder()
    build_graph(Recording(messages=iter([AIMessage("ok")])), [clock], 5).invoke(start("ciao"))
    assert seen[0][0].content == "s"


def test_summarizer_runs_once_with_reviewer_retry():
    summarize = recording_summarizer()
    verdicts = iter([Review(coerente=False, motivo="no"), Review(coerente=True, motivo="ok")])
    build_graph(fake(AIMessage("a"), AIMessage("b")), [clock], 5, summarizer=summarize, summary_threshold=1,
                summary_keep_turns=2, reviewer=lambda q, a, s, r, t: next(verdicts)).invoke(
        start("ultima", history=past_history(3)))
    assert len(summarize.calls) == 1


def test_summarizer_runs_before_router():
    order = []

    def summarize(previous, conversation):
        order.append("riassunto")
        return "R"

    def route(messages, summary):
        order.append(f"router con {summary}")
        return Route(categoria="conversazione", motivo="")

    build_graph(fake(AIMessage("ok")), [clock], 5, summarizer=summarize, summary_threshold=1,
                summary_keep_turns=2, router=route).invoke(start("ultima", history=past_history(3)))
    assert order == ["riassunto", "router con R"]


# --- Conferma come sospensione del grafo ---

def ask_until_decided(calls, decisions):
    return [] if 7 in decisions else [{"id_nota": 7, "domanda": "?"}]


@pytest.mark.parametrize("with_extras", [False, True])
def test_confirmation_suspends_and_resumes_from_confirm(with_extras):
    summarize, router = recording_summarizer(), make_router()
    extras = {"summarizer": summarize, "summary_threshold": 1, "router": router} if with_extras else {}
    graph = build_graph(fake(tool_call({}, "a"), AIMessage("Sono le 14:32")), [clock], 5,
                        confirmation_check=ask_until_decided, **extras)
    out = graph.invoke(start("che ora è?", history=past_history(3)))
    assert out["confirmations"] == [{"id_nota": 7, "domanda": "?"}]
    assert not any(isinstance(m, ToolMessage) for m in out["messages"])
    before = (len(summarize.calls), len(router.calls))

    out = graph.invoke({"messages": out["messages"], "steps": out["steps"], "decisions": {7: True}})
    assert out["confirmations"] == []
    assert out["messages"][-1].content == "Sono le 14:32"
    assert (len(summarize.calls), len(router.calls)) == before


def test_tools_receive_decisions_in_configurable():
    seen = []

    @tool
    def spy(config: RunnableConfig) -> str:
        """Strumento spia."""
        seen.append(config["configurable"])
        return "ok"

    graph = build_graph(fake(tool_call({}, "a", name="spy"), AIMessage("fine")), [spy], 5,
                        confirmation_check=lambda calls, decisions: [])
    graph.invoke({**start("q"), "decisions": {3: False}}, config={"configurable": {"altro": 1}})
    assert seen[0]["note_decisions"] == {3: False} and seen[0]["altro"] == 1


def test_without_confirmation_check_no_confirmations_key():
    out = build_graph(fake(tool_call({}, "a"), AIMessage("ok")), [clock], 5).invoke(start("ora?"))
    assert "confirmations" not in out


def test_system_prompt_explains_per_and_diviso():
    # «37 per 19» veniva calcolato come 37 / 19
    p = system_prompt(prefs())
    assert "«per» è la moltiplicazione" in p and "37 * 19" in p


def test_system_prompt_requires_add_days_for_future_dates():
    # «che data sarà fra 45 giorni?» veniva calcolato a mente (e sbagliato)
    p = system_prompt(prefs())
    assert "fra N giorni" in p and "chiama `add_days`" in p


@pytest.mark.parametrize("text, expected", [
    ("Quanto fa 37 per 19?", "Quanto fa 37 × 19?"),
    ("Quanto fa 120 diviso 8 per 3?", "Quanto fa 120 diviso 8 × 3?"),
    ("2,5 per 4 e 3.5 per 2", "2,5 × 4 e 3.5 × 2"),
    ("Dividi 20 per 3", "Dividi 20 per 3"),            # «dividere X per Y»: qui «per» è la divisione
    ("Il 15 per cento di 80", "Il 15 per cento di 80"),  # non seguito da un numero
    ("Ricordami di chiamare Luca", "Ricordami di chiamare Luca"),
])
def test_explain_multiplication(text, expected):
    assert explain_multiplication(text) == expected


class RecordingFake(FakeToolModel):
    received: list = []

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.received.append(messages)
        yield from super()._stream(messages, stop, run_manager, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.received.append(messages)
        return super()._generate(messages, stop, run_manager, **kwargs)


def test_model_sees_multiplication_but_history_keeps_user_text():
    model = RecordingFake(messages=iter([AIMessage("703")]), received=[])
    graph = build_graph(model, [], 5)
    out = graph.invoke({"messages": [SystemMessage("sys"), HumanMessage("Quanto fa 37 per 19?")], "steps": 0})
    assert out["messages"][1].content == "Quanto fa 37 per 19?"  # la cronologia resta com'era
    assert model.received[0][-1].content == "Quanto fa 37 × 19?"  # il modello vede la moltiplicazione


def test_system_prompt_remembers_what_the_user_says():
    assert "il nome" in system_prompt(prefs()) and "usalo" in system_prompt(prefs())
