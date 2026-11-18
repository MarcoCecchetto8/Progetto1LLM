"""Avvio: python -m assistant."""

import logging
import os
import signal
import sys
import warnings

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

    from assistant.agent_client import (START_TIMEOUT, AgentClient, AgentRequestError, AgentUnavailable, LocalAgentService,
                                        wait_until_responds)
    from assistant.cli import run
    from assistant.config import ConfigError, load_settings
    from assistant.mcp_client import MCPConnectionError, MCPPromptError

    # Con stdout/stderr rediretti Windows può usare cp1252: forza UTF-8 per non rompere "→" e "…"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    load_dotenv()
    quiet_library_warnings()
    try:
        settings = load_settings(os.environ)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    configure_logging(settings.log_level)
    log = logging.getLogger("assistant")
    service = None if settings.agent_service_url else LocalAgentService(quiet=settings.log_level != "DEBUG")
    client = None
    # Il finally copre anche un Ctrl+C durante l'attesa di start(): il processo figlio non resta vivo
    try:
        try:
            url = settings.agent_service_url or service.start()
            # Con un agente remoto (Docker) il container può essere avviato ma non ancora in ascolto
            if service is None and not wait_until_responds(url):
                raise AgentUnavailable(f"L'agente non risponde all'indirizzo {url} (atteso {START_TIMEOUT:g} secondi).")
            client = AgentClient(url)
            status = client.status()
            for part in ("modello", "strumenti"):
                if not status[part]["raggiungibile"]:
                    print(status[part]["messaggio"], file=sys.stderr)
                    return 1
            try:
                prompt_list = client.prompts()
            except (MCPPromptError, MCPConnectionError, AgentRequestError) as error:
                log.warning("[mcp] prompt non disponibili (%s): nessun prompt", error)
                prompt_list = []
        except (AgentUnavailable, AgentRequestError) as error:
            print(error, file=sys.stderr)
            return 1
        log.info("[agente] servizio: %s", url)
        log.info("[mcp] prompt: %s", ", ".join(p.name for p in prompt_list) or "nessuno")
        color = sys.stdout.isatty()
        if color and os.name == "nt":
            # Abilita l'elaborazione VT nella console classica; Windows Terminal e VS Code la hanno già
            os.system("")
        return run(client, settings, color=color, model=status["modello"].get("modello", settings.model),
                   prompt_list=prompt_list)
    finally:
        if client is not None:
            close_quietly(client)
        if service is not None:
            close_quietly(service)


if __name__ == "__main__":
    raise SystemExit(main())
