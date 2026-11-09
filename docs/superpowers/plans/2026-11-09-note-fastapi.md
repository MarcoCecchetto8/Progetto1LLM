# Note persistenti con FastAPI — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** note persistenti (aggiungi, elenca, elimina con conferma del programma) in un servizio FastAPI + SQLite separato, usato dall'assistente tramite tre wrapper `@tool` scritti a mano.

**Architecture:** nuovo pacchetto `notes_service/` (`store.py` = SQLite con validazione, `app.py` = FastAPI, `__main__.py` = uvicorn). Nell'assistente `assistant/notes.py`: tre tool sincroni con `httpx.Client`, formattazione dei risultati (distanza dalla scadenza calcolata dal programma), conferma dell'eliminazione nel terminale, avvio automatico del servizio in locale. I tre tool si aggiungono ai 9 tool MCP prima di `build_graph`; il grafo non cambia.

**Tech Stack:** Python 3.14; nuove dipendenze `fastapi==0.162.2`, `uvicorn==0.54.0`, `httpx==0.28.1` (verificate il 2026-11-09 in un venv pulito con `requirements.txt`: installazione ok, `pip check` «No broken requirements found», import di `fastapi.testclient` ok; starlette 1.10.0 arriva con fastapi). SQLite con `sqlite3` della libreria standard.

**Spec:** `docs/superpowers/specs/2026-11-09-note-fastapi-design.md`

## Global Constraints

- Branch `feature/note-fastapi` da `developer` aggiornato; merge `--no-ff` in `developer`, push di `developer` ed eliminazione del branch **solo dopo la prova reale e l'ok dell'utente**. Il branch feature non si pusha.
- Pezzi piccoli, un commit per task (o meno); prima di ogni commit `git status`, diff, staging selettivo; controllare l'**exit code** di pytest.
- Nomi nel codice in inglese; testi per l'utente, risultati, errori, log, README e commit in italiano (Conventional Commits).
- Archivio: `data/notes.db` nella radice del progetto; `data/` in `.gitignore`; mai versionare il database.
- Limiti: testo 1–500 caratteri (spazi ai bordi tolti); `limit` 1–50, predefinito 10; scadenza `AAAA-MM-GG` esistente, passata ammessa; `""` come scadenza = nessuna scadenza.
- Eliminazione solo per ID esatto e solo dopo `s`/`si`/`sì` (senza distinzione di maiuscole) nel terminale; qualsiasi altra risposta, invio vuoto o EOF annulla. L'annullamento è un risultato normale, non un errore.
- Errori del servizio (validazione, ID inesistente) → `ToolException` nel wrapper (tornano al modello). Servizio irraggiungibile o timeout → `NotesConnectionError` (esce dal grafo, turno interrotto). Timeout HTTP 5 secondi.
- Nuova variabile `NOTES_SERVICE_URL`: vuota = avvio automatico su `http://127.0.0.1:8000`; impostata = servizio esterno.
- Comandi dalla radice con il venv attivo (`.\.venv\Scripts\Activate.ps1`); test: `python -m pytest`.
- Non leggere né modificare `lezione-03/`.

## Review Focus

1. **Porta 8000 già occupata all'avvio locale** (per esempio il container `notes` di Docker ancora acceso): errore chiaro che suggerisce `docker compose down`, senza parlare in silenzio con l'altro servizio. Test nel Task 4.
2. **Il modello passa una scadenza non ISO o vuota** (`"venerdì"`, `""`): `""` = senza scadenza; `"venerdì"` → errore italiano con il formato atteso, che torna al modello. Test nei Task 1 e 3.
3. **EOF o invio vuoto alla domanda di conferma** (input da pipe, Docker `-T`): nulla eliminato, risultato «annullata dall'utente». Test nel Task 3.
4. **Testo con virgolette, a capo, emoji o apici SQL** (`l'esame "finale" 🎓`, `'); DROP TABLE notes;--`): salvato e restituito identico (query parametrizzate). Test nel Task 1.
5. **Servizio che si ferma a metà sessione**: `NotesConnectionError` → messaggio `NOTES_DOWN`, cronologia invariata, nessun traceback. Test nei Task 3 e 4.

