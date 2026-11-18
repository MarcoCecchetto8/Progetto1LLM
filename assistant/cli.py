"""Interfaccia da terminale: ciclo della sessione, comandi e messaggi d'errore."""

import logging
import os
import sys

from assistant import GOODBYE
from assistant.agent_client import AgentRequestError, AgentUnavailable
from assistant.config import Settings
from assistant.mcp_client import MCPConnectionError, MCPPromptError, PromptInfo
from assistant.prompts import (PromptCommandError, format_prompt_list, parse_prompt_command,
                               prompt_log_line, prompt_messages)
from assistant.stream_view import INTERRUPTED, THINKING, TurnView

HELP_TEXT = (
    "Comandi:\n"
    "  help        mostra questo aiuto\n"
    "  clear       svuota la cronologia e pulisce lo schermo\n"
    "  /prompts    elenca i prompt del server\n"
    "  /prompt     richiama un prompt: /prompt nome argomento=valore …\n"
    "  quit, exit  esci dall'assistente\n"
    "Puoi uscire anche con Ctrl+C (Ctrl+D su Linux/Docker, Ctrl+Z + Invio su Windows)."
)
YES = {"s", "si", "sì"}

logger = logging.getLogger("assistant.cli")


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


def write_stdout(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def run(agent, settings: Settings, input_fn=input, output_fn=print, clear_fn=clear_screen,
        newline_on_interrupt: bool = os.name != "nt", write_fn=None, color: bool = False,
        model: str = "", prompt_list: list[PromptInfo] = ()) -> int:
    write_fn = write_fn or write_stdout
    history: list[dict] = []
    summary = ""

    def header():
        output_fn(f"Assistente del laboratorio — modello: {model}")
        output_fn("Scrivi la tua domanda. Comandi: help, clear, /prompts, /prompt. Per uscire: quit, exit o Ctrl+C.")

    def stream(payload: dict, view: TurnView) -> dict | None:
        """Mostra gli eventi del turno; restituisce il corpo di `fine`, None se il turno è finito in errore."""
        events = agent.stream_turn(payload)
        try:
            for name, data in events:
                if name == "ragionamento":
                    view.reasoning(data["testo"])
                elif name == "risposta":
                    view.answer(data["testo"])
                elif name == "strumento":
                    view.tool_call(data["nome"], data["argomenti"])
                elif name == "esito_strumento":
                    view.tool_result(data["nome"], data["contenuto"], data["errore"])
                elif name == "riga":
                    view.extra(data["testo"])
                elif name == "errore":
                    view.finish()
                    output_fn(data["messaggio"])
                    return None
                elif name == "fine":
                    return data
        finally:
            events.close()
            view.finish()
        return None

    def ask(confirmations: list[dict]) -> dict[str, bool]:
        decisions = {}
        for item in confirmations:
            try:
                answer = input_fn(item["domanda"])
            except EOFError:
                decisions[str(item["id_nota"])] = False
                continue
            decisions[str(item["id_nota"])] = answer.strip().casefold() in YES
        return decisions

    def turn(new_messages: list[dict]) -> None:
        nonlocal history, summary
        if not settings.show_reasoning:
            output_fn(THINKING)
        view = TurnView(write_fn, color, settings.show_reasoning)
        payload = {"messaggi": new_messages, "cronologia": history, "riassunto": summary}
        while True:
            try:
                result = stream(payload, view)
            except KeyboardInterrupt:
                output_fn(INTERRUPTED)
                return
            except AgentRequestError as error:
                output_fn(error.message)
                return
            except AgentUnavailable as error:
                output_fn(str(error))
                return
            if result is None:
                return
            if result["esito"] == "completato":
                history, summary = result["cronologia"], result["riassunto"]
                return
            # Turno sospeso: le domande si pongono qui (Ctrl+C a una domanda esce dalla sessione)
            payload = {"ripresa": {"sospeso": result["sospeso"], "decisioni": ask(result["conferme"])}}

    def prompt_command(rest: str):
        """Messaggi del prompt richiamato, o None se il comando non è valido (errore già mostrato)."""
        if not prompt_list:
            output_fn(format_prompt_list([]))
            return None
        try:
            name, arguments = parse_prompt_command(rest, list(prompt_list))
            raw = agent.get_prompt(name, arguments)
        except PromptCommandError as error:
            output_fn(str(error))
            return None
        except MCPPromptError as error:
            output_fn(f"Il server ha rifiutato il prompt: {error}")
            return None
        except MCPConnectionError as error:
            logger.warning("[mcp] collegamento con il server perso: %s", error)
            logger.debug("Dettaglio dell'errore di collegamento", exc_info=True)
            output_fn(str(error))
            return None
        except AgentUnavailable as error:
            output_fn(str(error))
            return None
        except AgentRequestError as error:
            output_fn(error.message)
            return None
        messages = prompt_messages(raw)
        if not messages:
            output_fn(f"Il server non ha restituito messaggi per il prompt {name}.")
            return None
        logger.info(prompt_log_line(name, arguments, raw))
        if len(raw) > 1:
            for number, (role, text) in enumerate(raw, 1):
                logger.debug("[prompt] %d/%d %s: %s", number, len(raw), role, " ".join(text.split()))
        return messages

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
                history = []
                summary = ""
                clear_fn()
                header()
                output_fn("Cronologia svuotata.")
                continue
            if command.startswith("/"):
                token = command.split()[0]
                if token == "/prompts":
                    output_fn(format_prompt_list(list(prompt_list)))
                elif token == "/prompt":
                    messages = prompt_command(text[len("/prompt"):])
                    if messages is not None:
                        turn(messages)
                else:
                    output_fn(f"Comando sconosciuto: {text.split()[0]}. Comandi: help, clear, /prompts, /prompt.")
                continue
            turn([{"ruolo": "utente", "contenuto": text}])
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
