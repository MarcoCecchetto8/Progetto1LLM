from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from assistant.reviewer import feedback_message
from assistant.summarizer import (AGENT_SUMMARY_HEADER, SUMMARIZER_INSTRUCTIONS, SUMMARY_HEADER, build_summarizer, estimate_tokens,
                                  summary_cut, summary_line, summary_request, transcript, turn_starts,
                                  with_summary)


def turn(i):
    return [HumanMessage(f"domanda {i}"), AIMessage(f"risposta {i}")]


def test_estimate_tokens():
    messages = [SystemMessage("a" * 40), HumanMessage("b" * 40)]
    assert estimate_tokens(messages) == 20
    assert estimate_tokens(messages, summary="c" * 40) == 30
    call = AIMessage("", tool_calls=[{"name": "calc", "args": {"x": 1}, "id": "1"}])
    assert estimate_tokens([call]) == (len("calc") + len('{"x": 1}')) // 4


def test_cut_keeps_last_turns():
    messages = [SystemMessage("s")]
    for i in range(4):
        messages += turn(i)
    messages.append(HumanMessage("corrente"))
    # Turni: indici 1, 3, 5, 7; domanda corrente 9. Si tengono gli ultimi 2 turni completi
    assert summary_cut(messages, keep_turns=2) == 5


def test_cut_nothing_to_compress():
    messages = [SystemMessage("s")] + turn(0) + turn(1) + [HumanMessage("corrente")]
    assert summary_cut(messages, keep_turns=2) == 0
    assert summary_cut([SystemMessage("s"), HumanMessage("corrente")], keep_turns=2) == 0


def test_cut_never_splits_tool_call():
    call = AIMessage("", tool_calls=[{"name": "calc", "args": {"x": 1}, "id": "1"}])
    messages = [
        SystemMessage("s"),
        HumanMessage("d0"), call, ToolMessage("2", name="calc", tool_call_id="1"), AIMessage("r0"),
        *turn(1), *turn(2),
        HumanMessage("corrente"),
    ]
    cut = summary_cut(messages, keep_turns=2)
    assert call in messages[1:cut]
    assert messages[3] in messages[1:cut]


def test_review_feedback_is_not_a_turn():
    messages = [SystemMessage("s"), HumanMessage("q"), AIMessage("bozza"), feedback_message("m."), AIMessage("r")]
    assert turn_starts(messages) == [1]


def test_transcript_lines():
    messages = [
        HumanMessage("ciao, mi chiamo Marco"),
        AIMessage("", tool_calls=[{"name": "add_note", "args": {"text": "x"}, "id": "1"}]),
        ToolMessage("Nota 7 salvata", name="add_note", tool_call_id="1"),
        AIMessage("Ho salvato la nota 7."),
    ]
    assert transcript(messages) == (
        "Utente: ciao, mi chiamo Marco\n"
        "Strumento add_note: Nota 7 salvata\n"
        "Assistente: Ho salvato la nota 7."
    )
    assert transcript(messages[1:2]) == ""


def test_summary_request_with_and_without_previous():
    assert summary_request("", "Utente: ciao") == "Conversazione da riassumere:\nUtente: ciao"
    with_previous = summary_request("R", "Utente: ciao")
    assert "Riassunto delle parti precedenti: R\n" in with_previous
    assert with_previous.index("Riassunto delle parti precedenti: R\n") < with_previous.index("Utente: ciao")


def test_with_summary_extends_system_only_for_call():
    system = SystemMessage("PROMPT")
    messages = [system, HumanMessage("q")]
    result = with_summary(messages, "R")
    assert result[0].content == f"PROMPT\n\n{AGENT_SUMMARY_HEADER}\nR"
    # Con l'intestazione breve l'agente ignorava il nome nel riassunto dopo turni con strumenti (sonda: 1/6 → 6/6)
    assert AGENT_SUMMARY_HEADER.startswith("Riassunto della conversazione precedente (fa parte di questa conversazione")
    assert "nome e città" in AGENT_SUMMARY_HEADER
    assert result[1] is messages[1]
    assert system.content == "PROMPT"
    assert messages[0] is system
    assert with_summary(messages, "") is messages


class FakeModel:
    def model_copy(self, update):
        self.update = update
        return self

    def invoke(self, messages):
        self.invoked = messages
        return AIMessage("Riassunto breve")


def test_build_summarizer_uses_no_reasoning():
    model = FakeModel()
    result = build_summarizer(model)("prima", "Utente: ciao")
    assert model.update == {"reasoning_effort": "none"}
    assert model.invoked == [SystemMessage(SUMMARIZER_INSTRUCTIONS),
                             HumanMessage(summary_request("prima", "Utente: ciao"))]
    assert result == "Riassunto breve"


def test_build_summarizer_returns_string_for_list_content():
    class ListModel(FakeModel):
        def invoke(self, messages):
            return AIMessage(content=[{"type": "text", "text": "R"}])

    assert build_summarizer(ListModel())("", "Utente: ciao") == "R"


def test_summary_line():
    assert summary_line(24, 5, 5200, 1400) == "[riassunto] 24 → 5 messaggi (circa 5200 → 1400 token)"


def test_instructions_name_the_user():
    # Con «Marco, residente a Roma, …» l'agente non collegava il nome all'utente (sonda: 0/3 → 3/3)
    rule = "Riferisciti all'utente sempre come «l'utente»: se conosci nome o città, inizia con «L'utente si chiama"
    assert rule in SUMMARIZER_INSTRUCTIONS
    assert SUMMARIZER_INSTRUCTIONS.index(rule) < SUMMARIZER_INSTRUCTIONS.index("Scrivi solo il riassunto")
