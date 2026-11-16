import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from assistant.graph import LIMIT_MESSAGE, build_graph
from assistant.llm import REASONING_KEY
from assistant.router import REFUSAL, Route
from assistant.stream_view import TurnView, stream_turn
from tests.fakes import FakeStreamGraph, fake, fake_clock, tool_call

DIM, RESET = "\x1b[2m", "\x1b[0m"


def make_view(color=False, show_reasoning=True):
    out = []
    return TurnView(out.append, color, show_reasoning), out


def r_chunk(text):
    return ("messages", (AIMessageChunk("", additional_kwargs={REASONING_KEY: text}),
                         {"langgraph_node": "model"}))


def a_chunk(text):
    return ("messages", (AIMessageChunk(text), {"langgraph_node": "model"}))


def test_reasoning_then_answer_plain():
    view, out = make_view()
    view.reasoning("Pen")
    view.reasoning("so.")
    view.answer("Ciao")
    view.answer("!")
    view.finish()
    text = "".join(out)
    # Senza colori la risposta ha un'intestazione propria, altrimenti si confonde col ragionamento
    assert text == "[ragionamento]\nPenso.\n[risposta]\nCiao!\n"
    assert "\x1b" not in text


def test_answer_without_reasoning_has_no_header():
    view, out = make_view()
    view.answer("Ciao!")
    view.finish()
    assert "".join(out) == "Ciao!\n"


def test_reasoning_dimmed_with_color():
    view, out = make_view(color=True)
    view.reasoning("Pen")
    view.reasoning("so.")
    view.answer("Ciao")
    view.finish()
    assert "".join(out) == (f"{DIM}[ragionamento]\n{RESET}{DIM}Pen{RESET}{DIM}so.{RESET}"
                            "\nCiao\n")


def test_reasoning_hidden():
    view, out = make_view(show_reasoning=False)
    view.reasoning("Penso")
    view.answer("Ciao!")
    view.finish()
    assert "".join(out) == "Ciao!\n"


def test_tool_lines():
    view, out = make_view()
    view.reasoning("Penso")
    view.tool_call("get_current_time", {"timezone": "Asia/Tokyo"})
    view.tool_result("get_current_time", "Asia/Tokyo: 22:32", False)
    view.tool_result("add_note", "Errore: x", True)
    view.finish()
    assert "".join(out) == (
        "[ragionamento]\nPenso\n"
        '[strumento] get_current_time {"timezone": "Asia/Tokyo"}\n'
        "[strumento] get_current_time → Asia/Tokyo: 22:32\n"
        "[strumento] add_note errore → Errore: x\n")


def test_stream_turn_order():
    view, out = make_view()
    call = AIMessage("", tool_calls=[{"name": "get_current_time",
                                      "args": {"timezone": "Asia/Tokyo"}, "id": "1"}])
    result = ToolMessage("Asia/Tokyo: 22:32", name="get_current_time", tool_call_id="1")
    final = {"messages": ["fine"]}
    graph = FakeStreamGraph([
        r_chunk("Penso"), r_chunk("."),
        ("updates", {"model": {"messages": [call]}}),
        ("messages", (result, {"langgraph_node": "tools"})),
        ("updates", {"tools": {"messages": [result]}}),
        a_chunk("Sono "), a_chunk("le 22:32"),
        ("updates", {"model": {"messages": [AIMessage("Sono le 22:32")]}}),
    ], final)
    assert stream_turn(graph, {}, view) == final
    assert "".join(out) == (
        "[ragionamento]\nPenso.\n"
        '[strumento] get_current_time {"timezone": "Asia/Tokyo"}\n'
        "[strumento] get_current_time → Asia/Tokyo: 22:32\n"
        "Sono le 22:32\n")


def test_stream_turn_answer_without_chunks():
    view, out = make_view()
    graph = FakeStreamGraph([("updates", {"model": {"messages": [AIMessage("ok")]}})], {})
    stream_turn(graph, {}, view)
    assert "".join(out) == "ok\n"


