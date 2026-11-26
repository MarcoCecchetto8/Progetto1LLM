# Back-end delle chat — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** servizio HTTP `backend_service/` (porta 8002) che gestisce le chat, le salva in PostgreSQL e inoltra le domande all'agente dello step 6, in JSON e in SSE, con la conferma delle eliminazioni tenuta nel back-end.

**Architecture:** FastAPI sincrono come gli altri servizi. Archivio `ChatStore` con implementazione PostgreSQL (psycopg 3, SQL a mano) e implementazione in memoria per i test, provate dalla stessa batteria. Il back-end parla con l'agente solo via HTTP, tramite un client leggero estratto da `assistant/agent_client.py` e condiviso con la CLI.

**Tech Stack:** Python 3.14, FastAPI 0.162.2, uvicorn 0.54.0, httpx 0.28.1, psycopg[binary] 3.3.9, PostgreSQL `postgres:18.6-alpine` in Docker Compose, pytest 9.1.1.

**Spec:** `docs/superpowers/specs/2026-11-23-backend-chat-design.md` (leggerla insieme al piano: tabelle degli endpoint 7 e degli errori 7.4).

## Global Constraints

- Lavoro sul branch `feature/backend-chat` creato da `developer`; un commit per task, Conventional Commits in italiano, staging selettivo, `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` in fondo al messaggio.
- Comandi dalla radice con il venv: `.venv/Scripts/python.exe -m pytest` (controllare l'exit code).
- Non leggere né toccare `lezione-03/`.
- `backend_service` non importa LangChain, LangGraph, MCP né `agent_service`, neanche indirettamente.
- Codice sincrono, moduli piccoli, testi per l'utente in italiano, JSON con `application/json; charset=utf-8`.
- Errori come `{codice, messaggio}`; codici e testi esattamente quelli della tabella 7.4 della spec.
- Titolo predefinito `"Nuova chat"`; titolo dalla prima domanda: una riga, massimo 60 caratteri con `…`; titolo passato alla creazione: ripulito, massimo 100 caratteri.
- Dipendenza nuova solo `psycopg[binary]==3.3.9` in `requirements.txt`.
- Nessun container del back-end, nessuna modifica a `Dockerfile` né ai servizi `notes`/`agent`/`app` di `compose.yaml` (step 9).
- La CLI non cambia comportamento: tutti i test esistenti restano verdi.

## Review Focus

- Decisioni con chiavi stringa (`{"3": true}` arriva così dal JSON) o con id mancanti/in più → coercizione a intero e 422 `decisioni_non_valide` con gli id attesi; la conferma resta in attesa (test in Task 4).
- Agente che chiude la connessione a metà stream senza `fine` → evento `errore` `agente_non_raggiungibile`, nulla salvato, chat di nuovo libera per un altro invio (test in Task 5).
- Testo con accenti, emoji e a capo → identico dopo il salvataggio in JSONB/TEXT; titolo su una riga sola (test nella batteria dell'archivio, Task 2).
- Chat eliminata mentre il suo turno è in corso → nulla salvato, 404 `chat_non_trovata` (evento `errore` in streaming), riga nei log (test in Task 4 e 5).
- PostgreSQL spento dopo l'avvio → 503 `database_non_raggiungibile` su ogni endpoint, controlli dello stream compresi, e `/stato` 503 (test in Task 3).

---

### Task 1: Client HTTP leggero dell'agente

**Files:**
- Create: `assistant/agent_http.py`
- Modify: `assistant/agent_client.py`
- Test: `tests/test_agent_http.py` (nuovo), `tests/test_agent_client.py` (solo import se serve)

**Interfaces:**
- Produces (in `assistant/agent_http.py`, che importa solo libreria standard e `httpx`):
  - `UNAVAILABLE: str` (testo attuale, invariato)
  - `class AgentUnavailable(Exception)`
  - `class AgentRequestError(Exception)` con `__init__(self, code: str, message: str, status: int | None = None)` e attributi `code`, `message`, `status` (codice HTTP della risposta dell'agente; `None` per un errore arrivato come evento SSE)
  - `parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]`, `_sse_lines(chunks)`, `error_from(response: httpx.Response) -> AgentRequestError` (imposta `status=response.status_code`)
  - `class AgentHTTPClient` con `__init__(base_url: str, transport: httpx.BaseTransport | None = None)`, `status() -> dict`, `turn(payload: dict) -> dict` (`POST /chat`, corpo JSON se 200, altrimenti `error_from`), `stream_turn(payload: dict) -> Iterator[tuple[str, dict]]`, `close()`, e `_request` protetto; errori di trasporto → `AgentUnavailable(UNAVAILABLE)`; timeout come oggi (`connect 10 s`, lettura senza limite).
- `assistant/agent_client.py`: `class AgentClient(AgentHTTPClient)` aggiunge `prompts()`, `get_prompt()` e la traduzione in `MCPPromptError`/`MCPConnectionError`; riesporta `UNAVAILABLE`, `AgentUnavailable`, `AgentRequestError`, `parse_sse` (gli import esistenti di CLI e test continuano a funzionare); `LocalAgentService` resta lì.

- [ ] **Step 1: creare il branch** `git switch -c feature/backend-chat` da `developer` pulito.
- [ ] **Step 2: test che falliscono** in `tests/test_agent_http.py`:
  - `test_import_is_light`: in un sottoprocesso `python -c "import sys, assistant.agent_http; bad=[m for m in sys.modules if m.split('.')[0] in ('langchain_core','langgraph','mcp','fastmcp','langchain_mcp_adapters','openai')]; print(bad); sys.exit(1 if bad else 0)"` → exit code 0.
  - `test_turn_returns_json_body`: `MockTransport` che verifica `request.url.path == "/chat"` e il corpo inviato, risponde 200 `{"esito": "completato", "risposta": "ok"}` → `turn(...)` restituisce quel dict.
  - `test_turn_error_keeps_status`: risposta 503 `{"codice": "modello_non_raggiungibile", "messaggio": "LM Studio…"}` → `AgentRequestError` con `code`, `message` e `status == 503`.
  - `test_turn_connect_error_is_unavailable`: transport che solleva `httpx.ConnectError` → `AgentUnavailable`.
- [ ] **Step 3: eseguire** `.venv/Scripts/python.exe -m pytest tests/test_agent_http.py -v` → FAIL (modulo assente).
- [ ] **Step 4: implementare** spostando il codice esistente (non riscriverlo) e aggiungendo `turn` e `status` in `AgentRequestError`.
- [ ] **Step 5: eseguire** `.venv/Scripts/python.exe -m pytest` → tutti verdi (i test di CLI, main e client compresi).
- [ ] **Step 6: commit** `refactor(cli): client HTTP leggero dell'agente condiviso` con `assistant/agent_http.py`, `assistant/agent_client.py`, `tests/test_agent_http.py` (e `tests/test_agent_client.py` se toccato).

### Task 2: Archivio delle chat (PostgreSQL e memoria) e database in Compose

**Files:**
- Create: `backend_service/__init__.py`, `backend_service/store.py`, `tests/memory_chat_store.py`, `tests/test_chat_store.py`
- Modify: `requirements.txt`, `compose.yaml`, `.env.example`

**Interfaces:**
- Produces (in `backend_service/store.py`):
  - `DEFAULT_TITLE = "Nuova chat"`, `MAX_TITLE = 100`, `AUTO_TITLE = 60`
  - `clean_title(title: str | None) -> str` (vuoto/None → `DEFAULT_TITLE`; spazi ripuliti; oltre 100 → `ValueError`)
  - `title_from(question: str) -> str` (spazi e a capo ridotti a uno spazio; oltre 60 → primi 59 caratteri + `…`)
  - `class StoreUnavailable(Exception)`
  - `class ChatStore` (classe base con i metodi sotto che sollevano `NotImplementedError`):
    - `create_chat(title: str | None = None) -> dict` → `{id, titolo, creata, ultimo_messaggio}`
    - `list_chats() -> list[dict]` (stesse chiavi; ordine `COALESCE(ultimo_messaggio, creata) DESC, id DESC`)
    - `get_chat(chat_id: int) -> dict | None` → in più `cronologia: list[dict]`, `riassunto: str`, `in_sospeso: dict | None`
    - `get_messages(chat_id: int) -> list[dict]` → `{id, ruolo, contenuto, strumenti, righe, creato}` in ordine di `id`
    - `delete_chat(chat_id: int) -> bool`
    - `set_pending(chat_id: int, pending: dict | None) -> bool`
    - `save_turn(chat_id: int, question: str, answer: str, tools: list[dict], lines: list[str], history: list[dict], summary: str) -> tuple[dict, dict] | None`: in una transazione inserisce i due messaggi (utente con `strumenti=[]`, `righe=[]`), sostituisce cronologia e riassunto, svuota `in_sospeso`, imposta `ultimo_messaggio` all'istante del salvataggio, cambia il titolo in `title_from(question)` solo se è `DEFAULT_TITLE`; `None` se la chat non esiste
    - `ping() -> None`
  - `class PostgresChatStore(ChatStore)` con `__init__(url: str, search_path: str | None = None)`: crea le tabelle della spec 6 (con la colonna `righe`) e l'indice con `CREATE … IF NOT EXISTS`; una connessione per operazione (`psycopg.connect(url, row_factory=dict_row, options=f"-c search_path={search_path}" se dato)`), JSON con `psycopg.types.json.Jsonb`; ogni `psycopg.OperationalError` → `StoreUnavailable`. Istanti `datetime` con fuso (UTC).
- `tests/memory_chat_store.py`: `class MemoryChatStore(ChatStore)` con lo stesso comportamento, più `down: bool` (se vero ogni metodo solleva `StoreUnavailable`) per i test del Task 3. Copie profonde in ingresso e in uscita.

- [ ] **Step 1: dipendenza** `psycopg[binary]==3.3.9` in `requirements.txt` (riga con commento: driver PostgreSQL sincrono, ruote binarie senza compilazione); `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt` → installato. Se non esiste la ruota per Python 3.14 fermarsi e riferire.
- [ ] **Step 2: Compose ed esempio** — servizio `db` in `compose.yaml`: `image: postgres:18.6-alpine`, `env_file: .env`, volume con nome `pgdata` montato su `/var/lib/postgresql`, `ports: ["127.0.0.1:5432:5432"]`, healthcheck `pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}`; `volumes: pgdata:` in fondo. In `.env.example`, con commenti: `POSTGRES_USER=lab`, `POSTGRES_PASSWORD=cambiami`, `POSTGRES_DB=lab`, `DATABASE_URL=postgresql://lab:cambiami@127.0.0.1:5432/lab`, `# BACKEND_AGENT_URL=http://127.0.0.1:8001`, `# TEST_DATABASE_URL=` (spiegato: attiva i test sul PostgreSQL vero, usano uno schema temporaneo). Verifica: `docker compose config` senza errori.
- [ ] **Step 3: test che falliscono** in `tests/test_chat_store.py`, con una fixture `store` parametrizzata: `memory` sempre; `postgres` solo se `TEST_DATABASE_URL` è impostata (altrimenti `pytest.skip`), che crea uno schema `test_<uuid hex>`, costruisce `PostgresChatStore(url, search_path=schema)` e alla fine fa `DROP SCHEMA … CASCADE`. Test:
  - `test_create_and_get`: chat nuova con titolo `"Nuova chat"`, `ultimo_messaggio is None`, `cronologia == []`, `riassunto == ""`, `in_sospeso is None`.
  - `test_create_with_title_cleaned` (`"  Python  "` → `"Python"`) e `test_create_title_too_long` (101 caratteri → `ValueError`).
  - `test_list_orders_by_activity`: tre chat; un turno salvato sulla prima → è in cima; a parità senza messaggi prima l'id più alto.
  - `test_save_turn`: due messaggi nell'ordine utente/assistente con strumenti e righe; cronologia e riassunto sostituiti; `in_sospeso` svuotato; `ultimo_messaggio` valorizzato; titolo = `title_from(domanda)`; un secondo turno non cambia più il titolo.
  - `test_save_turn_unicode`: `"è «x» 😀\nriga"` identico in lettura; titolo `"è «x» 😀 riga"`.
  - `test_save_turn_missing_chat` → `None`.
  - `test_pending_roundtrip`: `set_pending(id, {"sospeso": {...}, "domanda": "…", "conferme": [{"id_nota": 3, "domanda": "…"}]})` riletto uguale; `set_pending(id, None)`; chat inesistente → `False`.
  - `test_delete_cascades`: dopo `delete_chat` → `get_chat` è `None`, `get_messages` è `[]`, seconda `delete_chat` → `False`.
  - `test_persists_after_restart` (solo `postgres`): nuovo `PostgresChatStore` sullo stesso schema vede chat e messaggi.
  - `test_title_from_rules`: 60 caratteri invariati, 61 → 59 + `…`, a capo e tab → spazi singoli.
  - `test_unreachable_database` (solo unitario, senza server): `PostgresChatStore("postgresql://x:y@127.0.0.1:1/z")` → `StoreUnavailable`.
- [ ] **Step 4: eseguire** `.venv/Scripts/python.exe -m pytest tests/test_chat_store.py -v` → FAIL.
- [ ] **Step 5: implementare** `backend_service/store.py` e `tests/memory_chat_store.py`.
- [ ] **Step 6: verifiche** — senza database: `.venv/Scripts/python.exe -m pytest tests/test_chat_store.py -v` → memoria PASS, postgres SKIPPED. Con database: `.env` con le variabili dell'esempio (chiedere all'utente se `.env` va completato a mano: non sovrascriverlo), `docker compose up -d db`, poi `TEST_DATABASE_URL=postgresql://lab:cambiami@127.0.0.1:5432/lab .venv/Scripts/python.exe -m pytest tests/test_chat_store.py -v` → tutto PASS. Riportare entrambi gli esiti.
- [ ] **Step 7: commit** `feat(backend): archivio delle chat in PostgreSQL e database in Compose`.

### Task 3: App del back-end — chat, stato, errori, avvio

**Files:**
- Create: `backend_service/errors.py`, `backend_service/schemas.py`, `backend_service/app.py`, `backend_service/__main__.py`, `tests/test_backend_api.py`

**Interfaces:**
- Consumes: `ChatStore`, `StoreUnavailable`, `clean_title` (Task 2); `AgentHTTPClient`, `AgentUnavailable` (Task 1); `MemoryChatStore`.
- Produces:
  - `backend_service/errors.py`: `class BackendError(Exception)` con `status`, `code`, `message`; costanti dei testi della tabella 7.4 (`AGENT_DOWN`, `DB_DOWN`, `BUSY`, `PENDING`, `NO_PENDING`) e `chat_not_found(chat_id: int) -> BackendError`.
  - `backend_service/schemas.py`: `CreateChat{titolo: str | None = None}`, `ChatSummary{id, titolo, creata, ultimo_messaggio}`, `MessageOut{id, ruolo, contenuto, strumenti, righe, creato}`, `Confirmation{id_nota: int, domanda: str}`, `ChatDetail(ChatSummary){messaggi: list[MessageOut], conferme: list[Confirmation]}`, `SendMessage{testo: str}` (vuoto dopo `strip` → errore di validazione), `ConfirmRequest{decisioni: dict[int, bool]}`, `TurnResult{esito: Literal["completato", "conferma_richiesta"], domanda: MessageOut | None = None, risposta: MessageOut | None = None, righe: list[str] = [], conferme: list[Confirmation] = []}`, `ErrorBody{codice, messaggio}`.
  - `backend_service/app.py`: `create_app(store: ChatStore, agent: AgentHTTPClient) -> FastAPI` con titolo «Back-end delle chat», risposta predefinita UTF-8 (come `UTF8JSONResponse` dell'agente, ridefinita qui), gestori per `BackendError`, `StoreUnavailable` (503 `database_non_raggiungibile`) e `RequestValidationError` (422 con charset); endpoint `POST /chats` (201), `GET /chats`, `GET /chats/{id}`, `DELETE /chats/{id}` (204), `GET /stato`; `conferme` del dettaglio prese da `in_sospeso["conferme"]`; log INFO `[backend] chat N creata` / `[backend] chat N eliminata` (logger `backend_service`). Gli endpoint dei messaggi li aggiungono i Task 4 e 5.
  - `backend_service/__main__.py`: `main()` con `--host 127.0.0.1`, `--port 8002`, `--quiet`; `load_dotenv()`; `DATABASE_URL` mancante o database irraggiungibile → messaggio su stderr («Il database non risponde all'indirizzo …: avvia PostgreSQL con docker compose up -d db.» senza la password nell'URL) ed exit 1; agente da `BACKEND_AGENT_URL` (predefinito `http://127.0.0.1:8001`); log come `notes_service/__main__.py`.

- [ ] **Step 1: test che falliscono** in `tests/test_backend_api.py` con `TestClient(create_app(MemoryChatStore(), AgentHTTPClient("http://agente", transport=MockTransport(handler))))`:
  - `test_create_list_get_delete`: 201 con `id` e `"Nuova chat"`; elenco con la chat; dettaglio con `messaggi == []` e `conferme == []`; delete 204; poi get 404 `{"codice": "chat_non_trovata", "messaggio": "La chat 1 non esiste."}`; delete di nuovo 404.
  - `test_create_title_too_long_is_422`.
  - `test_json_charset`: `content-type` di `GET /chats` contiene `charset=utf-8`.
  - `test_status_ok` (agente 200 con parti raggiungibili → 200, `database.raggiungibile` e `agente.raggiungibile` veri, `agente.dettagli` = corpo dell'agente); `test_status_agent_down` (`ConnectError` → 503, `agente.raggiungibile` falso, messaggio = `AGENT_DOWN`); `test_status_agent_degraded` (agente 503 con il modello non raggiungibile → 503); `test_status_database_down` (`store.down = True` → 503).
  - `test_database_down_is_503`: `store.down = True` → `GET /chats` e `POST /chats` 503 `database_non_raggiungibile` con il testo della spec.
  - `test_openapi_lists_paths`: `/openapi.json` contiene `/chats`, `/chats/{chat_id}`, `/stato`.
  - `test_backend_import_is_light`: come il test del Task 1, sottoprocesso che importa `backend_service.app` e `backend_service.__main__`.
  - `test_main_exits_without_database`: con `monkeypatch` di `DATABASE_URL` verso `127.0.0.1:1` e `sys.argv`, `main()` → `SystemExit(1)` e stderr con «Il database non risponde» e senza la password.
- [ ] **Step 2: eseguire** `.venv/Scripts/python.exe -m pytest tests/test_backend_api.py -v` → FAIL.
- [ ] **Step 3: implementare** i quattro moduli.
- [ ] **Step 4: eseguire** `.venv/Scripts/python.exe -m pytest` → tutto verde.
- [ ] **Step 5: commit** `feat(backend): API delle chat, stato e avvio`.

### Task 4: Invio di un messaggio e conferma in JSON

**Files:**
- Create: `backend_service/turns.py`, `tests/test_backend_turns.py`
- Modify: `backend_service/app.py`

**Interfaces:**
- Consumes: Task 1–3.
- Produces (in `backend_service/turns.py`):
  - `class ChatTurns` con `__init__(store: ChatStore)`:
    - `busy(chat_id: int)` context manager: insieme in memoria protetto da `threading.Lock`; chat già occupata → `BackendError(409, "turno_in_corso", BUSY)`; libera sempre all'uscita.
    - `message_payload(chat_id: int, text: str) -> tuple[dict, str]`: chat assente → 404; `in_sospeso` presente → 409 `conferma_in_attesa`; restituisce il corpo per l'agente `{"messaggi": [{"ruolo": "utente", "contenuto": text}], "cronologia": …, "riassunto": …}` e la domanda.
    - `confirm_payload(chat_id: int, decisions: dict[int, bool]) -> tuple[dict, str]`: chat assente → 404; nessuna conferma → 409 `nessuna_conferma`; chiavi diverse dagli `id_nota` in attesa → 422 `decisioni_non_valide` con messaggio «Servono le decisioni per le note: 3, 5.»; corpo `{"ripresa": {"sospeso": …, "decisioni": {str(id): bool}}}` e la domanda salvata in `in_sospeso`.
    - `finish(chat_id: int, question: str, body: dict) -> dict`: dal corpo finale dell'agente al corpo `TurnResult` (dict). `completato` → `store.save_turn(...)` con `risposta`, `strumenti`, `righe`, `cronologia`, `riassunto`; `conferma_richiesta` → `store.set_pending(chat_id, {"sospeso": body["sospeso"], "domanda": question, "conferme": body["conferme"]})`, risposta con le sole `conferme`; chat sparita (`None`/`False`) → log `[backend] chat N eliminata durante il turno: risposta non salvata` e `chat_not_found`; chiavi mancanti o `esito` sconosciuto → `BackendError(502, "risposta_agente_non_valida", …)`.
  - `agent_error(error: AgentUnavailable | AgentRequestError) -> BackendError`: non raggiungibile → 503 `agente_non_raggiungibile` con `AGENT_DOWN`; errore dell'agente → stesso `status` (502 se `None`), `code` e `message`.
  - Endpoint `POST /chats/{chat_id}/messaggi` e `POST /chats/{chat_id}/conferma` in `app.py`: `busy` → payload → `agent.turn` → `finish`; log INFO `[backend] invio chat N`/`[backend] conferma chat N` con esito e durata.

- [ ] **Step 1: test che falliscono** in `tests/test_backend_turns.py` (agente simulato con `MockTransport` che registra i corpi ricevuti):
  - `test_send_completed_saves_both`: l'agente risponde `completato` con `risposta`, `strumenti=[{nome:"get_current_time",…}]`, `righe=["[revisore] ok"]`, `cronologia`, `riassunto` → risposta 200 con `domanda` e `risposta` salvati; `GET` della chat mostra i due messaggi e il titolo dalla domanda; il corpo inviato all'agente ha la cronologia vuota.
  - `test_second_turn_sends_saved_history`: il secondo invio manda all'agente `cronologia` e `riassunto` restituiti dal primo.
  - `test_agent_unreachable_saves_nothing`: `ConnectError` → 503 `agente_non_raggiungibile`; chat senza messaggi; un nuovo invio dopo funziona (chat libera).
  - `test_agent_error_passthrough`: agente 504 `modello_timeout` → 504 stesso codice e messaggio; nulla salvato.
  - `test_invalid_agent_reply`: agente 200 `{"esito": "boh"}` → 502 `risposta_agente_non_valida`.
  - `test_empty_text_is_422` e `test_missing_chat_is_404`.
  - `test_confirmation_flow`: primo invio → agente `conferma_richiesta` con `conferme=[{"id_nota": 3, "domanda": "Elimino la nota 3…?"}]` e `sospeso={"x": 1}` → risposta senza la chiave `sospeso` da nessuna parte (`"sospeso" not in json.dumps(body)`); `GET` mostra `conferme` e nessun messaggio; nuovo invio → 409 `conferma_in_attesa`; `POST /conferma` `{"decisioni": {"3": true}}` → all'agente arriva `{"ripresa": {"sospeso": {"x": 1}, "decisioni": {"3": true}}}`; agente `completato` → salvati domanda originale e risposta; `conferme` vuote.
  - `test_confirmation_wrong_ids`: `{"decisioni": {"4": true}}` e `{"decisioni": {}}` → 422 `decisioni_non_valide` con «3» nel messaggio; conferma ancora in attesa.
  - `test_confirmation_error_keeps_pending`: alla ripresa l'agente è irraggiungibile → 503 e `conferme` ancora presenti; ripetendo la conferma funziona.
  - `test_second_suspension_replaces_pending`: alla ripresa l'agente chiede un'altra conferma (nota 5) → `conferme` = solo la nota 5, domanda invariata.
  - `test_no_pending_is_409`.
  - `test_busy_chat_is_409`: con `ChatTurns.busy(id)` tenuto aperto nel test (accesso tramite `app.state.turns`), un invio → 409 `turno_in_corso`; un'altra chat risponde normalmente.
  - `test_chat_deleted_during_turn`: l'handler dell'agente elimina la chat dallo store prima di rispondere → 404 `chat_non_trovata`, nessun messaggio salvato.
  - `test_integration_with_real_agent_api`: agente vero `agent_service.app.create_app(make_agent(clock_graph()))` (helper di `tests/test_agent_api.py`) in un `TestClient`; il back-end usa `AgentHTTPClient("http://testserver", transport=agent_test_client._transport)`; invio «Che ore sono?» → `completato`, risposta «Sono le 14:32.», `strumenti[0]["nome"] == "get_current_time"`; secondo invio accettato dall'agente con la cronologia salvata.
- [ ] **Step 2: eseguire** `.venv/Scripts/python.exe -m pytest tests/test_backend_turns.py -v` → FAIL.
- [ ] **Step 3: implementare** `turns.py` e i due endpoint (il `ChatTurns` dell'app in `app.state.turns`).
- [ ] **Step 4: eseguire** `.venv/Scripts/python.exe -m pytest` → tutto verde.
- [ ] **Step 5: commit** `feat(backend): invio dei messaggi e conferma delle eliminazioni`.

### Task 5: Streaming SSE dell'invio e della conferma

**Files:**
- Create: `backend_service/streaming.py`, `tests/test_backend_stream.py`
- Modify: `backend_service/app.py`

**Interfaces:**
- Consumes: `ChatTurns`, `agent_error` (Task 4); `AgentHTTPClient.stream_turn` (Task 1).
- Produces (in `backend_service/streaming.py`):
  - `KEEPALIVE_SECONDS = 0.5`, `KEEPALIVE = ": \n\n"`, `SSE_MEDIA_TYPE = "text/event-stream; charset=utf-8"`, `sse(name: str, data: dict) -> str` (JSON con `ensure_ascii=False`).
  - `stream_turn_events(turns: ChatTurns, agent: AgentHTTPClient, chat_id: int, payload: dict, question: str, release: Callable[[], None])` → generatore asincrono di stringhe SSE. Un thread legge `agent.stream_turn(payload)` e mette gli eventi in una coda: gli eventi diversi da `fine`/`errore` si inoltrano invariati; a `fine` il **thread** chiama `turns.finish(...)` (quindi il salvataggio avviene anche se il client se n'è andato) e mette il `fine` del back-end (il `TurnResult`); `errore` dell'agente → inoltrato; `AgentUnavailable`, `AgentRequestError`, `BackendError`, `StoreUnavailable` → evento `errore` `{codice, messaggio}`; stream finito senza `fine` né `errore` → evento `errore` `agente_non_raggiungibile`. Prima di ogni evento il thread controlla un `threading.Event` di annullamento: se il client è andato via (il `finally` del generatore asincrono lo imposta), esce dal `for`, il che chiude lo stream verso l'agente. `release()` (che libera `busy`) si chiama nel `finally` del thread. Keepalive quando la coda è vuota da `KEEPALIVE_SECONDS`, come in `agent_service/app.py::stream_events`.
  - Endpoint `POST /chats/{chat_id}/messaggi/stream` e `POST /chats/{chat_id}/conferma/stream`: controlli (404, 409, 422, database) e presa di `busy` **prima** di restituire lo `StreamingResponse` (errori come normali risposte HTTP); `busy` si prende con un metodo esplicito `ChatTurns.acquire(chat_id)`/`release(chat_id)` (aggiungerli accanto al context manager del Task 4, che li usa).

- [ ] **Step 1: test che falliscono** in `tests/test_backend_stream.py` (agente simulato che risponde con un corpo SSE già pronto; analisi degli eventi con `assistant.agent_http.parse_sse`):
  - `test_stream_forwards_and_saves`: eventi agente `ragionamento`, `strumento`, `esito_strumento`, `riga`, `risposta`, `fine(completato…)` → il client riceve i primi cinque invariati e un `fine` uguale al corpo di `POST /messaggi` (con `domanda.id` e `risposta.id`, senza `cronologia`); la chat contiene i due messaggi.
  - `test_stream_confirmation_hides_suspended`: `fine(conferma_richiesta, sospeso…)` → `fine` del back-end con solo `conferme`; `"sospeso"` assente da tutto il corpo; `in_sospeso` salvato; `POST /conferma/stream` riprende e salva.
  - `test_stream_agent_error_event`: l'agente manda `errore {codice: "modello_timeout", …}` → inoltrato; nulla salvato.
  - `test_stream_agent_drops_without_fine`: corpo con solo `risposta` → ultimo evento `errore` `agente_non_raggiungibile`; nulla salvato; un nuovo invio sulla stessa chat è accettato.
  - `test_stream_prechecks_are_http_errors`: chat assente → 404 JSON; conferma in attesa → 409; testo vuoto → 422; database giù → 503 (nessuno stream aperto).
  - `test_stream_chat_deleted_during_turn` → evento `errore` `chat_non_trovata`.
  - `test_saved_when_client_leaves_after_fine`: chiamare direttamente `stream_turn_events` con un agente finto la cui iterazione mette `fine(completato)`; chiudere il generatore asincrono subito dopo il primo `yield` (`aclose()` in `asyncio.run`) e aspettare il thread (esporre il thread o attendere `release` con un `threading.Event` nel test) → turno salvato.
  - `test_cancel_before_fine_saves_nothing`: agente finto il cui iteratore produce `risposta`, poi attende un `threading.Event` del test prima di produrre `fine`; il test chiude il generatore dopo il primo evento, poi sblocca l'iteratore → nessun salvataggio, `release` chiamata, iteratore dell'agente chiuso (`GeneratorExit` registrato o `close()` chiamato).
- [ ] **Step 2: eseguire** `.venv/Scripts/python.exe -m pytest tests/test_backend_stream.py -v` → FAIL.
- [ ] **Step 3: implementare** `streaming.py`, `acquire`/`release` e i due endpoint.
- [ ] **Step 4: eseguire** `.venv/Scripts/python.exe -m pytest` → tutto verde, senza thread appesi (la sessione pytest termina).
- [ ] **Step 5: commit** `feat(backend): streaming SSE di invio e conferma`.

### Task 6: Documentazione e prova di avvio

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: README** — sezione «Back-end delle chat»: prerequisiti (`docker compose up -d db`, variabili `DATABASE_URL`, `POSTGRES_*`, `BACKEND_AGENT_URL`, `TEST_DATABASE_URL`), avvio in tre terminali PowerShell (`python -m agent_service`, `python -m backend_service`), `/docs`, tabella degli endpoint, esempi PowerShell (`Invoke-RestMethod` per creare una chat e inviare `{"testo": "Che ore sono?"}`, `curl.exe -N` per lo stream), comportamento con agente spento (503, nulla salvato), salvataggio a fine turno (scostamento dall'ordine della slide, motivato), conferma delle eliminazioni, limiti (un turno per chat, un solo processo, messaggi dell'agente che nominano la CLI inoltrati invariati, nessun container del back-end fino allo step 9), test con PostgreSQL vero. Sezione «Prova reale del back-end» con le voci della spec 10, esiti da compilare dopo la prova.
- [ ] **Step 2: CLAUDE.md** — in «Struttura e comandi»: voce `backend_service/` (`store.py`, `turns.py`, `streaming.py`, `schemas.py`, `errors.py`, `app.py`, `__main__.py`), `assistant/agent_http.py`, comando `python -m backend_service`, test con `TEST_DATABASE_URL`; in «Obiettivo»: la CLI conserva la cronologia per la sessione, le chat del back-end sono salvate in PostgreSQL; in «Confini»: back-end fatto, front-end allo step 8.
- [ ] **Step 3: prova di avvio senza modello** — con `docker compose up -d db`: `python -m backend_service` parte; `Invoke-RestMethod -Method Post http://127.0.0.1:8002/chats` crea una chat; con l'agente spento l'invio dà 503 `agente_non_raggiungibile`; riavvio del back-end e la chat è ancora in elenco; `http://127.0.0.1:8002/docs` risponde 200. Riportare comandi ed esiti; la prova con LM Studio resta all'utente (o a una sessione dedicata) ed è annotata come da fare.
- [ ] **Step 4: `.venv/Scripts/python.exe -m pytest`** → tutto verde (riportare il numero dei test).
- [ ] **Step 5: commit** `docs(backend): avvio, endpoint e limiti del back-end`.
