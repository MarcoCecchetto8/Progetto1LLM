"""Tool delle note: wrapper LangChain sul servizio HTTP FastAPI, con conferma prima di eliminare."""

import logging
import os
import re
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import httpx
from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, ToolException, tool

from assistant.reviewer import last_question_index

logger = logging.getLogger("assistant.notes")

TIMEOUT = 5.0

SAVE_WARNING = "⚠ Attenzione: nessuna nota è stata salvata (lo strumento non l'ha confermato)."
DELETE_WARNING = "⚠ Attenzione: nessuna nota è stata eliminata (lo strumento non l'ha confermato)."

# Solo forme verbali di azione compiuta: gli aggettivi ("Nessuna nota salvata") non devono scattare.
# Desinenza libera perché il participio concorda con il pronome ("l'ho salvata"); "aggiunto" e "creato"
# contano solo se seguono nota/promemoria, altrimenti "ho aggiunto 5 giorni" (add_days) darebbe un falso avviso.
# La frase breve ("Nota salvata.") conta solo se apre la frase (inizio del testo o dopo . ! ? :), con al
# massimo due "ok/fatto/..." davanti: nel mezzo ("Hai 2 note salvate", "La nota salvata ieri") è un aggettivo.
_FRASE = r"(?:^|[.!?:]\s*)(?:(?:ok|fatto|perfetto|bene)\s*[,!:]?\s*){0,2}(?:la\s+)?"
_NOTA_N = r"(?:nota|promemoria)\s+(?:(?:n\.?\s*)?\d+\s+)?"
_SAVE_CLAIM = re.compile(
    r"\bho\s+(?:gia\s+)?(salvat|memorizzat|annotat|registrat)[aoie]\b"
    r"|\bho\s+(?:gia\s+)?(?:aggiunt|creat)[aoie]\s+(?:\w+\s+){0,2}?(?:nota|note|promemoria)\b"
    r"|\b(?:e'?|sono)\s+stat[aoie]\s+(salvat|memorizzat|annotat|registrat)[aoie]\b"
    r"|\b(?:nota|note|promemoria)\s+(?:(?:n\.?\s*)?\d+\s+)?(?:e'?|sono)\s+stat[aoie]\s+(?:aggiunt|creat)[aoie]\b"
    r"|" + _FRASE + _NOTA_N + r"(salvat|memorizzat|annotat|registrat|aggiunt|creat)[aoie]\b"
)
# Le espressioni contano solo nelle frasi che parlano della nota («Ho cancellato il file» non è una nota):
# la frase deve contenere nota/note/promemoria, anche per le forme con il pronome («l'ho salvata»).
_NOTE_WORD = re.compile(r"\b(?:nota|note|promemoria)\b")
_DELETE_CLAIM = re.compile(
    r"\bho\s+(?:gia\s+)?(eliminat|cancellat|rimoss)[aoie]\b"
    r"|\b(?:e'?|sono)\s+stat[aoie]\s+(eliminat|cancellat|rimoss)[aoie]\b"
    r"|" + _FRASE + _NOTA_N + r"(eliminat|cancellat|rimoss)[aoie]\b"
)

