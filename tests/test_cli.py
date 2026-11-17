import _thread
import dataclasses
import logging
import threading
import time

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGenerationChunk

from assistant.cli import TOOLS_DOWN, clear_screen, run
from assistant.config import load_settings
from assistant.stream_view import INTERRUPTED, THINKING
from assistant.graph import build_graph, system_prompt
from assistant.mcp_client import MCPConnectionError
from lab_server.preferences import Preferences
from tests.fakes import FakeToolModel, fake, fake_clock

REQ = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
BASE = load_settings({"LMSTUDIO_BASE_URL": "http://localhost:1234/v1", "LMSTUDIO_MODEL": "m"})
# Senza ragionamento compare la riga «…sto pensando», usata come riferimento nei test
SETTINGS = dataclasses.replace(BASE, show_reasoning=False)


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

    def stream(self, state, config=None, stream_mode=None):
        self.calls.append(state)
        return self.graph.stream(state, config, stream_mode=stream_mode)


class Stub:
    """Grafo finto: solleva le eccezioni date, poi risponde 'ok'."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = []

    def stream(self, state, config=None, stream_mode=None):
        self.calls.append(state)
        if self.errors:
            raise self.errors.pop(0)
        reply = AIMessage("ok")
        yield ("updates", {"model": {"messages": [reply]}})
        yield ("values", {"messages": state["messages"] + [reply]})


def real_graph(*msgs):
    return Recorder(build_graph(fake(*msgs), [fake_clock], 5))


def session(graph, *lines, settings=SETTINGS):
    # output_fn e write_fn finiscono nella stessa lista, nell'ordine in cui il terminale li mostrerebbe
    out = []
    code = run(graph, settings, inputs(*lines), out.append, write_fn=out.append)
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


def test_run_uses_given_preferences_also_after_clear():
    prefs = Preferences("inglese", "America/New_York", "dettagliato")
    graph = real_graph(AIMessage("r1"), AIMessage("r2"))
    run(graph, SETTINGS, inputs("d1", "clear", "d2", "quit"), lambda *_: None, write_fn=lambda *_: None,
        preferences=prefs)
    expected = system_prompt(prefs)
    assert expected.startswith("Preferenze dell'utente (dalla resource utente://preferenze):\n- Rispondi sempre in inglese.\n")
    assert graph.calls[0]["messages"][0].content == expected
    assert graph.calls[1]["messages"][0].content == expected


def test_run_default_preferences_from_settings():
    graph = real_graph(AIMessage("r1"))
    session(graph, "d1", "quit")
    expected = system_prompt(Preferences("italiano", SETTINGS.default_timezone, "sintetico"))
    assert graph.calls[0]["messages"][0].content == expected


def test_clear_clears_screen_and_reprints_header():
    out, cleared = [], []
    run(Stub(), SETTINGS, inputs("d1", "clear", "quit"), out.append, lambda: cleared.append(len(out)),
        write_fn=lambda text: None)
    assert cleared == [3]  # due righe d'intestazione, "…sto pensando", poi la pulizia
    assert out[3:6] == out[0:2] + ["Cronologia svuotata."]


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
    graph = Stub(KeyboardInterrupt())
    code, out = session(graph, "ciao", "seconda", "quit")
    assert code == 0
    assert INTERRUPTED in out
    assert out[-1] == "Arrivederci!"
    assert [m.content for m in graph.calls[1]["messages"][1:]] == ["seconda"]


def test_ctrl_c_at_confirmation_exits():
    from assistant.notes import ask_in_terminal, reset_confirmation

    def interrupted(prompt=""):
        raise KeyboardInterrupt

    class Asking:
        def stream(self, state, config=None, stream_mode=None):
            ask_in_terminal("?", interrupted)
            raise KeyboardInterrupt
            yield

    reset_confirmation()
    try:
        code, out = session(Asking(), "elimina", "quit")
    finally:
        reset_confirmation()
    assert code == 0
    assert out[-1] == "Arrivederci!"
    assert INTERRUPTED not in out


def test_thinking_line_only_without_reasoning():
    _, hidden = session(Stub(), "ciao", "quit", settings=SETTINGS)
    _, shown = session(Stub(), "ciao", "quit", settings=dataclasses.replace(BASE, show_reasoning=True))
    assert THINKING in hidden
    assert THINKING not in shown


class Partial:
    def __init__(self, error):
        self.error = error
        self.calls = []

    def stream(self, state, config=None, stream_mode=None):
        self.calls.append(state)
        if len(self.calls) == 1:
            yield ("messages", (AIMessageChunk("Ecco un po"), {"langgraph_node": "model"}))
            raise self.error
        reply = AIMessage("ok")
        yield ("values", {"messages": state["messages"] + [reply]})


def test_error_after_partial_answer():
    graph = Partial(openai.APITimeoutError(request=REQ))
    _, out = session(graph, "ciao", "seconda", "quit")
    i = out.index("Ecco un po")
    assert out[i + 1] == "\n"
    assert "120" in out[i + 2]
    assert [m.content for m in graph.calls[1]["messages"][1:]] == ["seconda"]


def test_answer_not_printed_twice():
    _, out = session(real_graph(AIMessage("risposta unica")), "ciao", "quit")
    assert "".join(out).count("risposta unica") == 1


@pytest.mark.parametrize("graph,lines", [(Stub(), ()), (Stub(KeyboardInterrupt()), ("ciao",))])
def test_interrupt_goodbye_on_new_line_posix(graph, lines):
    # Il terminale Linux (Docker) mostra "^C" senza andare a capo: il saluto va sulla riga dopo
    out = []
    run(graph, SETTINGS, inputs(*lines), out.append, newline_on_interrupt=True)
    assert out[-2:] == ["", "Arrivederci!"]


def test_interrupt_goodbye_without_blank_line_windows():
    out = []
    run(Stub(), SETTINGS, inputs(), out.append, newline_on_interrupt=False)
    assert out[-2:] != ["", "Arrivederci!"] and out[-1] == "Arrivederci!"


def test_quit_goodbye_without_blank_line():
    out = []
    run(Stub(), SETTINGS, inputs("quit"), out.append, newline_on_interrupt=True)
    assert out[-2] != ""


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


def test_tools_down_keeps_session():
    graph = Stub(MCPConnectionError("Il server degli strumenti non risponde: Connection closed"))
    _, out = session(graph, "che ora è?", "seconda", "quit")
    assert out[out.index("…sto pensando") + 1] == TOOLS_DOWN
    assert "ok" in out
    assert [m.content for m in graph.calls[1]["messages"][1:]] == ["seconda"]


def test_tools_down_is_logged(caplog):
    graph = Stub(MCPConnectionError("Il server degli strumenti non risponde: Connection closed"))
    with caplog.at_level(logging.WARNING, logger="assistant.cli"):
        session(graph, "che ora è?", "quit")
    assert "[mcp] collegamento con il server perso: Il server degli strumenti non risponde: Connection closed" in caplog.text


def test_notes_down_keeps_session():
    from assistant.cli import NOTES_DOWN
    from assistant.notes import NotesConnectionError

    graph = Stub(NotesConnectionError("Il servizio delle note non risponde: x"))
    _, out = session(graph, "ricorda latte", "seconda", "quit")
    assert out[out.index("…sto pensando") + 1] == NOTES_DOWN
    assert [m.content for m in graph.calls[1]["messages"][1:]] == ["seconda"]


class SlowModel(FakeToolModel):
    """Modello finto lento: una risposta che comincia con «lento» esce a pezzi, 0,1 s l'uno."""

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for chunk in super()._stream(messages, stop, run_manager, **kwargs):
            text = chunk.message.content
            if not text.startswith("lento"):
                yield chunk
                continue
            for piece in text:
                time.sleep(0.1)
                SLOW_PIECES.append(piece)
                yield ChatGenerationChunk(message=AIMessageChunk(piece))


