"""API HTTP dell'agente: turno in JSON o in streaming SSE, stato e prompt MCP."""

import asyncio
import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent_service.errors import AgentError, classify
from agent_service.messages import Message, from_langchain, to_langchain
from agent_service.schemas import (
    ErrorBody,
    PromptArgumentOut,
    PromptMessages,
    PromptOut,
    PromptRequest,
    TurnRequest,
    TurnResponse,
)
from agent_service.turn import Suspended, TurnCancelled, TurnOutcome, resume_turn, run_turn
from assistant.config import Settings
from assistant.mcp_client import MCPConnectionError, MCPPromptError, PromptInfo

logger = logging.getLogger("assistant.agent")

ROLES = {"user": "utente", "assistant": "assistente"}
ERRORS = {code: {"model": ErrorBody} for code in (422, 500, 502, 503, 504)}
SSE_MEDIA_TYPE = "text/event-stream; charset=utf-8"


@dataclass
class Agent:
    graph: object
    system: str
    settings: Settings
    list_prompts: Callable[[], list[PromptInfo]]
    get_prompt: Callable[[str, dict[str, str]], list[tuple[str, str]]]
    status: Callable[[], dict]
    lock: threading.Lock = field(default_factory=threading.Lock)


def _suspended(body: TurnRequest) -> Suspended | None:
    if body.ripresa is None:
        return None
    try:
        return Suspended.from_dict(body.ripresa.sospeso)
    except ValueError as error:
        raise AgentError(422, "sospeso_non_valido", str(error)) from None


def _run(agent: Agent, endpoint: str, body: TurnRequest, suspended: Suspended | None, emit=None,
         cancelled=None) -> dict:
    """Esegue il turno (da chiamare con il lock preso), lo registra nei log e restituisce il corpo della risposta."""
    start = time.monotonic()
    try:
        if suspended is not None:
            logger.info("[api] ripresa %s: %d decisioni", endpoint, len(body.ripresa.decisioni))
            outcome = resume_turn(agent.graph, agent.system, suspended, body.ripresa.decisioni, agent.settings,
                                  emit, cancelled)
        else:
            logger.info("[api] turno %s: %d messaggi in cronologia, %d nuovi", endpoint, len(body.cronologia),
                        len(body.messaggi))
            outcome = run_turn(agent.graph, agent.system, to_langchain(body.cronologia), to_langchain(body.messaggi),
                               body.riassunto, agent.settings, emit, cancelled)
        # Anche la conversione sta qui: un suo errore diventa errore_imprevisto, non uno stream troncato
        response = _response(outcome).model_dump(mode="json")
    except TurnCancelled:
        logger.info("[api] turno annullato in %.1f s", time.monotonic() - start)
        raise
    except Exception as exc:
        error = exc if isinstance(exc, AgentError) else classify(exc, agent.settings)
        cause = exc.__cause__ if isinstance(exc, AgentError) else exc
        if error.code == "errore_imprevisto":
            # Senza il traceback un 500 non si può diagnosticare
            logger.warning("[api] %s", error.message, exc_info=cause or exc)
        logger.info("[api] turno %s in %.1f s", error.code, time.monotonic() - start)
        raise error from cause
    for tool in outcome.tools:
        logger.info("[api] strumento %s %s → %s", tool["nome"], tool["argomenti"], tool["esito"])
    logger.info("[api] turno %s in %.1f s", outcome.status, time.monotonic() - start)
    return response


def _response(outcome: TurnOutcome) -> TurnResponse:
    if outcome.suspended is not None:
        return TurnResponse(esito=outcome.status, conferme=outcome.confirmations, sospeso=outcome.suspended.to_dict())
    return TurnResponse(esito=outcome.status, risposta=outcome.answer, strumenti=outcome.tools, righe=outcome.lines,
                        cronologia=from_langchain(outcome.history), riassunto=outcome.summary)


