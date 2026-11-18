import dataclasses
import logging

import pytest

from assistant.agent_client import UNAVAILABLE, AgentRequestError, AgentUnavailable
from assistant.cli import clear_screen, run
from assistant.config import load_settings
from assistant.mcp_client import MCPConnectionError, MCPPromptError, PromptArgument, PromptInfo
from assistant.stream_view import INTERRUPTED, THINKING
from tests.fakes import FakeAgent, confirmation, done

BASE = load_settings({"LMSTUDIO_BASE_URL": "http://localhost:1234/v1", "LMSTUDIO_MODEL": "m"})
# Senza ragionamento compare la riga «…sto pensando», usata come riferimento nei test
SETTINGS = dataclasses.replace(BASE, show_reasoning=False)
QUESTION = "Elimino la nota 1 «latte» · senza scadenza? [s/N] "


def inputs(*lines):
    it = iter(lines)

    def input_fn(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return input_fn


def session(agent, *lines, settings=SETTINGS, **kwargs):
    # output_fn e write_fn finiscono nella stessa lista, nell'ordine in cui il terminale li mostrerebbe
    out = []
    code = run(agent, settings, inputs(*lines), out.append, write_fn=out.append, **kwargs)
    return code, out


def user(text):
    return {"ruolo": "utente", "contenuto": text}


def assistant(text):
    return {"ruolo": "assistente", "contenuto": text}


def test_header_shows_model():
    _, out = session(FakeAgent(), "quit", model="m1")
    assert out[0] == "Assistente del laboratorio — modello: m1"


def test_conversation_keeps_history_and_summary():
    agent = FakeAgent([done([user("d1"), assistant("r1")], "R")], [done([user("d1"), assistant("r1")], "R2")])
    session(agent, "d1", "d2", "quit")
    assert agent.payloads[0] == {"messaggi": [user("d1")], "cronologia": [], "riassunto": ""}
    assert agent.payloads[1] == {"messaggi": [user("d2")], "cronologia": [user("d1"), assistant("r1")],
                                 "riassunto": "R"}


def test_clear_resets_history_and_summary():
    agent = FakeAgent([done([user("d1"), assistant("r1")], "R")])
    _, out = session(agent, "d1", "clear", "d2", "quit")
    assert agent.payloads[1] == {"messaggi": [user("d2")], "cronologia": [], "riassunto": ""}
    assert "Cronologia svuotata." in out


def test_clear_clears_screen_and_reprints_header():
    out, cleared = [], []
    run(FakeAgent(), SETTINGS, inputs("d1", "clear", "quit"), out.append, lambda: cleared.append(len(out)),
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
    agent = FakeAgent()
    code, out = session(agent, cmd)
    assert code == 0
    assert "Arrivederci!" in out
    assert agent.payloads == []


def test_help_lists_commands():
    _, out = session(FakeAgent(), "help", "quit")
    text = "\n".join(out)
    for word in ("help", "clear", "quit", "exit", "Ctrl+C"):
        assert word in text


def test_blank_line_ignored():
    agent = FakeAgent()
    session(agent, "", "   ", "quit")
    assert agent.payloads == []


def test_eof_exits_cleanly():
    code, out = session(FakeAgent())
    assert code == 0
    assert out[-1] == "Arrivederci!"


def test_thinking_line_only_without_reasoning():
    _, hidden = session(FakeAgent(), "ciao", "quit", settings=SETTINGS)
    _, shown = session(FakeAgent(), "ciao", "quit", settings=dataclasses.replace(BASE, show_reasoning=True))
    assert THINKING in hidden
    assert THINKING not in shown


def test_events_are_printed_in_order():
    agent = FakeAgent([
        ("ragionamento", {"testo": "penso"}),
        ("strumento", {"nome": "get_current_time", "argomenti": {"timezone": "Asia/Tokyo"}}),
        ("esito_strumento", {"nome": "get_current_time", "contenuto": "22:32", "errore": False}),
        ("risposta", {"testo": "Sono le 22:32."}),
        ("riga", {"testo": "[revisore] ok"}),
        ("riga", {"testo": "⚠ Attenzione: prova"}),
        done([user("ora?"), assistant("Sono le 22:32.")]),
    ])
    _, out = session(agent, "ora?", "quit", settings=dataclasses.replace(BASE, show_reasoning=True))
    text = "".join(out)
    expected = ("[ragionamento]", "penso", '[strumento] get_current_time {"timezone": "Asia/Tokyo"}',
                "[strumento] get_current_time → 22:32", "Sono le 22:32.", "[revisore] ok", "⚠ Attenzione: prova")
    positions = [text.index(s) for s in expected]
    assert positions == sorted(positions)


def test_answer_not_printed_twice():
    agent = FakeAgent([("risposta", {"testo": "risposta unica"}), done([user("ciao"), assistant("risposta unica")])])
    _, out = session(agent, "ciao", "quit")
    assert "".join(out).count("risposta unica") == 1


# --- conferma di eliminazione ---

def confirm_agent():
    return FakeAgent([confirmation((1, QUESTION), suspended={"stato": "s"})],
                     [("risposta", {"testo": "Fatto."}), done([user("elimina"), assistant("Fatto.")])])


def one_question_input(agent, answer, questions):
    """Prima domanda «elimina»; alla conferma risponde `answer`; poi esce."""
    def input_fn(prompt=""):
        if prompt == "> ":
            return "quit" if agent.payloads else "elimina"
        questions.append(prompt)
        if isinstance(answer, type) and issubclass(answer, BaseException):
            raise answer
        return answer

    return input_fn


@pytest.mark.parametrize("answer,expected", [("s", True), ("SI", True), (" sì ", True), ("n", False), ("", False)])
def test_confirmation_resumes_with_decision(answer, expected):
    agent, questions, out = confirm_agent(), [], []
    run(agent, SETTINGS, one_question_input(agent, answer, questions), out.append, write_fn=out.append)
    assert questions == [QUESTION]
    assert agent.payloads[1] == {"ripresa": {"sospeso": {"stato": "s"}, "decisioni": {"1": expected}}}
    assert "Fatto." in out


def test_confirmation_eof_means_no_then_exit():
    agent, questions, out = confirm_agent(), [], []
    code = run(agent, SETTINGS, one_question_input(agent, EOFError, questions), out.append, write_fn=out.append)
    assert code == 0
    assert agent.payloads[1]["ripresa"]["decisioni"] == {"1": False}
    assert out[-1] == "Arrivederci!"


def test_confirmation_ctrl_c_exits_session():
    agent, questions, out = confirm_agent(), [], []
    code = run(agent, SETTINGS, one_question_input(agent, KeyboardInterrupt, questions), out.append,
               write_fn=out.append)
    assert code == 0
    assert out[-1] == "Arrivederci!"
    assert INTERRUPTED not in out
    assert len(agent.payloads) == 1


def test_several_confirmations_are_all_asked():
    agent = FakeAgent([confirmation((1, "uno? "), (2, "due? "))], [done([])])
    answers = iter(["s", "n"])
    asked = []

    def input_fn(prompt=""):
        if prompt == "> ":
            return "quit" if agent.payloads else "elimina tutto"
        asked.append(prompt)
        return next(answers)

    run(agent, SETTINGS, input_fn, lambda *_: None, write_fn=lambda *_: None)
    assert asked == ["uno? ", "due? "]
    assert agent.payloads[1]["ripresa"]["decisioni"] == {"1": True, "2": False}


# --- errori ---

TIMEOUT_TEXT = "Il modello non ha risposto entro 120 secondi. Riprova."


@pytest.mark.parametrize("failure", [
    [("errore", {"codice": "modello_timeout", "messaggio": TIMEOUT_TEXT})],
    AgentRequestError("modello_timeout", TIMEOUT_TEXT),
])
def test_errors_print_message_and_keep_history(failure):
    agent = FakeAgent([done([user("d1"), assistant("r1")])], failure)
    _, out = session(agent, "d1", "fallita", "d3", "quit")
    assert TIMEOUT_TEXT in out
    assert agent.payloads[2]["cronologia"] == [user("d1"), assistant("r1")]


def test_error_after_partial_answer_starts_on_new_line():
    agent = FakeAgent([("risposta", {"testo": "Ecco un po"}), ("errore", {"codice": "x", "messaggio": "boom"})])
    _, out = session(agent, "ciao", "quit")
    i = out.index("Ecco un po")
    assert out[i + 1] == "\n"
    assert out[i + 2] == "boom"


def test_agent_unavailable_keeps_session():
    agent = FakeAgent(AgentUnavailable(UNAVAILABLE))
    _, out = session(agent, "ciao", "seconda", "quit")
    assert "L'agente non risponde: esci e riavvia l'assistente." in out
    assert len(agent.payloads) == 2
    assert out[-1] == "Arrivederci!"


def test_ctrl_c_during_streaming_closes_generator_and_keeps_history():
    agent = FakeAgent([done([user("d1"), assistant("r1")])], [("risposta", {"testo": "Ecco"}), done([])])
    out = []

    def write_fn(text):
        out.append(text)
        if text == "Ecco":
            raise KeyboardInterrupt

    code = run(agent, SETTINGS, inputs("d1", "seconda", "terza", "quit"), out.append, write_fn=write_fn)
    assert code == 0
    assert INTERRUPTED in out
    assert agent.closed == 3  # anche il generatore interrotto è chiuso
    assert agent.payloads[2]["cronologia"] == [user("d1"), assistant("r1")]
    assert out[-1] == "Arrivederci!"


@pytest.mark.parametrize("lines", [(), ("ciao",)])
def test_interrupt_goodbye_on_new_line_posix(lines):
    # Il terminale Linux (Docker) mostra "^C" senza andare a capo: il saluto va sulla riga dopo
    out = []
    run(FakeAgent(), SETTINGS, inputs(*lines), out.append, write_fn=out.append, newline_on_interrupt=True)
    assert out[-2:] == ["", "Arrivederci!"]


def test_interrupt_goodbye_without_blank_line_windows():
    out = []
    run(FakeAgent(), SETTINGS, inputs(), out.append, newline_on_interrupt=False)
    assert out[-2:] != ["", "Arrivederci!"] and out[-1] == "Arrivederci!"


def test_quit_goodbye_without_blank_line():
    out = []
    run(FakeAgent(), SETTINGS, inputs("quit"), out.append, newline_on_interrupt=True)
    assert out[-2] != ""


def test_late_ctrl_c_after_eof_single_goodbye():
    # Su Windows Ctrl+C a input() può dare EOFError e poi un KeyboardInterrupt in ritardo
    out = []

    def output_fn(text):
        out.append(text)
        if text == "Arrivederci!":
            raise KeyboardInterrupt

    assert run(FakeAgent(), SETTINGS, inputs(), output_fn) == 0
    assert out.count("Arrivederci!") == 1


# --- comandi /prompts e /prompt ---

PROMPTS = [
    PromptInfo("spiega", "Spiega un concetto", (
        PromptArgument("argomento", "il concetto", True),
        PromptArgument("livello", "il livello", False))),
    PromptInfo("riassumi_conversazione", "Riassume la conversazione", ()),
]


def prompt_session(agent, *lines, prompts=PROMPTS):
    out = []
    run(agent, SETTINGS, inputs(*lines), out.append, write_fn=out.append, prompt_list=prompts)
    return out


def test_prompts_lists_and_help_mentions_commands():
    out = prompt_session(FakeAgent(), "/prompts", "help", "quit")
    text = "\n".join(out)
    assert "Comandi: help, clear, /prompts, /prompt." in text
    assert "spiega — Spiega un concetto" in text
    assert "  /prompts    elenca i prompt del server" in text
    assert "  /prompt     richiama un prompt: /prompt nome argomento=valore …" in text


def test_prompt_runs_turn_with_prompt_message(caplog):
    agent = FakeAgent()
    with caplog.at_level(logging.INFO, logger="assistant.cli"):
        prompt_session(agent, '/prompt spiega argomento="MCP"', "seconda", "quit")
    assert agent.prompt_calls == [("spiega", {"argomento": "MCP"})]
    assert agent.payloads[0]["messaggi"] == [user("Spiega MCP in breve.")]
    assert "[prompt] spiega" in caplog.text
    assert user("Spiega MCP in breve.") in agent.payloads[1]["cronologia"]


@pytest.mark.parametrize("line,expected", [
    ("/prompt", "Uso: /prompt <nome> argomento=valore …  (elenco con /prompts)"),
    ("/prompt spiega tema=x", "Argomento sconosciuto per spiega: tema (ammessi: argomento, livello)."),
    ("/prompt spiega livello=base", "Argomento obbligatorio mancante per spiega: argomento."),
    ("/prompt nessuno", "Prompt sconosciuto: nessuno. Disponibili: spiega, riassumi_conversazione."),
    ("/promt x", "Comando sconosciuto: /promt. Comandi: help, clear, /prompts, /prompt."),
])
def test_prompt_errors_do_not_call_agent(line, expected):
    agent = FakeAgent()
    out = prompt_session(agent, line, "domanda", "quit")
    assert expected in out
    assert agent.prompt_calls == []
    assert [p["messaggi"] for p in agent.payloads] == [[user("domanda")]]


def test_prompt_rejected_by_server():
    def refuse(name, arguments):
        raise MCPPromptError("argomento vuoto: indica il concetto da spiegare")

    agent = FakeAgent(prompt=refuse)
    out = prompt_session(agent, '/prompt spiega argomento=" "', "quit")
    assert "Il server ha rifiutato il prompt: argomento vuoto: indica il concetto da spiegare" in out
    assert agent.payloads == []


def test_prompt_connection_lost_shows_server_message(caplog):
    def lost(name, arguments):
        raise MCPConnectionError("Il server degli strumenti non risponde: riavvia l'agente.")

    agent = FakeAgent(prompt=lost)
    with caplog.at_level(logging.WARNING, logger="assistant.cli"):
        out = prompt_session(agent, "/prompt spiega argomento=x", "quit")
    assert "Il server degli strumenti non risponde: riavvia l'agente." in out
    assert "[mcp] collegamento con il server perso" in caplog.text
    assert agent.payloads == []


def test_prompt_agent_unavailable():
    def down(name, arguments):
        raise AgentUnavailable(UNAVAILABLE)

    out = prompt_session(FakeAgent(prompt=down), "/prompt spiega argomento=x", "quit")
    assert UNAVAILABLE in out


def test_prompt_without_messages_does_not_start_turn():
    agent = FakeAgent(prompt=[])
    out = prompt_session(agent, "/prompt spiega argomento=x", "quit")
    assert "Il server non ha restituito messaggi per il prompt spiega." in out
    assert agent.payloads == []


def test_prompt_without_prompt_list():
    agent = FakeAgent()
    out = prompt_session(agent, "/prompt spiega argomento=x", "quit", prompts=())
    assert "Nessun prompt disponibile sul server." in out
    assert agent.payloads == []


def test_ctrl_c_during_prompt_turn_keeps_history():
    agent = FakeAgent(KeyboardInterrupt())
    out = prompt_session(agent, "/prompt spiega argomento=x", "seconda", "quit")
    assert INTERRUPTED in out
    assert agent.payloads[1]["cronologia"] == []


def test_prompt_command_case():
    agent = FakeAgent()
    out = prompt_session(agent, "/PROMPTS", "/Prompt spiega argomento=x", "/prompt Spiega argomento=x", "quit")
    assert any(line.startswith("spiega — ") for line in out)
    assert agent.prompt_calls == [("spiega", {"argomento": "x"})]
    assert any(line.startswith("Prompt sconosciuto: Spiega.") for line in out)


def test_prompt_with_several_messages_logs_each_at_debug(caplog):
    messages = [("user", "Primo   testo."), ("assistant", "Secondo testo.")]
    with caplog.at_level(logging.DEBUG, logger="assistant.cli"):
        prompt_session(FakeAgent(prompt=messages), "/prompt riassumi_conversazione", "quit")
    assert "[prompt] 1/2 user: Primo testo." in caplog.text
    assert "[prompt] 2/2 assistant: Secondo testo." in caplog.text


def test_prompt_empty_name_gives_usage():
    agent = FakeAgent()
    out = prompt_session(agent, '/prompt ""', "quit")
    assert "Uso: /prompt <nome> argomento=valore …  (elenco con /prompts)" in out
    assert agent.prompt_calls == []
