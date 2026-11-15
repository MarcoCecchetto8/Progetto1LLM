"""Servizio HTTP delle note: endpoint FastAPI sopra l'archivio SQLite."""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from notes_service.store import DEFAULT_LIMIT, NoteStore

logger = logging.getLogger("notes_service")


class NoteIn(BaseModel):
    text: str
    due_date: str | None = None


def create_app(db_path: Path) -> FastAPI:
    app = FastAPI(title="Note del laboratorio")
    store = NoteStore(db_path)

    @app.exception_handler(ValueError)
    def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def not_found(note_id: int) -> HTTPException:
        return HTTPException(status_code=404, detail=f"Nessuna nota con ID {note_id}.")

    # Endpoint sincroni: sqlite3 è bloccante, FastAPI li esegue in un thread
    @app.post("/notes", status_code=201)
    def create_note(body: NoteIn):
        note = store.add(body.text, body.due_date)
        logger.info("nota creata id=%s testo=%s scadenza=%s", note["id"], note["text"], note["due_date"])
        return note

    @app.get("/notes")
    def list_notes(limit: int = DEFAULT_LIMIT):
        total, notes = store.list_notes(limit)
        return {"total": total, "notes": notes}

    @app.get("/notes/{note_id}")
    def get_note(note_id: int):
        note = store.get(note_id)
        if note is None:
            raise not_found(note_id)
        return note

    @app.delete("/notes/{note_id}")
    def delete_note(note_id: int):
        note = store.delete(note_id)
        if note is None:
            raise not_found(note_id)
        logger.info("nota eliminata id=%s testo=%s", note["id"], note["text"])
        return note

    return app
