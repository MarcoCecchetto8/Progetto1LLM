import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from assistant.cli import clear_screen, run
from assistant.config import load_settings
from assistant.graph import build_graph
from assistant.tools import make_clock_tool
from tests.fakes import fake

REQ = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
SETTINGS = load_settings({"LMSTUDIO_BASE_URL": "http://localhost:1234/v1", "LMSTUDIO_MODEL": "m"})


def bad_request(text):
    return openai.BadRequestError(text, response=httpx.Response(400, request=REQ), body=None)


def inputs(*lines):
    it = iter(lines)

    def input_fn(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return input_fn


class Recorder:
    """Avvolge un grafo e registra gli input passati a invoke."""

    def __init__(self, graph):
        self.graph = graph
        self.calls = []

    def invoke(self, state):
        self.calls.append(state)
        return self.graph.invoke(state)


class Stub:
    """Grafo finto: solleva le eccezioni date, poi risponde 'ok'."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = []

    def invoke(self, state):
        self.calls.append(state)
        if self.errors:
            raise self.errors.pop(0)
        return {"messages": state["messages"] + [AIMessage("ok")]}


def real_graph(*msgs):
    return Recorder(build_graph(fake(*msgs), [make_clock_tool("Europe/Rome")], 5))


def session(graph, *lines):
    out = []
    code = run(graph, SETTINGS, inputs(*lines), out.append)
    return code, out


def test_conversation_keeps_history():
    graph = real_graph(AIMessage("r1"), AIMessage("r2"))
    session(graph, "d1", "d2", "quit")
    second = graph.calls[1]["messages"]
    assert [m.content for m in second[1:]] == ["d1", "r1", "d2"]
    assert graph.calls[1]["steps"] == 0


def test_clear_resets_history():
    graph = real_graph(AIMessage("r1"), AIMessage("r2"))
    _, out = session(graph, "d1", "clear", "d2", "quit")
    messages = graph.calls[1]["messages"]
    assert [type(m) for m in messages] == [SystemMessage, HumanMessage]
    assert messages[1].content == "d2"
    assert "Cronologia svuotata." in out


def test_clear_clears_screen_and_reprints_header():
    out, cleared = [], []
    run(Stub(), SETTINGS, inputs("d1", "clear", "quit"), out.append, lambda: cleared.append(len(out)))
    assert cleared == [4]  # due righe d'intestazione, "…sto pensando", "ok", poi la pulizia
    assert out[4:7] == out[0:2] + ["Cronologia svuotata."]


class FakeStream:
    def __init__(self, tty):
        self.tty = tty
        self.written = ""

    def isatty(self):
        return self.tty

    def write(self, text):
        self.written += text

    def flush(self):
        pass


def test_clear_screen_posix_terminal():
    stream = FakeStream(tty=True)
    clear_screen(stream, windows=False)
    assert stream.written == "\033[2J\033[3J\033[H"


def test_clear_screen_windows_terminal():
    commands = []
    clear_screen(FakeStream(tty=True), windows=True, system=commands.append)
    assert commands == ["cls"]


@pytest.mark.parametrize("windows", [True, False])
def test_clear_screen_not_a_terminal(windows):
    stream, commands = FakeStream(tty=False), []
    clear_screen(stream, windows=windows, system=commands.append)
    assert stream.written == "" and commands == []


@pytest.mark.parametrize("cmd", ["quit", "EXIT", "  Quit  "])
def test_quit_commands(cmd):
    graph = Stub()
    code, out = session(graph, cmd)
    assert code == 0
    assert "Arrivederci!" in out
    assert graph.calls == []


def test_help_lists_commands():
    _, out = session(Stub(), "help", "quit")
    text = "\n".join(out)
    for word in ("help", "clear", "quit", "exit", "Ctrl+C"):
        assert word in text


def test_blank_line_ignored():
    graph = Stub()
    session(graph, "", "   ", "quit")
    assert graph.calls == []


def test_eof_exits_cleanly():
    code, out = session(Stub())
    assert code == 0
    assert out[-1] == "Arrivederci!"


def test_ctrl_c_during_model():
    code, out = session(Stub(KeyboardInterrupt()), "ciao")
    assert code == 0
    assert out[-1] == "Arrivederci!"


def test_late_ctrl_c_after_eof_single_goodbye():
    # Su Windows Ctrl+C a input() può dare EOFError e poi un KeyboardInterrupt in ritardo
    out = []

    def output_fn(text):
        out.append(text)
        if text == "Arrivederci!":
            raise KeyboardInterrupt

    assert run(Stub(), SETTINGS, inputs(), output_fn) == 0
    assert out.count("Arrivederci!") == 1


def test_empty_answer_is_reported_and_not_kept():
    broken = AIMessage("", invalid_tool_calls=[
        {"name": "get_current_time", "args": "{oops", "id": "x", "error": "JSON non valido", "type": "invalid_tool_call"}])
    graph = real_graph(broken, AIMessage("r2"))
    _, out = session(graph, "d1", "d2", "quit")
    assert "Il modello non ha dato una risposta: riprova." in out
    assert [m.content for m in graph.calls[1]["messages"][1:]] == ["d2"]


@pytest.mark.parametrize("exc,expected", [
    (openai.APITimeoutError(request=REQ), "120"),
    (openai.APIConnectionError(request=REQ), "http://localhost:1234/v1"),
    (bad_request("context length exceeded"), "clear"),
    (openai.APIError("exceeds the context window", request=REQ, body=None), "clear"),
    (openai.APIError("server esploso", request=REQ, body=None), "server esploso"),
    (RuntimeError("boom"), "boom"),
])
def test_model_errors_keep_session(exc, expected):
    graph = Stub(exc)
    _, out = session(graph, "fallita", "seconda", "quit")
    assert expected in out[out.index("…sto pensando") + 1]
    assert "ok" in out
    retry = graph.calls[1]["messages"]
    assert [m.content for m in retry[1:]] == ["seconda"]