---

### Task 1: Dipendenze e archivio SQLite

**Files:**
- Modify: `requirements.txt`, `.gitignore`
- Create: `notes_service/__init__.py`, `notes_service/store.py`
- Test: `tests/test_notes_store.py`

**Interfaces:**
- Produces in `notes_service/store.py`:
  - `MAX_TEXT = 500`, `MAX_LIMIT = 50`, `DEFAULT_LIMIT = 10`
  - `class NoteStore:` `__init__(self, path: Path)` (crea la cartella e la tabella se mancano); `add(self, text: str, due_date: str | None = None) -> dict`; `list_notes(self, limit: int = DEFAULT_LIMIT) -> tuple[int, list[dict]]` (totale, note); `get(self, note_id: int) -> dict | None`; `delete(self, note_id: int) -> dict | None` (la nota eliminata o `None`).
  - Nota = `{"id": int, "text": str, "due_date": str | None, "created_at": str}`; `created_at` = `datetime.now(UTC).isoformat(timespec="seconds")`.
  - Una connessione `sqlite3` per operazione (le richieste FastAPI arrivano da thread diversi); query sempre parametrizzate.
  - Ordine: `ORDER BY due_date IS NULL, due_date, CASE WHEN due_date IS NULL THEN -id ELSE id END`.
  - Errori `ValueError` (testi esatti): `Il testo della nota è vuoto.`; `Il testo della nota è troppo lungo: massimo 500 caratteri (ricevuti {n}).`; `Scadenza "{v}" non valida: formato atteso AAAA-MM-GG (es. 2026-11-13).`; `Scadenza "{v}" inesistente.`; `limit deve essere compreso fra 1 e 50.` (`v` senza spazi ai bordi).

- [ ] **Step 1:** `git checkout developer`, `git pull`, `git checkout -b feature/note-fastapi`.
- [ ] **Step 2:** aggiungi a `requirements.txt` `fastapi==0.162.2`, `uvicorn==0.54.0`, `httpx==0.28.1`; `pip install -r requirements.txt` nel `.venv`; `python -m pip check` → «No broken requirements found». Aggiungi `data/` a `.gitignore`.
- [ ] **Step 3: test** in `tests/test_notes_store.py` (archivio in `tmp_path / "sub" / "notes.db"`, cartella non esistente):
  - `add("  consegnare il report ", "2026-11-13")` restituisce id 1, testo `"consegnare il report"`, `due_date "2026-11-13"`, `created_at` che termina con `+00:00`; la cartella `sub` viene creata;
  - `add("x", "")` e `add("x", None)` → `due_date is None`; `add("x", " 2026-11-13 ")` → `"2026-11-13"`;
  - Review Focus 4: `add('l\'esame "finale" 🎓\nseconda riga')` e `add("'); DROP TABLE notes;--")` restituiti identici da `get`; dopo, `list_notes()` ha totale 2;
  - errori: `add("   ")` → `"vuoto"`; `add("a" * 501)` → `"massimo 500 caratteri (ricevuti 501)"`; `add("a" * 500)` valido; Review Focus 2: `add("x", "venerdì")` → `'Scadenza "venerdì" non valida: formato atteso AAAA-MM-GG'`; `add("x", "2026-02-30")` → `"inesistente"`; `add("x", "2020-01-01")` valido (passata ammessa);
  - ordine: note con scadenze `2026-12-01`, nessuna, `2026-11-01`, nessuna, `2026-11-20` → ordine degli ID `[3, 5, 1, 4, 2]`;
  - `list_notes(2)` → totale 5, 2 note; `list_notes(0)` e `list_notes(51)` → `ValueError` `"fra 1 e 50"`;
  - `get(99) is None`; `delete(1)` restituisce la nota 1 e poi `get(1) is None`; `delete(1) is None`;
  - persistenza: un secondo `NoteStore` sullo stesso file vede le stesse note.
- [ ] **Step 4:** FAIL → implementa → PASS; `python -m pytest` tutto verde; commit `feat(note): aggiunge l'archivio SQLite delle note` (con `requirements.txt` e `.gitignore`).

### Task 2: Servizio FastAPI

