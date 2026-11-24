"""Streaming SSE di invio e conferma: inoltro degli eventi dell'agente e salvataggio al suo `fine`."""

import asyncio
import json
import logging
import queue
import threading
import time
from collections.abc import AsyncIterator, Callable

from assistant.agent_http import AgentHTTPClient, AgentRequestError, AgentUnavailable
from backend_service.errors import AGENT_DOWN, DB_DOWN, BackendError
from backend_service.schemas import TurnResult
from backend_service.store import StoreUnavailable
from backend_service.turns import ChatTurns, agent_error

logger = logging.getLogger("backend_service")

KEEPALIVE_SECONDS = 0.5
KEEPALIVE = ": \n\n"  # commento SSE: tiene viva la connessione mentre l'agente tace
SSE_MEDIA_TYPE = "text/event-stream; charset=utf-8"


def sse(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error(code: str, message: str) -> tuple[str, dict]:
    return "errore", {"codice": code, "messaggio": message}


def _read_agent(turns: ChatTurns, agent: AgentHTTPClient, chat_id: int, payload: dict, question: str,
                events: queue.Queue, cancelled: threading.Event) -> str:
    """Inoltra gli eventi dell'agente; al `fine` salva qui, nel thread, anche se il client se n'è andato."""
    stream = agent.stream_turn(payload)
    try:
        # Limite strutturale: il thread è fermo dentro l'iteratore dell'agente e vede l'annullamento solo tra
        # un evento e l'altro; nelle fasi silenziose (router, modello prima del primo token, revisore) il turno
        # non si può interrompere prima, e l'agente può arrivare al `fine` con le sue azioni già fatte.
        for name, data in stream:
            if name == "fine":
                # Si salva anche se il client se n'è andato: le azioni del turno sono già avvenute
                result = turns.finish(chat_id, question, data)
                events.put(("fine", TurnResult.model_validate(result).model_dump(mode="json")))
                return result["esito"]
            if cancelled.is_set():
                return "interrotto"  # uscire dal for chiude lo stream verso l'agente, che ferma il turno
            events.put((name, data))
            if name == "errore":
                return data.get("codice", "errore") if isinstance(data, dict) else "errore"
        if cancelled.is_set():
            return "interrotto"
        events.put(_error("agente_non_raggiungibile", AGENT_DOWN))  # stream finito senza fine né errore
        return "agente_non_raggiungibile"
    finally:
        stream.close()


def _worker(turns: ChatTurns, agent: AgentHTTPClient, chat_id: int, payload: dict, question: str,
            release: Callable[[], None], events: queue.Queue, cancelled: threading.Event, label: str) -> None:
    started = time.monotonic()
    outcome = "errore"
    try:
        outcome = _read_agent(turns, agent, chat_id, payload, question, events, cancelled)
    except (AgentUnavailable, AgentRequestError) as error:
        failure = agent_error(error)
        outcome = failure.code
        events.put(_error(failure.code, failure.message))
    except BackendError as error:
        outcome = error.code
        events.put(_error(error.code, error.message))
    except StoreUnavailable as error:
        logger.warning("[backend] database non raggiungibile: %s", error)
        outcome = "database_non_raggiungibile"
        events.put(_error(outcome, DB_DOWN))
    except Exception as error:
        logger.warning("[backend] errore imprevisto: %s", error, exc_info=(type(error), error, error.__traceback__))
        outcome = "errore_imprevisto"
        events.put(_error(outcome, f"Errore imprevisto: {error}. Riprova."))
    finally:
        release()
        events.put(None)  # chiude sempre il generatore asincrono
        logger.info("[backend] %s chat %d: %s in %.1f s", label, chat_id, outcome, time.monotonic() - started)


async def _events(events: queue.Queue, cancelled: threading.Event) -> AsyncIterator[str]:
    last_sent = time.monotonic()
    try:
        while True:
            try:
                item = events.get_nowait()
            except queue.Empty:
                if time.monotonic() - last_sent >= KEEPALIVE_SECONDS:
                    last_sent = time.monotonic()
                    yield KEEPALIVE
                else:
                    await asyncio.sleep(0.05)
                continue
            if item is None:
                return
            last_sent = time.monotonic()
            yield sse(*item)
    finally:
        cancelled.set()  # il client se n'è andato (o lo stream è finito): il thread smette di inoltrare


def stream_turn_events(turns: ChatTurns, agent: AgentHTTPClient, chat_id: int, payload: dict, question: str,
                       release: Callable[[], None], label: str = "stream") -> AsyncIterator[str]:
    """Righe SSE del turno. Il thread parte subito, così `release` arriva anche se lo stream non viene mai letto."""
    events: queue.Queue = queue.Queue()
    cancelled = threading.Event()
    threading.Thread(target=_worker, daemon=True,
                     args=(turns, agent, chat_id, payload, question, release, events, cancelled, label)).start()
    return _events(events, cancelled)