def test_stream_turn_warning_once():
    view, out = make_view()
    warn = "Ho salvato la nota.\n\n⚠ Attenzione: non risulta salvata."
    graph = FakeStreamGraph([
        a_chunk("Ho salvato la nota."),
        ("updates", {"model": {"messages": [AIMessage("Ho salvato la nota.")]}}),
        ("updates", {"answer_check": {"messages": [AIMessage(warn)]}}),
    ], {})
    stream_turn(graph, {}, view)
    assert "".join(out) == "Ho salvato la nota.\n⚠ Attenzione: non risulta salvata.\n"


def test_stream_turn_step_limit():
    view, out = make_view()
    graph = FakeStreamGraph(
        [("updates", {"step_limit": {"messages": [AIMessage(LIMIT_MESSAGE)]}})], {})
    stream_turn(graph, {}, view)
    assert "".join(out) == LIMIT_MESSAGE + "\n"


def test_stream_turn_finishes_line_on_error():
    class Boom:
        def stream(self, state, config=None, stream_mode=None):
            yield a_chunk("Ciao")
            raise RuntimeError("giù")

    view, out = make_view()
    with pytest.raises(RuntimeError):
        stream_turn(Boom(), {}, view)
    assert "".join(out) == "Ciao\n"


def test_stream_turn_with_real_graph():
    def build():
        return build_graph(fake(tool_call({"timezone": "Asia/Tokyo"}, "1"),
                                AIMessage("Sono le 14:32")), [fake_clock], 5)

    state = {"messages": [HumanMessage("che ore sono a Tokyo?")], "steps": 0}
    view, out = make_view()
    final = stream_turn(build(), state, view)
    text = "".join(out)
    assert '[strumento] get_current_time {"timezone": "Asia/Tokyo"}\n' in text
    assert "[strumento] get_current_time → Asia/Tokyo: 2026-10-26T22:32:05+09:00\n" in text
    assert text.count("Sono le 14:32") == 1
    expected = build().invoke(state)
    assert [(type(m), m.content) for m in final["messages"]] == \
           [(type(m), m.content) for m in expected["messages"]]


def test_stream_turn_refusal_printed_once():
    view, out = make_view()
    refusal = REFUSAL.format(motivo="cucina")
    graph = FakeStreamGraph([
        ("messages", (AIMessageChunk("testo del router"), {"langgraph_node": "router"})),
        ("updates", {"router": {"route": "fuori_ambito"}}),
        ("updates", {"refusal": {"messages": [AIMessage(refusal)]}}),
    ], {})
    stream_turn(graph, {}, view)
    text = "".join(out)
    assert text == refusal + "\n"
    assert "testo del router" not in text


def test_stream_turn_with_real_graph_refusal():
    router = lambda messages: Route(categoria="fuori_ambito", motivo="cucina")
    graph = build_graph(fake(AIMessage("non deve comparire")), [fake_clock], 5, router=router)
    view, out = make_view()
    stream_turn(graph, {"messages": [HumanMessage("carbonara?")], "steps": 0}, view)
    text = "".join(out)
    assert REFUSAL.format(motivo="cucina") in text
    assert "non deve comparire" not in text


def test_stream_turn_review_lines():
    from assistant.reviewer import Review
    verdicts = iter([Review(coerente=False, motivo="manca il calcolo."), Review(coerente=True, motivo="ok")])
    graph = build_graph(fake(AIMessage("bozza"), AIMessage("risposta completa")), [fake_clock], 5,
                        reviewer=lambda q, a: next(verdicts))
    view, out = make_view()
    stream_turn(graph, {"messages": [HumanMessage("q")], "steps": 0}, view)
    text = "".join(out)
    order = ["bozza", "[revisore] non coerente: manca il calcolo. → nuova risposta", "risposta completa",
             "[revisore] coerente"]
    positions = [text.index(s) for s in order]
    assert positions == sorted(positions) and all(text.count(s) == 1 for s in order)
    assert text.count("\n[revisore] non coerente") == 1
