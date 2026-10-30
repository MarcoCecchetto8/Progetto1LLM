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
    from assistant.tools import make_clock_tool

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
    graph = build_graph(build_chat_model(settings), [make_clock_tool(settings.default_timezone)], settings.max_steps)
    return run(graph, settings)


if __name__ == "__main__":
    raise SystemExit(main())