**Files:**
- Create: `notes_service/app.py`, `notes_service/__main__.py`
- Test: `tests/test_notes_service.py`

**Interfaces:**
- Consumes: `NoteStore`, `DEFAULT_LIMIT` (Task 1).
- Produces:
  - `notes_service.app.create_app(db_path: Path) -> FastAPI` (titolo `"Note del laboratorio"`): `POST /notes` (JSON `{"text": str, "due_date": str | None}`) → `201` con la nota; `GET /notes?limit=` → `200` `{"total": int, "notes": [...]}`; `GET /notes/{note_id}` → `200` nota o `404`; `DELETE /notes/{note_id}` → `200` nota eliminata o `404`. `ValueError` del `NoteStore` → `422` con `{"detail": "<testo italiano>"}`; `404` con `{"detail": "Nessuna nota con ID {id}."}`.
  - Logger `"notes_service"`: `INFO` `nota creata id=%s testo=%s scadenza=%s` e `nota eliminata id=%s testo=%s`.
  - `python -m notes_service [--host 127.0.0.1] [--port 8000] [--db <percorso>] [--quiet]`: `--db` predefinito `data/notes.db` nella radice del progetto (`Path(__file__).resolve().parents[1] / "data" / "notes.db"`); log su stderr a `INFO`; con `--quiet` livello `WARNING` e `access_log=False`; `uvicorn.run(create_app(db), host=..., port=..., log_level=..., access_log=...)`.

- [ ] **Step 1: test** in `tests/test_notes_service.py` con `TestClient(create_app(tmp_path / "notes.db"))`:
  - `POST /notes {"text": "report", "due_date": "2026-11-13"}` → `201`, `id == 1`; `GET /notes/1` → `200` stessa nota; `GET /notes` → `{"total": 1, ...}`;
  - `POST /notes {"text": ""}` → `422`, `detail == "Il testo della nota è vuoto."`; `due_date "13/11/2026"` → `422` con `"AAAA-MM-GG"` nel detail; `GET /notes?limit=0` → `422` con `"fra 1 e 50"`;
  - `GET /notes/99` e `DELETE /notes/99` → `404`, `detail == "Nessuna nota con ID 99."`;
  - `DELETE /notes/1` → `200` con la nota, poi `GET /notes/1` → `404`;
  - `caplog` a `INFO`: dopo creazione ed eliminazione compaiono `nota creata id=1` e `nota eliminata id=1`;
  - persistenza: una seconda `create_app` sullo stesso file vede la nota;
  - `GET /openapi.json` → `200` e contiene `"/notes"`.
- [ ] **Step 2:** FAIL → implementa → PASS; tutto verde; commit `feat(note): aggiunge il servizio FastAPI delle note`.
- [ ] **Step 3: verifica diretta** in PowerShell, annotando l'output: `python -m notes_service --db $env:TEMP\notes-prova.db` in un terminale; in un altro `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/notes -ContentType 'application/json' -Body '{"text":"prova","due_date":"2026-11-13"}'`, `Invoke-RestMethod http://127.0.0.1:8000/notes`, `Invoke-RestMethod -Method Delete http://127.0.0.1:8000/notes/1`; poi Ctrl+C. Tieni i comandi e gli output per il README (Task 5).

### Task 3: Tool delle note nell'assistente

**Files:**
- Create: `assistant/notes.py`
- Test: `tests/test_notes_tools.py`

