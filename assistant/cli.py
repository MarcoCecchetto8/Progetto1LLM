"""Interfaccia da terminale: ciclo della sessione, comandi e messaggi d'errore."""

import logging
import os
import signal
import sys
import threading
from contextlib import contextmanager

import openai
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage

from assistant import GOODBYE
from assistant.config import Settings
from assistant.graph import system_prompt
from assistant.mcp_client import MCPConnectionError
from assistant.notes import NotesConnectionError, confirmation_pending, reset_confirmation
from assistant.stream_view import INTERRUPTED, THINKING, TurnView, stream_turn
from lab_server.preferences import Preferences

HELP_TEXT = (
    "Comandi:\n"
    "  help        mostra questo aiuto\n"
    "  clear       svuota la cronologia e pulisce lo schermo\n"
    "  quit, exit  esci dall'assistente\n"
    "Puoi uscire anche con Ctrl+C (Ctrl+D su Linux/Docker, Ctrl+Z + Invio su Windows)."
)
EMPTY_ANSWER = "Il modello non ha dato una risposta: riprova."
TOOLS_DOWN = "Il server degli strumenti non risponde: esci e riavvia l'assistente."
NOTES_DOWN = "Il servizio delle note non risponde: esci e riavvia l'assistente."

logger = logging.getLogger("assistant.cli")


def error_message(error: openai.APIError, settings: Settings) -> str:
    # APITimeoutError è figlia di APIConnectionError: va controllata prima
    if isinstance(error, openai.APITimeoutError):
        return f"Il modello non ha risposto entro {settings.timeout:g} secondi. Riprova."
    if isinstance(error, openai.APIConnectionError):
        return f"LM Studio non è raggiungibile all'indirizzo {settings.base_url}. Controlla che sia attivo e riprova."
    if "context" in str(error).lower():
        return "Il contesto del modello è pieno: usa 'clear' per svuotare la cronologia."
    return f"Errore dell'API del modello: {error}"


def clear_screen(stream=None, windows: bool = os.name == "nt", system=os.system) -> None:
    stream = stream or sys.stdout
    # Con l'output rediretto (file, pipe) non c'è uno schermo da pulire
    if not stream.isatty():
        return
    if windows:
        # "cls" funziona anche nella vecchia console, dove le sequenze ANSI possono non essere attive
        system("cls")
    else:
        stream.write("\033[2J\033[3J\033[H")
        stream.flush()


class TurnCancelled(Exception):
    """Ctrl+C durante il turno: ferma il thread del modello."""


class CancelOnInterrupt(BaseCallbackHandler):
    # Senza raise_error LangChain registrerebbe l'eccezione e lascerebbe proseguire il modello
    raise_error = True

    def __init__(self, cancelled: threading.Event):
        self._cancelled = cancelled

    def on_llm_new_token(self, token, **kwargs) -> None:
        if self._cancelled.is_set():
            raise TurnCancelled


@contextmanager
def cancel_on_ctrl_c(cancelled: threading.Event):
    # LangGraph esegue il modello in un thread e all'interruzione ne aspetta la fine:
    # l'Event lo fa fermare al pezzo successivo. Il KeyboardInterrupt resta quello di sempre.
    def handler(signum, frame):
        cancelled.set()
        signal.default_int_handler(signum, frame)

    cancelled.clear()
    try:
        previous = signal.signal(signal.SIGINT, handler)
    except ValueError:  # fuori dal thread principale non si può installare un gestore
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def write_stdout(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def run(graph, settings: Settings, input_fn=input, output_fn=print, clear_fn=clear_screen,
        newline_on_interrupt: bool = os.name != "nt", write_fn=None, color: bool = False,
        preferences: Preferences | None = None) -> int:
    write_fn = write_fn or write_stdout
    preferences = preferences or Preferences("italiano", settings.default_timezone, "sintetico")
    initial = [SystemMessage(system_prompt(preferences))]
    history = list(initial)
    summary = ""

    def header():
        output_fn(f"Assistente del laboratorio — modello: {settings.model}")
        output_fn("Scrivi la tua domanda. Comandi: help, clear. Per uscire: quit, exit o Ctrl+C.")

    cancelled = threading.Event()
    config = {"callbacks": [CancelOnInterrupt(cancelled)]}
    header()
    try:
        while True:
            text = input_fn("> ").strip()
            command = text.lower()
            if not text:
                continue
            if command in ("quit", "exit"):
                break
            if command == "help":
                output_fn(HELP_TEXT)
                continue
            if command == "clear":
                history = list(initial)
                summary = ""
                clear_fn()
                header()
                output_fn("Cronologia svuotata.")
                continue
            reset_confirmation()
            if not settings.show_reasoning:
                output_fn(THINKING)
            view = TurnView(write_fn, color, settings.show_reasoning)
            try:
                with cancel_on_ctrl_c(cancelled):
                    result = stream_turn(graph, {"messages": history + [HumanMessage(text)], "steps": 0,
                                                 "summary": summary}, view, config)
            except KeyboardInterrupt:
                if confirmation_pending():
                    raise  # Ctrl+C alla conferma di eliminazione: si esce come prima
                output_fn(INTERRUPTED)
                continue
            except openai.APIError as error:
                output_fn(error_message(error, settings))
                continue
            except MCPConnectionError as error:
                # Errore di collegamento, distinto da un errore dello strumento (che torna al modello)
                logger.warning("[mcp] collegamento con il server perso: %s", error)
                logger.debug("Dettaglio dell'errore di collegamento", exc_info=True)
                output_fn(TOOLS_DOWN)
                continue
            except NotesConnectionError as error:
                logger.warning("[note] collegamento con il servizio perso: %s", error)
                logger.debug("Dettaglio dell'errore di collegamento", exc_info=True)
                output_fn(NOTES_DOWN)
                continue
            except Exception as error:
                logger.debug("Errore imprevisto durante il turno", exc_info=True)
                output_fn(f"Errore imprevisto: {error}. Riprova o usa 'clear'.")
                continue
            # La risposta è già stata scritta in streaming: qui si controlla solo che non sia vuota
            answer = result["messages"][-1].content
            if not answer.strip():
                # es. chiamata allo strumento con JSON non valido: il turno non entra in cronologia
                output_fn(EMPTY_ANSWER)
                continue
            history = result["messages"]
            summary = result.get("summary", "")
    except (EOFError, KeyboardInterrupt):
        # Su Linux (anche in Docker) il terminale scrive "^C" senza andare a capo
        if newline_on_interrupt:
            output_fn("")
    try:
        output_fn(GOODBYE)
    except KeyboardInterrupt:
        # Su Windows un Ctrl+C a input() può arrivare in ritardo, dopo l'EOFError
        pass
    return 0
