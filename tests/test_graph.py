import logging
import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from assistant.graph import LIMIT_MESSAGE, build_graph, system_prompt
from assistant.mcp_client import MCPClient, MCPConnectionError
from tests.fakes import fake, fake_clock as clock, tool_call


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
    with caplog.at_level(logging.INFO, logger="assistant.graph"):
        build_graph(model, [clock], 5).invoke(start("ora?"))
    assert ("[strumento] get_current_time call_id=a argomenti={} esito=ok → "
            "Europe/Rome: 2026-10-26T14:32:05+01:00") in caplog.text
    assert '[strumento] get_current_time call_id=b argomenti={"timezone": "Marte/Base"} esito=errore' in caplog.text


def test_graph_with_mcp_tool():
    with MCPClient([sys.executable, "-m", "tests.mcp_test_server"], os.environ) as tools:
        model = fake(tool_call({"text": "ciao"}, "m1", name="echo"), AIMessage("fatto"))
        out = build_graph(model, tools, 5).invoke(start("ripeti ciao"))
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [(m.tool_call_id, m.content, m.status) for m in tool_msgs] == [("m1", "ciao", "success")]
    assert out["messages"][-1].content == "fatto"


def test_system_prompt_mentions_tools_and_errors():
    p = system_prompt("Europe/Rome")
    assert "convert_units" in p and "non inventare" in p and "errore" in p