SLOW_PIECES = []


def test_ctrl_c_stops_the_model_thread():
    # Grafo vero: LangGraph esegue il modello in un thread e, senza fermarlo, ne aspetta la fine
    SLOW_PIECES.clear()
    model = SlowModel(messages=iter([AIMessage("lento" + "." * 25), AIMessage("r2")]))
    graph = Recorder(build_graph(model, [fake_clock], 5))
    timer = threading.Timer(0.5, _thread.interrupt_main)
    start = time.monotonic()
    timer.start()
    try:
        _, out = session(graph, "ciao", "seconda", "quit")
    finally:
        timer.cancel()
    elapsed = time.monotonic() - start
    print(f"durata della sessione interrotta: {elapsed:.2f} s")
    assert elapsed < 1.5
    assert INTERRUPTED in out
    assert [m.content for m in graph.calls[1]["messages"][1:]] == ["seconda"]
    assert out[-1] == "Arrivederci!"
    # Il thread del modello non continua a generare dopo l'interruzione
    emitted = len(SLOW_PIECES)
    time.sleep(0.3)
    assert len(SLOW_PIECES) == emitted < 30


class SummaryGraph:
    """Grafo finto: registra lo stato ricevuto e restituisce un riassunto a ogni turno riuscito."""

    def __init__(self, *summaries, fail_on=None):
        self.summaries = list(summaries)
        self.fail_on = fail_on or {}
        self.calls = []

    def stream(self, state, config=None, stream_mode=None):
        n = len(self.calls)
        self.calls.append(state)
        if n in self.fail_on:
            if self.fail_on[n] == "empty":
                yield ("values", {"messages": state["messages"] + [AIMessage("")], "summary": "SCARTATO"})
                return
            raise self.fail_on[n]
        reply = AIMessage("ok")
        yield ("updates", {"model": {"messages": [reply]}})
        yield ("values", {"messages": state["messages"] + [reply], "summary": self.summaries.pop(0)})


