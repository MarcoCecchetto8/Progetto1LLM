"""Tool delle note: wrapper LangChain sul servizio HTTP FastAPI, con conferma prima di eliminare."""

import logging
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, ToolException, tool

logger = logging.getLogger("assistant.notes")

TIMEOUT = 5.0
YES = {"s", "si", "sì"}

SAVE_WARNING = "⚠ Attenzione: nessuna nota è stata salvata (lo strumento non l'ha confermato)."
DELETE_WARNING = "⚠ Attenzione: nessuna nota è stata eliminata (lo strumento non l'ha confermato)."

# Solo forme verbali di azione compiuta: gli aggettivi ("Nessuna nota salvata") non devono scattare.
# Desinenza libera perché il participio concorda con il pronome ("l'ho salvata"); "aggiunto" conta
# solo se segue nota/promemoria, altrimenti "ho aggiunto 5 giorni" (add_days) darebbe un falso avviso.
_SAVE_CLAIM = re.compile(
    r"\bho\s+(?:gia\s+)?(salvat|memorizzat|annotat|registrat)[aoie]\b"
    r"|\bho\s+(?:gia\s+)?aggiunt[aoie]\s+(?:\w+\s+){0,2}?(?:nota|note|promemoria)\b"
    r"|\b(?:e'?|sono)\s+stat[aoie]\s+(salvat|memorizzat|annotat|registrat)[aoie]\b"
)
_DELETE_CLAIM = re.compile(
    r"\bho\s+(?:gia\s+)?(eliminat|cancellat|rimoss)[aoie]\b"
    r"|\b(?:e'?|sono)\s+stat[aoie]\s+(eliminat|cancellat|rimoss)[aoie]\b"
)


class NotesConnectionError(Exception):
    """Servizio non raggiungibile. Non è una ToolException: deve uscire dal grafo."""


# La conferma gira in un thread del ToolNode: lo stato è a livello di modulo e thread-safe.
# Serve al ciclo da terminale per distinguere un Ctrl+C alla conferma da uno durante il modello.
_pending = threading.Event()


def confirmation_pending() -> bool:
    return _pending.is_set()


def reset_confirmation() -> None:
    _pending.clear()


def ask_in_terminal(question: str, input_fn=input) -> bool:
    _pending.set()
    try:
        answer = input_fn(question)
    except EOFError:
        _pending.clear()
        return False
    except KeyboardInterrupt:
        # Resta segnata: chi sta in ascolto sa che l'utente ha interrotto proprio la conferma
        return False
    _pending.clear()
    return answer.strip().casefold() in YES


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
    # ToolNode esegue in parallelo le chiamate di uno stesso messaggio: senza lock due
    # conferme comparirebbero insieme e la risposta dell'utente potrebbe valere per la nota sbagliata.
    delete_lock = threading.Lock()

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
        with delete_lock:
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


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def check_note_claims(messages: list[AnyMessage]) -> list[str]:
    """Avvisi per le risposte che dichiarano un salvataggio o un'eliminazione mai confermati da uno strumento."""
    answer = messages[-1].content
    if not isinstance(answer, str):
        return []
    last_human = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    confirmed = {m.name for m in messages[last_human + 1:]
                 if isinstance(m, ToolMessage) and m.status != "error"}
    text = _normalize(answer)
    warnings = []
    if _SAVE_CLAIM.search(text) and "add_note" not in confirmed:
        warnings.append(SAVE_WARNING)
    if _DELETE_CLAIM.search(text) and "delete_note" not in confirmed:
        warnings.append(DELETE_WARNING)
    return warnings


def _responds(url: str) -> bool:
    try:
        httpx.get(f"{url}/notes", params={"limit": 1}, timeout=1.0)
    except httpx.TransportError:
        return False
    return True


def wait_until_ready(url: str, timeout: float = 20.0, alive: Callable[[], bool] = lambda: True) -> None:
    deadline = time.monotonic() + timeout
    while alive():
        if _responds(url):
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.2)
    raise NotesConnectionError(f"Il servizio delle note non risponde all'indirizzo {url}.")


class LocalNotesService:
    """Avvia il servizio delle note come sottoprocesso locale."""

    def __init__(self, port: int = 8000, quiet: bool = True, db: Path | None = None):
        self.port = port
        self.quiet = quiet
        self.db = db
        self._proc: subprocess.Popen | None = None

    def start(self) -> str:
        url = f"http://127.0.0.1:{self.port}"
        if _responds(url):
            raise NotesConnectionError(
                f"La porta {self.port} è già in uso (forse il servizio delle note di Docker è acceso: "
                "docker compose down)."
            )
        command = [sys.executable, "-m", "notes_service", "--port", str(self.port)]
        if self.quiet:
            command.append("--quiet")
        if self.db:
            command += ["--db", str(self.db)]
        # Su Windows Ctrl+C arriva a tutti i processi della console: senza gruppo separato il servizio
        # morirebbe quando Ctrl+C ferma solo il turno.
        if os.name == "nt":
            isolation = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            isolation = {"start_new_session": True}
        proc = self._proc = subprocess.Popen(command, **isolation)
        try:
            wait_until_ready(url, alive=lambda: proc.poll() is None)
        except NotesConnectionError as error:
            self.close()
            raise NotesConnectionError(f"Il servizio delle note non è partito su {url}.") from error
        return url

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