**Interfaces:**
- Consumes: `create_app` (solo nei test, tramite `TestClient`, che è un `httpx.Client`).
- Produces in `assistant/notes.py`:
  - `class NotesConnectionError(Exception)`; `TIMEOUT = 5.0`
  - `ask_in_terminal(question: str, input_fn=input) -> bool` — `True` solo per `s`/`si`/`sì` (strip + casefold); `EOFError` → `False`.
  - `due_phrase(due_date: str | None, today: date) -> str` — `senza scadenza`; `scadenza 2026-11-13 (fra 4 giorni)`; `(fra 1 giorno)`; `(scade oggi)`; `(scaduta da 2 giorni)`; `(scaduta da 1 giorno)`.
  - `build_note_tools(client: httpx.Client, today: Callable[[], date], confirm: Callable[[str], bool]) -> list[BaseTool]` → tool `add_note(text: str, due_date: str | None = None)`, `list_notes(limit: int = 10)`, `delete_note(note_id: int)`, tutti `-> str`, con docstring italiane (descrizioni nel wrapper: niente discovery).
  - Testi: `Nota {id} salvata: «{text}» · {due_phrase}.`; elenco `{n} note, mostrate {m}:` (se troncato), `{n} note:` (`1 nota:` se una), righe `- {id}: {text} · {due_phrase}`, vuoto `Nessuna nota salvata.`; domanda di conferma `Elimino la nota {id} «{text}» · {due_phrase}? [s/N] `; `Nota {id} eliminata: «{text}».`; `Eliminazione della nota {id} annullata dall'utente.`; ID inesistente in `delete_note` → `ToolException("Nessuna nota con ID {id}: nulla è stato eliminato.")` **senza** chiedere conferma.
  - Risposta `4xx` → `ToolException(detail)` se `detail` è una stringa, altrimenti `ToolException("Richiesta non valida al servizio delle note.")`; `5xx` → `ToolException("Errore del servizio delle note (HTTP {code}).")`; `httpx.TransportError` (compreso il timeout) → `NotesConnectionError("Il servizio delle note non risponde: {errore}")`.
  - Logger `"assistant.notes"`: `INFO` `[note] eliminazione della nota %s confermata dall'utente` / `annullata dall'utente`.

- [ ] **Step 1: test** in `tests/test_notes_tools.py` (`TODAY = date(2026, 11, 9)`; `client = TestClient(create_app(tmp_path / "n.db"))`; tool presi per nome):
  - `due_phrase`: `None` → `"senza scadenza"`; `"2026-11-13"` → `"scadenza 2026-11-13 (fra 4 giorni)"`; `"2026-11-10"` → `"(fra 1 giorno)"`; `"2026-11-09"` → `"(scade oggi)"`; `"2026-11-07"` → `"(scaduta da 2 giorni)"`;
  - `add_note {"text": "consegnare il report", "due_date": "2026-11-13"}` → `"Nota 1 salvata: «consegnare il report» · scadenza 2026-11-13 (fra 4 giorni)."`;
  - Review Focus 2: `add_note {"text": "x", "due_date": "venerdì"}` → `ToolException` con `"AAAA-MM-GG"`; `{"text": "x", "due_date": ""}` → `"· senza scadenza."`;
  - `list_notes` vuoto → `"Nessuna nota salvata."`; con 3 note e `limit` 2 → prima riga `"3 note, mostrate 2:"`; con 1 nota → `"1 nota:"`;
  - `delete_note {"note_id": 1}` con `confirm` che restituisce `True` → `"Nota 1 eliminata: «...»."` e la nota non c'è più; la domanda passata a `confirm` è `"Elimino la nota 1 «consegnare il report» · scadenza 2026-11-13 (fra 4 giorni)? [s/N] "`;
  - con `confirm` → `False` → `"Eliminazione della nota 1 annullata dall'utente."` e la nota c'è ancora; `caplog` contiene `"annullata dall'utente"`;
  - `delete_note {"note_id": 99}` → `ToolException` `"Nessuna nota con ID 99: nulla è stato eliminato."` e `confirm` mai chiamata;
  - Review Focus 3: `ask_in_terminal` con input `"s"`, `"Sì"`, `" SI "` → `True`; `""`, `"n"`, `"forse"` → `False`; `input_fn` che solleva `EOFError` → `False`;
  - Review Focus 5: con `httpx.Client(base_url="http://127.0.0.1:9", timeout=0.5)` (porta chiusa) `list_notes` → `NotesConnectionError`;
  - grafo con il modello finto (`tests.fakes`): `tool_call({"text": "report"}, "n1", name="add_note")` poi `AIMessage("Fatto")` → `ToolMessage` `n1` con stato `success` e testo `"Nota 1 salvata"`; `delete_note` con `confirm` → `False` → `ToolMessage` `success` «annullata» e nota ancora presente.