# Richiesta esplicita dell'utente, cercata sulla domanda normalizzata. Forme volutamente strette: se l'utente
# parla d'altro («Come si salva un file», «Ricordami come mi chiamo», «Crea una nota musicale in Python»)
# l'avviso non deve mai comparire, quindi nel dubbio una forma resta fuori. Il salvataggio conta solo a inizio
# domanda (con "per favore/ok/ehi" facoltativo); l'eliminazione anche dopo e/ed/poi/virgola, ma solo con il numero.
_PREFISSO = r"(?:(?:per favore|ok|ehi)\s*,?\s*)?"
_SAVE_REQUEST = re.compile(
    r"^\s*" + _PREFISSO + r"(?:"
    r"(?:salva|salvami|annota|annotami|segna|segnati|segnami|scrivi|scrivimi|aggiungi|crea)\s+"
    r"(?:(?:una|la|un|il)\s+)?(?:nota|promemoria)(?:\s*:|\s*[.!]?\s*$)"
    r"|(?:annota|annotati|segnati|segnami)\s+che\b(?!\s*(?:cos|cosa|ore|tipo|differenza|significa)\b)"
    r"|ricordami\s+di\s+\w+(?:[aei]re|[aei]r(?:lo|la|li|le|mi|ti|ci|vi|gli|ne))\b)"
)
_DELETE_REQUEST = re.compile(
    r"(?:^\s*" + _PREFISSO + r"|\b(?:e|ed|poi)\s+|,\s*)"
    r"(?:elimina|cancella|rimuovi)\s+(?:(?:la|le|il|i|questa)\s+)?(?:nota|note|promemoria)\s+(?:n\.?\s*)?\d"
)


class NotesConnectionError(Exception):
    """Servizio non raggiungibile. Non è una ToolException: deve uscire dal grafo."""


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


def _confirmation_question(note: dict, today: date) -> str:
    return f"Elimino la nota {note['id']} «{note['text']}» · {due_phrase(note['due_date'], today)}? [s/N] "


def build_confirmation_check(client: httpx.Client,
                             today: Callable[[], date]) -> Callable[[list[dict], dict[int, bool]], list[dict]]:
    def check(calls: list[dict], decisions: dict[int, bool]) -> list[dict]:
        """Domande di conferma per le eliminazioni non ancora decise; le note inesistenti non chiedono nulla."""
        ids = []
        for call in calls:
            note_id = call["args"].get("note_id") if call["name"] == "delete_note" else None
            # I modelli locali passano spesso l'ID come stringa ("1"): il ToolNode lo converte, quindi va chiesto
            if isinstance(note_id, str) and note_id.isascii() and note_id.isdigit():
                note_id = int(note_id)
            if (isinstance(note_id, int) and not isinstance(note_id, bool)
                    and note_id not in decisions and note_id not in ids):
                ids.append(note_id)
        needed = []
        for note_id in ids:
            try:
                note = _call(client, "GET", f"/notes/{note_id}").json()
            except ToolException as e:
                # Il tool rifà la stessa chiamata e restituisce l'errore (404 compreso) al modello
                continue
            needed.append({"id_nota": note_id, "domanda": _confirmation_question(note, today())})
        return needed

    return check


_WEEKDAYS = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato", "domenica"]  # come date.weekday()
_WEEKDAYS_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_ISO_DATE =re.compile(r"\d{4}-\d{2}-\d{2}")


def resolve_due_date(value: str | None, today: date) -> str | None:
    """Traduce una scadenza relativa in AAAA-MM-GG; una data ISO passa invariata (la valida il servizio)."""
    if value is None or not value.strip():
        return None
    word = _normalize(value).strip()
    if _ISO_DATE.fullmatch(word):
        return word
    # Il modello a volte ragiona in inglese: accetto anche le forme equivalenti
    offsets = {"oggi": 0, "domani": 1, "dopodomani": 2, "today": 0, "tomorrow": 1, "day after tomorrow": 2}
    if word in offsets:
        return (today + timedelta(days=offsets[word])).isoformat()
    name = word.removesuffix(" prossimo").removesuffix(" prossima").removeprefix("next ")
    weekday = _WEEKDAYS.index(name) if name in _WEEKDAYS else _WEEKDAYS_EN.index(name) if name in _WEEKDAYS_EN else None
    if weekday is not None:
        ahead = (weekday - today.weekday() - 1) % 7 + 1  # da 1 a 7: mai oggi
        return (today + timedelta(days=ahead)).isoformat()
    raise ToolException(f"Scadenza non valida: «{value}». Usa AAAA-MM-GG oppure oggi, domani, dopodomani "
                        "o un giorno della settimana (es. venerdì).")


