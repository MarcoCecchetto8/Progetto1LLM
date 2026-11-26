"""Costruzione dell'agente: configurazione, server MCP, preferenze, servizio note e grafo."""

import logging
from collections.abc import Callable
from contextlib import ExitStack
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import httpx

from agent_service.app import Agent
from agent_service.errors import NOTES_DOWN, TOOLS_DOWN, model_unreachable
from agent_service.warmup import start_warm_up
from assistant.config import Settings, load_scope
from assistant.graph import build_graph, system_prompt, today_line
from assistant.llm import LMStudioUnavailable, ModelNotFound, build_chat_model, list_models
from assistant.mcp_client import MCPClient, MCPConnectionError, MCPPromptError, server_command, server_env
from assistant.notes import (TIMEOUT, LocalNotesService, _responds, build_confirmation_check, build_note_tools,
                             check_note_claims, wait_until_ready)
from assistant.preferences import load_preferences
from assistant.reviewer import build_reviewer
from assistant.router import build_router
from assistant.summarizer import build_summarizer
from lab_server.timezones import get_timezone

logger = logging.getLogger("assistant")

# Controllo breve: con LM Studio appeso /stato non deve attendere tutto LMSTUDIO_TIMEOUT (bloccherebbe la CLI)
STATUS_TIMEOUT = 5.0


def model_status(settings: Settings, list_models=list_models) -> dict:
    try:
        available = list_models(settings.base_url, min(settings.timeout, STATUS_TIMEOUT))
    except LMStudioUnavailable:
        return {"raggiungibile": False, "messaggio": model_unreachable(settings.base_url), "modello": settings.model}
    if settings.model not in available:
        return {"raggiungibile": False, "messaggio": str(ModelNotFound(settings.model, available)),
                "modello": settings.model}
    return {"raggiungibile": True, "messaggio": f"Modello {settings.model} disponibile.", "modello": settings.model}


def _tools_status(client: MCPClient, count: int) -> dict:
    try:
        client.ping()
    except MCPConnectionError:
        return {"raggiungibile": False, "messaggio": TOOLS_DOWN, "strumenti": count}
    return {"raggiungibile": True, "messaggio": f"Server degli strumenti attivo ({count} strumenti).",
            "strumenti": count}


def _notes_status(url: str) -> dict:
    if not _responds(url):
        return {"raggiungibile": False, "messaggio": NOTES_DOWN, "indirizzo": url}
    return {"raggiungibile": True, "messaggio": f"Servizio delle note attivo ({url}).", "indirizzo": url}


def date_line_for(zone_name: str, now: Callable[[ZoneInfo], datetime] = datetime.now) -> Callable[[], str]:
    """Funzione che a ogni chiamata dà la riga della data di oggi nel fuso indicato (non fissata all'avvio)."""
    zone = get_timezone(zone_name)
    return lambda: today_line(now(zone).date(), zone_name)


def reviewer_for(max_reviews: int, build: Callable[[], object]):
    """Revisore solo con MAX_REVIEWS > 0: con 0 il turno non spende la chiamata al modello per il giudizio."""
    return build() if max_reviews > 0 else None


def build_agent(settings: Settings, root: Path) -> tuple[Agent, Callable[[], None]]:
    """Costruisce l'agente; restituisce anche la funzione che chiude servizio note, client HTTP e client MCP.

    ConfigError, MCPConnectionError e NotesConnectionError si propagano dopo aver chiuso quanto già aperto.
    Il modello spento non ferma l'avvio: ChatOpenAI non lo contatta finché non serve.
    """
    scope = load_scope(settings.scope_file, root)
    logger.info("[router] ambito: %s (%d righe)", settings.scope_file, len(scope.splitlines()))
    model = model_status(settings)
    if not model["raggiungibile"]:
        logger.warning("[modello] %s", model["messaggio"])
    with ExitStack() as stack:
        client = MCPClient(server_command(), server_env(settings))
        stack.callback(client.close)
        mcp_tools = client.start()
        if not mcp_tools:
            raise MCPConnectionError("Il server degli strumenti non espone nessuno strumento.")
        # Il catalogo arriva dal server (discovery), non è scritto nell'agente
        logger.info("[mcp] catalogo: %s", ", ".join(tool.name for tool in mcp_tools))
        preferences = load_preferences(client.read_resource, settings.default_timezone)
        try:
            prompt_list = client.list_prompts()
        except MCPPromptError as error:
            logger.warning("[mcp] prompt non disponibili (%s): nessun prompt", error)
            prompt_list = []
        logger.info("[mcp] prompt: %s", ", ".join(p.name for p in prompt_list) or "nessuno")

        if settings.notes_service_url:
            url = settings.notes_service_url
            wait_until_ready(url)
        else:
            service = LocalNotesService(quiet=settings.log_level != "DEBUG")
            stack.callback(service.close)
            url = service.start()
        http = httpx.Client(base_url=url, timeout=TIMEOUT)
        stack.callback(http.close)
        logger.info("[note] servizio: %s", url)

        zone = get_timezone(preferences.fuso_orario)
        today = lambda: datetime.now(zone).date()  # noqa: E731
        date_line = date_line_for(preferences.fuso_orario)
        chat_model = build_chat_model(settings)
        tools = mcp_tools + build_note_tools(http, today)
        router = build_router(chat_model, scope)
        graph = build_graph(chat_model, tools, settings.max_steps,
                            answer_check=check_note_claims, router=router,
                            reviewer=reviewer_for(settings.max_reviews,
                                                  lambda: build_reviewer(chat_model, today=date_line)),
                            max_reviews=settings.max_reviews,
                            summarizer=build_summarizer(chat_model), summary_threshold=settings.summary_threshold,
                            summary_keep_turns=settings.summary_keep_turns,
                            confirmation_check=build_confirmation_check(http, today), today=date_line)
        if settings.max_reviews > 0:
            logger.info("[revisore] limite: %d revisioni", settings.max_reviews)
        else:
            logger.info("[revisore] spento (MAX_REVIEWS=0)")
        logger.info("[riassunto] soglia: %d token stimati, turni conservati: %d",
                    settings.summary_threshold, settings.summary_keep_turns)

        def status() -> dict:
            return {"modello": model_status(settings), "strumenti": _tools_status(client, len(mcp_tools)),
                    "note": _notes_status(url)}

        agent = Agent(graph=graph, system=system_prompt(preferences), settings=settings,
                      list_prompts=client.list_prompts, get_prompt=client.get_prompt, status=status)
        # In sottofondo: la prima domanda trova già in cache l'inizio dei prompt di agente e router
        start_warm_up(chat_model, tools, agent.system, date_line, router=router)
        close = stack.pop_all().close
    return agent, close