- [ ] **Step 2:** FAIL → implementa → PASS; tutto verde; commit `feat(note): aggiunge i tool delle note con conferma dell'eliminazione`.

### Task 4: Avvio automatico e integrazione nell'assistente

**Files:**
- Modify: `assistant/notes.py`, `assistant/config.py`, `assistant/__main__.py`, `assistant/cli.py`, `assistant/graph.py`
- Test: `tests/test_notes_launcher.py`, `tests/test_config.py`, `tests/test_cli.py`, `tests/test_graph.py`, `tests/test_main.py`

**Interfaces:**
- Produces:
  - In `assistant/notes.py`: `wait_until_ready(url: str, timeout: float = 20.0, alive: Callable[[], bool] = lambda: True) -> None` (interroga `GET {url}/notes?limit=1` ogni 0,2 s; scaduto il tempo o `alive()` falso → `NotesConnectionError(f"Il servizio delle note non risponde all'indirizzo {url}.")`); `class LocalNotesService:` `__init__(self, port: int = 8000, quiet: bool = True, db: Path | None = None)`, `start(self) -> str` (URL), `close(self) -> None` (idempotente: terminate, attesa 5 s, kill).
  - `start()`: se `GET http://127.0.0.1:{port}/notes?limit=1` risponde già → `NotesConnectionError(f"La porta {port} è già in uso (forse il servizio delle note di Docker è acceso: docker compose down).")`; altrimenti avvia `[sys.executable, "-m", "notes_service", "--port", str(port)] + (["--quiet"] if quiet else []) + (["--db", str(db)] if db else [])` e `wait_until_ready(url, alive=lambda: proc.poll() is None)`; in caso d'errore chiude il processo e rilancia `NotesConnectionError(f"Il servizio delle note non è partito su {url}.")`.
  - `Settings.notes_service_url: str = ""` (ultimo campo, con default); `load_settings` legge `NOTES_SERVICE_URL` (spazi e `/` finale tolti; facoltativa).
  - `cli.NOTES_DOWN = "Il servizio delle note non risponde: esci e riavvia l'assistente."`; `run` gestisce `NotesConnectionError` come `MCPConnectionError` (log `WARNING` `[note] collegamento con il servizio perso: %s`, messaggio, turno fuori dalla cronologia).
  - `_start()`: dopo il catalogo MCP, `service = None if settings.notes_service_url else LocalNotesService(quiet=settings.log_level != "DEBUG")`; `url = settings.notes_service_url or service.start()`; con URL esterno `wait_until_ready(url)`; `httpx.Client(base_url=url, timeout=TIMEOUT)`; `tools + build_note_tools(client, today, ask_in_terminal)` con `today = lambda: datetime.now(get_timezone(settings.default_timezone)).date()`; log `INFO` `[note] servizio: <url>`; `NotesConnectionError` all'avvio → messaggio su stderr e `return 1`; nel `finally` chiusura di client HTTP e servizio con `close_quietly`. Import dentro `_start` (tempi di avvio e Ctrl+C).
  - `system_prompt`: frase (prima di quella sugli errori): «Per ricordare qualcosa usa `add_note`, una sola volta per richiesta, con la scadenza nel formato AAAA-MM-GG se l'utente ne indica una (per giorni come «venerdì» o «domani» ricava la data con gli strumenti delle date). Per vedere le note usa `list_notes`. Per eliminare una nota usa `delete_note` con l'ID esatto preso da `list_notes`; se non è chiaro quale nota intende l'utente, chiediglielo; prima di eliminare il programma chiederà conferma all'utente. Non dire mai che una nota è stata salvata o eliminata se lo strumento non lo conferma.»

