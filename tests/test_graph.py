import logging
from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from assistant.graph import LIMIT_MESSAGE, build_graph, system_prompt
from assistant.tools import make_clock_tool
from tests.fakes import fake, tool_call

FIXED = lambda: datetime(2026, 10, 26, 13, 32, 5, tzinfo=UTC)
clock = make_clock_tool("Europe/Rome", FIXED)


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


def test_invalid_tool_args_return_error_to_model():
    out = build_graph(fake(tool_call({"timezone": 5}, "a"), AIMessage("ok")), [clock], 5).invoke(start("ora?"))
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.status for m in tool_msgs] == ["error"]
    assert out["messages"][-1].content == "ok"


def test_unknown_tool_args_are_ignored():
    # gli argomenti sconosciuti vengono ignorati: si usa il fuso predefinito
    out = build_graph(fake(tool_call({"tz": 1}, "a"), AIMessage("ok")), [clock], 5).invoke(start("ora?"))
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1 and tool_msgs[0].status == "success"
    assert tool_msgs[0].content.startswith("Europe/Rome: ")
    assert out["messages"][-1].content == "ok"


def test_two_calls_in_one_message():
    msg = AIMessage("", tool_calls=[{"name": "get_current_time", "args": {}, "id": "a"},
                                    {"name": "get_current_time", "args": {"timezone": "Asia/Tokyo"}, "id": "b"}])
    out = build_graph(fake(msg, AIMessage("ok")), [clock], 5).invoke(start("ora a Roma e Tokyo?"))
    assert sum(isinstance(m, ToolMessage) for m in out["messages"]) == 2


def test_system_prompt_mentions_timezone_and_tool():
    p = system_prompt("Asia/Tokyo")
    assert "Asia/Tokyo" in p and "get_current_time" in p and "italiano" in p


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
