"""API HTTP del back-end: chat salvate, stato di database e agente."""

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from assistant.agent_http import AgentHTTPClient, AgentRequestError, AgentUnavailable
from backend_service.errors import AGENT_DOWN, DB_DOWN, BackendError, chat_not_found
from backend_service.schemas import ChatDetail, ChatSummary, CreateChat, ErrorBody
from backend_service.store import ChatStore, StoreUnavailable

logger = logging.getLogger("backend_service")

ERRORS = {code: {"model": ErrorBody} for code in (404, 409, 422, 500, 502, 503)}


class UTF8JSONResponse(JSONResponse):
    # Senza charset, Windows PowerShell 5.1 (Invoke-RestMethod) legge il corpo come Latin-1
    media_type = "application/json; charset=utf-8"


def _error(status: int, code: str, message: str) -> UTF8JSONResponse:
    return UTF8JSONResponse(status_code=status, content={"codice": code, "messaggio": message})


def create_app(store: ChatStore, agent: AgentHTTPClient) -> FastAPI:
    app = FastAPI(title="Back-end delle chat", default_response_class=UTF8JSONResponse)

    @app.exception_handler(RequestValidationError)
    def validation_error_handler(request: Request, exc: RequestValidationError):
        return UTF8JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})

    @app.exception_handler(BackendError)
    def backend_error_handler(request: Request, exc: BackendError):
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(StoreUnavailable)
    def store_error_handler(request: Request, exc: StoreUnavailable):
        logger.warning("[backend] database non raggiungibile: %s", exc)
        return _error(503, "database_non_raggiungibile", DB_DOWN)

    # Endpoint sincroni: FastAPI li esegue in un thread
    @app.post("/chats", status_code=201, response_model=ChatSummary, responses=ERRORS)
    def create_chat(body: CreateChat | None = None):
        """Crea una chat; il titolo è facoltativo."""
        chat = store.create_chat(body.titolo if body else None)
        logger.info("[backend] chat %d creata", chat["id"])
        return chat

    @app.get("/chats", response_model=list[ChatSummary], responses=ERRORS)
    def list_chats():
        """Elenca le chat, prima quella con l'attività più recente."""
        return store.list_chats()

    @app.get("/chats/{chat_id}", response_model=ChatDetail, responses=ERRORS)
    def get_chat(chat_id: int):
        """Legge una chat con i messaggi e le eventuali conferme in attesa."""
        chat = store.get_chat(chat_id)
        if chat is None:
            raise chat_not_found(chat_id)
        pending = chat.get("in_sospeso") or {}
        return {**chat, "messaggi": store.get_messages(chat_id), "conferme": pending.get("conferme", [])}

    @app.delete("/chats/{chat_id}", status_code=204, responses=ERRORS)
    def delete_chat(chat_id: int):
        """Elimina la chat e i suoi messaggi."""
        if not store.delete_chat(chat_id):
            raise chat_not_found(chat_id)
        logger.info("[backend] chat %d eliminata", chat_id)
        return Response(status_code=204)

    @app.get("/stato")
    def status():
        """Stato di database e agente: 503 se uno dei due non risponde."""
        try:
            store.ping()
            database = {"raggiungibile": True, "messaggio": "ok"}
        except StoreUnavailable:
            database = {"raggiungibile": False, "messaggio": DB_DOWN}
        agent_part = {"raggiungibile": False, "messaggio": AGENT_DOWN, "dettagli": None}
        try:
            details = agent.status()
            parts = [v for v in details.values() if isinstance(v, dict) and "raggiungibile" in v]
            ok = all(v["raggiungibile"] is True for v in parts)
            agent_part = {"raggiungibile": ok, "messaggio": "ok" if ok else "L'agente risponde ma una sua parte no.",
                          "dettagli": details}
        except AgentUnavailable:
            pass
        except AgentRequestError as error:
            agent_part["messaggio"] = error.message
        code = 200 if database["raggiungibile"] and agent_part["raggiungibile"] else 503
        return UTF8JSONResponse(status_code=code,
                                content={"backend": "ok", "database": database, "agente": agent_part})

    return app