- [ ] **Step 1: test:**
  - `tests/test_notes_launcher.py` (porta libera presa con `socket.bind(("127.0.0.1", 0))`, `db=tmp_path / "n.db"`: i test non toccano mai `data/notes.db`): `start()` restituisce `http://127.0.0.1:<porta>` e `GET /notes` risponde `200`; dopo `close()` la porta non risponde e `close()` ripetuto non solleva; Review Focus 1: con un primo servizio acceso, un secondo `LocalNotesService` sulla stessa porta → `NotesConnectionError` con `"già in uso"` e `"docker compose down"`; `wait_until_ready("http://127.0.0.1:9", timeout=0.5)` → `NotesConnectionError`.
  - `tests/test_config.py`: `NOTES_SERVICE_URL` assente → `""`; `" http://notes:8000/ "` → `"http://notes:8000"`.
  - `tests/test_cli.py`: un grafo stub che solleva `NotesConnectionError` → output contiene `NOTES_DOWN` e la cronologia del turno successivo non contiene la domanda fallita (come il test esistente per `MCPConnectionError`).
  - `tests/test_graph.py`: il prompt contiene `add_note`, `list_notes`, `delete_note`, `"ID esatto"` e `"chiederà conferma"`.
  - `tests/test_main.py`: in `test_heavy_imports_happen_inside_main` aggiungi `"assistant.notes"`, `"fastapi"`, `"notes_service"` alla tupla.
- [ ] **Step 2:** FAIL → implementa → PASS; tutto verde; commit `feat(note): avvia il servizio delle note e collega i tool all'assistente`.

### Task 5: Docker, documentazione e prova reale

**Files:**
- Modify: `Dockerfile`, `compose.yaml`, `.env.example`, `README.md`, `CLAUDE.md`

- [ ] **Step 1: Docker:** `Dockerfile` copia anche `notes_service/`. `compose.yaml`: servizio `notes` (`build: .`, `command: ["python", "-m", "notes_service", "--host", "0.0.0.0", "--port", "8000", "--db", "/app/data/notes.db"]`, `ports: ["8000:8000"]`, `volumes: ["./data:/app/data"]`); in `app` `NOTES_SERVICE_URL: http://notes:8000` e `depends_on: [notes]`. `.env.example`: riga commentata su `NOTES_SERVICE_URL` (vuota in locale; Compose la imposta da solo).
- [ ] **Step 2: verifica Docker** (annota gli output): `docker compose build`; `docker compose run --rm -T app` con input da pipe `quit` (avvio senza errori e riga `[note] servizio: http://notes:8000`); `docker compose ps` mostra `notes` acceso e la porta 8000 pubblicata (se `run` non la pubblica, annotalo e usa `docker compose up -d notes` nel README); `Invoke-RestMethod http://127.0.0.1:8000/notes` dall'host; permessi di scrittura: una `POST` da host crea `data/notes.db` nella cartella del progetto; `docker compose down`.
- [ ] **Step 3: documentazione:** README — architettura (servizio FastAPI accanto al server MCP, differenza con la discovery), configurazione (`NOTES_SERVICE_URL`), avvio locale (servizio avviato dall'assistente, `/docs` nel browser), Docker (secondo container, stesse note in `data/`, `docker compose down` per fermarlo, non usare insieme locale e Docker), verifica diretta (comandi del Task 2 con l'output osservato), sezione «Prova reale delle note» con le domande della spec §8 ed esito «da provare», diagnosi (porta 8000 occupata, servizio che non risponde), numero di test. `CLAUDE.md` — struttura (`notes_service/`, `assistant/notes.py`, `data/` escluso da Git), comandi (`python -m notes_service`), confini (strumenti MCP in `lab_server/`, note tramite il servizio FastAPI; meteo con specifica propria). Commit `docs: documenta il servizio delle note` (e `build(docker): ...` per Dockerfile/compose se separato).
- [ ] **Step 4: prova reale (utente, LM Studio acceso)**, in locale e con Docker: «Ricordami di consegnare il report venerdì» (una sola `add_note`, scadenza = venerdì prossimo); «Che note ho?» (`list_notes`, ordine per scadenza); «Elimina la nota 99» (errore, nessuna conferma chiesta); eliminazione di una nota vera rispondendo `n` e poi `s`; riavvio dell'assistente con le note ancora presenti; stesse note in Docker; `/docs` nel browser. Esiti nel README; se il modello sbaglia, annotare il punto esatto. Commit `docs: registra nel README la prova reale delle note`.
- [ ] **Step 5:** con l'ok dell'utente: merge `--no-ff` in `developer`, test sul risultato, push di `developer`, eliminazione del branch; aggiornare la memoria di progetto.
