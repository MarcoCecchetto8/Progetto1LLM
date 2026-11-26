"""Riscaldamento all'avvio: mette in cache di LM Studio l'inizio fisso dei prompt di agente e router.

La prima domanda dopo l'avvio altrimenti rilegge da zero il prompt dell'agente (istruzioni e strumenti,
circa 2.700 token: ~40 s su questo portatile). Gira in sottofondo e non blocca l'agente.
"""

import logging
import threading
import time
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage

from assistant.graph import with_today

logger = logging.getLogger("agent_service")

WARMUP_TEXT = "ciao"


def warm_up(model, tools: list, system: str, today: Callable[[], str] | None,
            router: Callable[[list, str], object] | None) -> None:
    """Una chiamata con lo stesso inizio di prompt dell'agente (un solo token) e una al router; mai eccezioni."""
    started = time.monotonic()
    try:
        messages = with_today([SystemMessage(system), HumanMessage(WARMUP_TEXT)], today() if today else "")
        model.bind_tools(tools).invoke(messages, max_tokens=1)
        if router:
            router([HumanMessage(WARMUP_TEXT)], "")
    except Exception as error:  # noqa: BLE001 - il riscaldamento non deve mai fermare l'agente
        logger.warning("[riscaldamento] non riuscito (%s): la prima domanda sarà più lenta", error)
        return
    logger.info("[riscaldamento] prompt di agente e router in cache in %.1f s", time.monotonic() - started)


def start_warm_up(*args, **kwargs) -> threading.Thread:
    thread = threading.Thread(target=warm_up, args=args, kwargs=kwargs, name="riscaldamento", daemon=True)
    thread.start()
    return thread
