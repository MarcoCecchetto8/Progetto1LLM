import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError

from agent_service.messages import (
    Message,
    ToolCall,
    dump_state_messages,
    from_langchain,
    load_state_messages,
    to_langchain,
)
from assistant.reviewer import feedback_message, is_review_feedback


def test_utente_andata_e_ritorno():
    msgs = [Message(ruolo="utente", contenuto="ciao")]
    lc = to_langchain(msgs)
    assert isinstance(lc[0], HumanMessage)
    assert from_langchain(lc) == msgs


def test_assistente_con_due_chiamate():
    msg = Message(
        ruolo="assistente",
        contenuto="",
        chiamate=[
            ToolCall(id="a", nome="ora", argomenti={"fuso": "Europe/Rome"}),
            ToolCall(id="b", nome="somma", argomenti={"x": 1}),
        ],
    )
    lc = to_langchain([msg])
    assert isinstance(lc[0], AIMessage)
    assert [c["id"] for c in lc[0].tool_calls] == ["a", "b"]
    assert from_langchain(lc) == [msg]


def test_strumento_con_errore():
    msg = Message(ruolo="strumento", contenuto="boom", id_chiamata="a", nome="ora", errore=True)
    lc = to_langchain([msg])
    assert isinstance(lc[0], ToolMessage)
    assert lc[0].status == "error"
    assert from_langchain(lc) == [msg]


def test_strumento_senza_errore():
    msg = Message(ruolo="strumento", contenuto="ok", id_chiamata="a", nome="ora")
    assert to_langchain([msg])[0].status == "success"


def test_from_langchain_scarta_il_system():
    out = from_langchain([SystemMessage("s"), HumanMessage("q")])
    assert [m.ruolo for m in out] == ["utente"]


def test_contenuto_a_blocchi():
    ai = AIMessage(content=[{"type": "text", "text": "a"}, {"type": "image", "x": 1}, {"type": "text", "text": "b"}])
    assert from_langchain([ai])[0].contenuto == "ab"


def test_validazione():
    with pytest.raises(ValidationError):
        Message(ruolo="strumento", contenuto="x")
    with pytest.raises(ValidationError):
        Message(ruolo="sistema")
    with pytest.raises(ValidationError):
        Message(ruolo="utente", chiamate=[ToolCall(id="a", nome="n", argomenti={})])


def test_stato_senza_perdite():
    original = feedback_message("m")
    [loaded] = load_state_messages(dump_state_messages([original]))
    assert is_review_feedback(loaded)
    assert loaded.id == original.id


def test_stato_non_valido():
    with pytest.raises(ValueError, match="stato sospeso non valido"):
        load_state_messages([{"x": 1}])