def build_note_tools(client: httpx.Client, today: Callable[[], date]) -> list[BaseTool]:
    @tool
    def add_note(text: str, due_date: str | None = None) -> str:
        """Salva una nota (promemoria) con testo e, se richiesta, una scadenza.

        text: testo della nota. due_date: scadenza opzionale, AAAA-MM-GG oppure oggi, domani, dopodomani o un
        giorno della settimana: per le date relative passa la parola così com'è (es. due_date="venerdì"),
        il programma calcola la data; se l'utente non indica una scadenza, omettila."""
        due = resolve_due_date(due_date, today())
        note = _call(client, "POST", "/notes", json={"text": text, "due_date": due}).json()
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
    def delete_note(note_id: int, config: RunnableConfig) -> str:
        """Elimina una nota dato il suo ID (visibile con list_notes). Prima chiede conferma all'utente."""
        try:
            note = _call(client, "GET", f"/notes/{note_id}").json()
        except ToolException as e:
            if "Nessuna nota con ID" in str(e):
                raise ToolException(f"Nessuna nota con ID {note_id}: nulla è stato eliminato.") from e
            raise
        # La decisione arriva dal grafo, che ha sospeso il turno per chiederla all'utente
        decision = config.get("configurable", {}).get("note_decisions", {}).get(note_id)
        if decision is None:
            logger.warning("[note] eliminazione della nota %s senza conferma: annullata", note_id)
            return f"Eliminazione della nota {note_id} annullata dall'utente."
        if not decision:
            logger.info("[note] eliminazione della nota %s annullata dall'utente", note_id)
            return f"Eliminazione della nota {note_id} annullata dall'utente."
        logger.info("[note] eliminazione della nota %s confermata dall'utente", note_id)
        _call(client, "DELETE", f"/notes/{note_id}")
        return f"Nota {note_id} eliminata: «{note['text']}»."

    return [add_note, list_notes, delete_note]


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _note_sentences(text: str) -> list[str]:
    # Protegge i punti di «n. 3» e dei numeri decimali, poi divide in frasi.
    text = re.sub(r"\bn\.(?=\s*\d)", "n@@", text)
    text = re.sub(r"(?<=\d)\.(?=\d)", "@@", text)
    return [part.replace("@@", ".").strip() for part in re.split(r"[.!?\n]+", text) if part.strip()]


def check_note_claims(messages: list[AnyMessage]) -> list[str]:
    """Avvisi per le risposte che dichiarano, o che l'utente aveva chiesto esplicitamente, un salvataggio
    o un'eliminazione mai confermati da uno strumento."""
    answer = messages[-1].content
    if not isinstance(answer, str):
        return []
    last_human = last_question_index(messages)
    confirmed = {m.name for m in messages[last_human + 1:]
                 if isinstance(m, ToolMessage) and m.status != "error"}
    text = _normalize(answer)
    question = messages[last_human].content if last_human >= 0 else None
    # Una domanda di chiarimento («Che testo vuoi salvare?») non è un falso successo.
    asks_back = text.rstrip().endswith("?")
    save_asked = delete_asked = False
    # Una domanda che termina con «?» non è una richiesta («Nota: è lenta, perché?»).
    if isinstance(question, str) and not asks_back and not question.rstrip().endswith("?"):
        q = _normalize(question)
        save_asked = bool(_SAVE_REQUEST.search(q))
        delete_asked = bool(_DELETE_REQUEST.search(q))
    warnings = []
    about_note = [s for s in _note_sentences(text) if _NOTE_WORD.search(s)]
    save_claimed = any(_SAVE_CLAIM.search(s) for s in about_note)
    delete_claimed = any(_DELETE_CLAIM.search(s) for s in about_note)
    if (save_claimed or save_asked) and "add_note" not in confirmed:
        warnings.append(SAVE_WARNING)
    if (delete_claimed or delete_asked) and "delete_note" not in confirmed:
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