def test_summary_carried_to_next_turn():
    graph = SummaryGraph("R", "R2")
    session(graph, "d1", "d2", "quit")
    assert graph.calls[0]["summary"] == ""
    assert graph.calls[1]["summary"] == "R"


def test_clear_resets_summary():
    graph = SummaryGraph("R", "R2")
    session(graph, "d1", "clear", "d2", "quit")
    assert graph.calls[1]["summary"] == ""


@pytest.mark.parametrize("failure", [openai.APIError("boom", request=REQ, body=None), "empty"])
def test_failed_turn_keeps_summary(failure):
    graph = SummaryGraph("R", "R3", fail_on={1: failure})
    session(graph, "d1", "d2", "d3", "quit")
    assert graph.calls[1]["summary"] == "R"
    assert graph.calls[2]["summary"] == "R"


# --- comandi /prompts e /prompt ---

from assistant.mcp_client import MCPPromptError, PromptArgument, PromptInfo

PROMPTS = [
    PromptInfo("spiega", "Spiega un concetto", (
        PromptArgument("argomento", "il concetto", True),
        PromptArgument("livello", "il livello", False))),
    PromptInfo("riassumi_conversazione", "Riassume la conversazione", ()),
]


def prompt_session(graph, *lines, get_prompt=None, prompts=PROMPTS):
    out = []
    run(graph, SETTINGS, inputs(*lines), out.append, write_fn=out.append,
        prompt_list=prompts, get_prompt=get_prompt)
    return out


def fake_get_prompt(calls=None, messages=None):
    def get_prompt(name, arguments):
        if calls is not None:
            calls.append((name, arguments))
        return messages if messages is not None else [("user", "Spiega MCP in breve.")]

    return get_prompt


def test_prompts_lists_and_help_mentions_commands():
    out = prompt_session(Stub(), "/prompts", "help", "quit", get_prompt=fake_get_prompt())
    text = "\n".join(out)
    assert "spiega — Spiega un concetto" in text
    assert "  /prompts    elenca i prompt del server" in text
    assert "  /prompt     richiama un prompt: /prompt nome argomento=valore …" in text


