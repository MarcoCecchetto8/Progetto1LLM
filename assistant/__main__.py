"""Avvio: python -m assistant."""

import logging
import os
import signal
import sys

from assistant import GOODBYE


def configure_logging(level: str) -> None:
    debug = level == "DEBUG"
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s" if debug else "%(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr, force=True)
    if not debug:
        # "httpx2" è il nome del logger HTTP nell'ambiente installato (verificato con LOG_LEVEL=DEBUG)
        for name in ("httpx", "httpx2", "openai", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)


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
    from assistant.config import ConfigError, load_settings
    from assistant.graph import build_graph
    from assistant.llm import LMStudioUnavailable, ModelNotFound, build_chat_model, check_model
    from assistant.mcp_client import MCPClient, MCPConnectionError, server_command, server_env

    # Con stdout/stderr rediretti Windows può usare cp1252: forza UTF-8 per non rompere "→" e "…"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    load_dotenv()
    try:
        settings = load_settings(os.environ)
        configure_logging(settings.log_level)
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
        except MCPConnectionError as error:
            print(error, file=sys.stderr)
            return 1
        # Il catalogo arriva dal server (discovery), non è scritto nell'assistente
        logging.getLogger("assistant").info("[mcp] catalogo: %s", ", ".join(tool.name for tool in tools))
        graph = build_graph(build_chat_model(settings), tools, settings.max_steps)
        return run(graph, settings)
    finally:
        close_quietly(client)


if __name__ == "__main__":
    raise SystemExit(main())
