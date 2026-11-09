"""Tool delle note: wrapper LangChain sul servizio HTTP FastAPI, con conferma prima di eliminare."""

import logging
from collections.abc import Callable
from datetime import date

import httpx
from langchain_core.tools import BaseTool, ToolException, tool

logger = logging.getLogger("assistant.notes")

TIMEOUT = 5.0
YES = {"s", "si", "sì"}


class NotesConnectionError(Exception):
    """Servizio non raggiungibile. Non è una ToolException: deve uscire dal grafo."""


def ask_in_terminal(question: str, input_fn=input) -> bool:
    try:
        return input_fn(question).strip().casefold() in YES
    except EOFError:
        return False


def _days(n: int) -> str:
    return f"{n} giorno" if n == 1 else f"{n} giorni"


def due_phrase(due_date: str | None, today: date) -> str:
    if not due_date:
        return "senza scadenza"
    delta = (date.fromisoformat(due_date) - today).days
    if delta > 0:
        when = f"fra {_days(delta)}"
    elif delta == 0:
        when = "scade oggi"
    else:
        when = f"scaduta da {_days(-delta)}"
    return f"scadenza {due_date} ({when})"


def _call(client: httpx.Client, method: str, url: str, **kw) -> httpx.Response:
    try:
        resp = client.request(method, url, **kw)
    except httpx.TransportError as e:
        raise NotesConnectionError(f"Il servizio delle note non risponde: {e}") from e
    if resp.status_code >= 500:
        raise ToolException(f"Errore del servizio delle note (HTTP {resp.status_code}).")
    if resp.status_code >= 400:
        detail = resp.json().get("detail") if resp.headers.get("content-type", "").startswith("application/json") else None
        raise ToolException(detail if isinstance(detail, str) else "Richiesta non valida al servizio delle note.")
    return resp


def build_note_tools(client: httpx.Client, today: Callable[[], date],
                     confirm: Callable[[str], bool]) -> list[BaseTool]:
    @tool
    def add_note(text: str, due_date: str | None = None) -> str:
        """Salva una nota (promemoria) con testo e, se richiesta, una scadenza.

        text: testo della nota. due_date: scadenza opzionale in formato AAAA-MM-GG
        (es. 2026-11-13); se l'utente non indica una scadenza, omettila."""
        note = _call(client, "POST", "/notes", json={"text": text, "due_date": due_date or None}).json()
        return f"Nota {note['id']} salvata: «{note['text']}» · {due_phrase(note['due_date'], today())}."

    @tool
    def list_notes(limit: int = 10) -> str:
        """Elenca le note salvate, con ID, testo e scadenza. limit: numero massimo di note da mostrare."""
        data = _call(client, "GET", "/notes", params={"limit": limit}).json()
        total, notes = data["total"], data["notes"]
        if not notes:
            return "Nessuna nota salvata."
        if len(notes) < total:
            header = f"{total} note, mostrate {len(notes)}:"
        else:
            header = "1 nota:" if total == 1 else f"{total} note:"
        day = today()
        rows = [f"- {n['id']}: {n['text']} · {due_phrase(n['due_date'], day)}" for n in notes]
        return "\n".join([header, *rows])

    @tool
    def delete_note(note_id: int) -> str:
        """Elimina una nota dato il suo ID (visibile con list_notes). Prima chiede conferma all'utente."""
        try:
            note = _call(client, "GET", f"/notes/{note_id}").json()
        except ToolException as e:
            if "Nessuna nota con ID" in str(e):
                raise ToolException(f"Nessuna nota con ID {note_id}: nulla è stato eliminato.") from e
            raise
        phrase = due_phrase(note["due_date"], today())
        if not confirm(f"Elimino la nota {note_id} «{note['text']}» · {phrase}? [s/N] "):
            logger.info("[note] eliminazione della nota %s annullata dall'utente", note_id)
            return f"Eliminazione della nota {note_id} annullata dall'utente."
        logger.info("[note] eliminazione della nota %s confermata dall'utente", note_id)
        _call(client, "DELETE", f"/notes/{note_id}")
        return f"Nota {note_id} eliminata: «{note['text']}»."

    return [add_note, list_notes, delete_note]
