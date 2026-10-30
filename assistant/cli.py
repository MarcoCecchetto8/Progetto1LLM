"""Interfaccia da terminale: ciclo della sessione, comandi e messaggi d'errore."""

import logging
import os
import sys

import openai
from langchain_core.messages import HumanMessage, SystemMessage

from assistant import GOODBYE
from assistant.config import Settings
from assistant.graph import system_prompt

HELP_TEXT = (
    "Comandi:\n"
    "  help        mostra questo aiuto\n"
    "  clear       svuota la cronologia e pulisce lo schermo\n"
    "  quit, exit  esci dall'assistente\n"
    "Puoi uscire anche con Ctrl+C (Ctrl+D su Linux/Docker, Ctrl+Z + Invio su Windows)."
)
EMPTY_ANSWER = "Il modello non ha dato una risposta: riprova."

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


def run(graph, settings: Settings, input_fn=input, output_fn=print, clear_fn=clear_screen,
        newline_on_interrupt: bool = os.name != "nt") -> int:
    initial = [SystemMessage(system_prompt(settings.default_timezone))]
    history = list(initial)

    def header():
        output_fn(f"Assistente del laboratorio — modello: {settings.model}")
        output_fn("Scrivi la tua domanda. Comandi: help, clear. Per uscire: quit, exit o Ctrl+C.")

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
                clear_fn()
                header()
                output_fn("Cronologia svuotata.")
                continue
            output_fn("…sto pensando")
            try:
                result = graph.invoke({"messages": history + [HumanMessage(text)], "steps": 0})
            except openai.APIError as error:
                output_fn(error_message(error, settings))
                continue
            except Exception as error:
                logger.debug("Errore imprevisto durante il turno", exc_info=True)
                output_fn(f"Errore imprevisto: {error}. Riprova o usa 'clear'.")
                continue
            answer = result["messages"][-1].content
            if not answer.strip():
                # es. chiamata allo strumento con JSON non valido: il turno non entra in cronologia
                output_fn(EMPTY_ANSWER)
                continue
            history = result["messages"]
            output_fn(answer)
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
