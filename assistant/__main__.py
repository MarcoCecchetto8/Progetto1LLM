"""Avvio: python -m assistant."""

import logging
import os
import signal
import sys
import warnings
from pathlib import Path

from assistant import GOODBYE


def configure_logging(level: str) -> None:
    debug = level == "DEBUG"
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s" if debug else "%(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr, force=True)
    if not debug:
        # "httpx2" è il nome del logger HTTP nell'ambiente installato (verificato con LOG_LEVEL=DEBUG)
        for name in ("httpx", "httpx2", "openai", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)


def quiet_library_warnings() -> None:
    # Con l'output strutturato langchain-openai fa emettere a pydantic un avviso innocuo a ogni chiamata
    # (campo "parsed"): sporcherebbe il terminale a ogni domanda (router e revisore)
    warnings.filterwarnings("ignore", message="Pydantic serializer warnings", category=UserWarning)


def close_quietly(client) -> None:
    # Un Ctrl+C in ritardo (Windows) dopo il saluto non deve interrompere la chiusura del server né ripetere il saluto
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    client.close()


def main(start=None, output_fn=print) -> int:
    try:
        return (start or _start)()
    except KeyboardInterrupt:
        output_fn(GOODBYE)
        return 0
    finally:
        # Un Ctrl+C in ritardo (Windows) dopo il saluto non deve produrre un traceback
        signal.signal(signal.SIGINT, signal.SIG_IGN)


def _start() -> int:
    # Librerie caricate qui, dentro main(): un Ctrl+C durante i secondi di caricamento dà il saluto
    from dotenv import load_dotenv

    from assistant.cli import run
    from assistant.config import ConfigError, load_scope, load_settings
    from assistant.graph import build_graph
    from assistant.reviewer import build_reviewer
    from assistant.router import build_router
    from assistant.summarizer import build_summarizer
    from assistant.llm import LMStudioUnavailable, ModelNotFound, build_chat_model, check_model
    from datetime import datetime

    import httpx

    from assistant.preferences import load_preferences
    from assistant.mcp_client import (MCPClient, MCPConnectionError, MCPPromptError, server_command, server_env)
    from assistant.notes import (LocalNotesService, NotesConnectionError, TIMEOUT, ask_in_terminal,
                                 build_note_tools, check_note_claims, wait_until_ready)
    from lab_server.timezones import get_timezone

    # Con stdout/stderr rediretti Windows può usare cp1252: forza UTF-8 per non rompere "→" e "…"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    load_dotenv()
    quiet_library_warnings()
    try:
        settings = load_settings(os.environ)
        root = Path(__file__).resolve().parent.parent
        scope = load_scope(settings.scope_file, root)
        configure_logging(settings.log_level)
        logging.getLogger("assistant").info(
            "[router] ambito: %s (%d righe)", settings.scope_file, len(scope.splitlines()))
        check_model(settings)
    except (ConfigError, LMStudioUnavailable, ModelNotFound) as error:
        print(error, file=sys.stderr)
        return 1
    client = MCPClient(server_command(), server_env(settings))
    try:
        try:
            tools = client.start()
            if not tools:
                raise MCPConnectionError("Il server degli strumenti non espone nessuno strumento.")
            # Il catalogo arriva dal server (discovery), non è scritto nell'assistente
            logging.getLogger("assistant").info("[mcp] catalogo: %s", ", ".join(tool.name for tool in tools))
            # Letta una volta, prima della prima domanda; un collegamento caduto è l'errore di sempre
            preferences = load_preferences(client.read_resource, settings.default_timezone)
            try:
                prompt_list = client.list_prompts()
            except MCPPromptError as error:
                logging.getLogger("assistant").warning("[mcp] prompt non disponibili (%s): nessun prompt", error)
                prompt_list = []
            logging.getLogger("assistant").info(
                "[mcp] prompt: %s", ", ".join(p.name for p in prompt_list) or "nessuno")
        except MCPConnectionError as error:
            print(error, file=sys.stderr)
            return 1
        service = None if settings.notes_service_url else LocalNotesService(quiet=settings.log_level != "DEBUG")
        http = None
        try:
            try:
                url = settings.notes_service_url or service.start()
                if service is None:
                    wait_until_ready(url)
            except NotesConnectionError as error:
                print(error, file=sys.stderr)
                return 1
            http = httpx.Client(base_url=url, timeout=TIMEOUT)
            logging.getLogger("assistant").info("[note] servizio: %s", url)
            zone = get_timezone(preferences.fuso_orario)
            tools = tools + build_note_tools(http, lambda: datetime.now(zone).date(), ask_in_terminal)
            model = build_chat_model(settings)
            graph = build_graph(model, tools, settings.max_steps, answer_check=check_note_claims,
                                router=build_router(model, scope), reviewer=build_reviewer(model),
                                max_reviews=settings.max_reviews, summarizer=build_summarizer(model),
                                summary_threshold=settings.summary_threshold,
                                summary_keep_turns=settings.summary_keep_turns)
            logging.getLogger("assistant").info("[revisore] limite: %d revisioni", settings.max_reviews)
            logging.getLogger("assistant").info(
                "[riassunto] soglia: %d token stimati, turni conservati: %d",
                settings.summary_threshold, settings.summary_keep_turns)
            color = sys.stdout.isatty()
            if color and os.name == "nt":
                # Abilita l'elaborazione VT nella console classica; Windows Terminal e VS Code la hanno già
                os.system("")
            return run(graph, settings, color=color, preferences=preferences,
                       prompt_list=prompt_list, get_prompt=client.get_prompt)
        finally:
            if http is not None:
                close_quietly(http)
            if service is not None:
                close_quietly(service)
    finally:
        close_quietly(client)


if __name__ == "__main__":
    raise SystemExit(main())