def _sse(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_worker(agent: Agent, body: TurnRequest, suspended: Suspended | None, events: queue.Queue,
                   cancelled: threading.Event) -> None:
    # Il None finale chiude sempre il generatore, anche quando il turno non parte
    try:
        with agent.lock:
            if cancelled.is_set():
                return
            response = _run(agent, "/chat/stream", body, suspended, lambda name, data: events.put((name, data)), cancelled)
        events.put(("fine", response))
    except TurnCancelled:
        pass
    except AgentError as error:
        events.put(("errore", {"codice": error.code, "messaggio": error.message}))
    finally:
        events.put(None)


async def stream_events(agent: Agent, body: TurnRequest, suspended: Suspended | None, cancelled: threading.Event):
    """Righe SSE del turno, eseguito in un thread; chiudere il generatore annulla il turno."""
    events: queue.Queue = queue.Queue()
    threading.Thread(target=_stream_worker, args=(agent, body, suspended, events, cancelled), daemon=True).start()
    try:
        while True:
            try:
                item = events.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if item is None:
                return
            yield _sse(*item)
    finally:
        cancelled.set()


def create_app(agent: Agent) -> FastAPI:
    app = FastAPI(title="Agente del laboratorio")

    @app.exception_handler(AgentError)
    def agent_error_handler(request: Request, exc: AgentError):
        return JSONResponse(status_code=exc.status, content={"codice": exc.code, "messaggio": exc.message})

    # Endpoint sincroni: il turno è bloccante, FastAPI li esegue in un thread
    @app.post("/chat", response_model=TurnResponse, responses=ERRORS)
    def chat(body: TurnRequest):
        """Esegue un turno e restituisce tutto insieme. Con `ripresa` prosegue un turno sospeso."""
        suspended = _suspended(body)
        with agent.lock:
            return _run(agent, "/chat", body, suspended)

    @app.post("/chat/stream", responses={**ERRORS, 200: {"content": {"text/event-stream": {}}}})
    def chat_stream(body: TurnRequest):
        """Stesso turno di /chat, con eventi SSE; gli errori dopo l'inizio arrivano come evento `errore`."""
        suspended = _suspended(body)
        return StreamingResponse(stream_events(agent, body, suspended, threading.Event()),
                                 media_type=SSE_MEDIA_TYPE, headers={"Cache-Control": "no-cache"})

    @app.get("/stato")
    def status():
        """Stato di agente, modello, server degli strumenti e servizio note: 503 se qualcosa non risponde."""
        parts = agent.status()
        code = 200 if all(part["raggiungibile"] for part in parts.values()) else 503
        return JSONResponse(status_code=code, content={"agente": "ok", **parts})

    @app.get("/prompts", response_model=list[PromptOut], responses=ERRORS)
    def prompts():
        try:
            found = agent.list_prompts()
        except (MCPPromptError, MCPConnectionError) as error:
            raise _prompt_error(error) from error
        return [PromptOut(nome=p.name, descrizione=p.description,
                          argomenti=[PromptArgumentOut(nome=a.name, descrizione=a.description, obbligatorio=a.required)
                                     for a in p.arguments])
                for p in found]

    @app.post("/prompts/{nome}", response_model=PromptMessages, responses=ERRORS)
    def prompt(nome: str, body: PromptRequest):
        """Messaggi del prompt compilati dal server MCP."""
        try:
            pairs = agent.get_prompt(nome, body.argomenti)
        except (MCPPromptError, MCPConnectionError) as error:
            raise _prompt_error(error) from error
        return PromptMessages(messaggi=[Message(ruolo=ROLES.get(role, "utente"), contenuto=text)
                                        for role, text in pairs])

    def _prompt_error(error: Exception) -> AgentError:
        if isinstance(error, MCPPromptError):
            return AgentError(422, "prompt_rifiutato", f"Il server ha rifiutato il prompt: {error}")
        return classify(error, agent.settings)

    return app