def test_prompt_runs_turn_with_prompt_message(caplog):
    graph, calls = Stub(), []
    with caplog.at_level(logging.INFO, logger="assistant.cli"):
        prompt_session(graph, '/prompt spiega argomento="MCP"', "seconda", "quit",
                       get_prompt=fake_get_prompt(calls))
    assert calls == [("spiega", {"argomento": "MCP"})]
    first = graph.calls[0]["messages"]
    assert [m.content for m in first[1:]] == ["Spiega MCP in breve."]
    assert isinstance(first[-1], HumanMessage)
    assert "[prompt] spiega" in caplog.text
    assert "Spiega MCP in breve." in [m.content for m in graph.calls[1]["messages"]]


@pytest.mark.parametrize("line,expected", [
    ("/prompt", "Uso: /prompt <nome> argomento=valore …  (elenco con /prompts)"),
    ("/prompt spiega tema=x", "Argomento sconosciuto per spiega: tema (ammessi: argomento, livello)."),
    ("/prompt spiega livello=base", "Argomento obbligatorio mancante per spiega: argomento."),
    ("/prompt nessuno", "Prompt sconosciuto: nessuno. Disponibili: spiega, riassumi_conversazione."),
    ("/promt x", "Comando sconosciuto: /promt. Comandi: help, clear, /prompts, /prompt."),
])
def test_prompt_errors_do_not_call_graph(line, expected):
    graph, calls = Stub(), []
    out = prompt_session(graph, line, "domanda", "quit", get_prompt=fake_get_prompt(calls))
    assert expected in out
    assert calls == []
    assert len(graph.calls) == 1
    assert [m.content for m in graph.calls[0]["messages"][1:]] == ["domanda"]


def test_prompt_rejected_by_server():
    graph = Stub()

    def get_prompt(name, arguments):
        raise MCPPromptError("argomento vuoto: indica il concetto da spiegare")

    out = prompt_session(graph, '/prompt spiega argomento=" "', "quit", get_prompt=get_prompt)
    assert "Il server ha rifiutato il prompt: argomento vuoto: indica il concetto da spiegare" in out
    assert graph.calls == []


def test_prompt_connection_lost():
    graph = Stub()

    def get_prompt(name, arguments):
        raise MCPConnectionError("perso")

    out = prompt_session(graph, "/prompt spiega argomento=x", "quit", get_prompt=get_prompt)
    assert TOOLS_DOWN in out
    assert graph.calls == []


def test_prompt_without_messages_does_not_call_graph():
    graph = Stub()
    out = prompt_session(graph, "/prompt spiega argomento=x", "quit",
                         get_prompt=fake_get_prompt(messages=[]))
    assert "Il server non ha restituito messaggi per il prompt spiega." in out
    assert graph.calls == []


def test_prompt_without_get_prompt():
    graph = Stub()
    out = prompt_session(graph, "/prompt spiega argomento=x", "quit", prompts=())
    assert "Nessun prompt disponibile sul server." in out
    assert graph.calls == []


def test_ctrl_c_during_prompt_turn_keeps_history():
    graph = Stub(KeyboardInterrupt())
    out = prompt_session(graph, "/prompt spiega argomento=x", "seconda", "quit",
                         get_prompt=fake_get_prompt())
    assert INTERRUPTED in out
    assert [m.content for m in graph.calls[1]["messages"][1:]] == ["seconda"]


def test_prompt_command_case():
    graph, calls = Stub(), []
    out = prompt_session(graph, "/PROMPTS", "/Prompt spiega argomento=x", "/prompt Spiega argomento=x",
                         "quit", get_prompt=fake_get_prompt(calls))
    assert any(line.startswith("spiega — ") for line in out)
    assert calls == [("spiega", {"argomento": "x"})]
    assert any(line.startswith("Prompt sconosciuto: Spiega.") for line in out)
