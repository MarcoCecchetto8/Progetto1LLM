# Agente come servizio HTTP — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** l'agente (grafo, strumenti MCP, note) diventa un servizio FastAPI senza stato con `/chat`, `/chat/stream` (SSE), `/stato` e `/prompts`; la CLI diventa un suo client, conserva cronologia e riassunto, mantiene streaming e conferma delle eliminazioni.

**Architecture:** il cuore resta in `assistant/` (grafo, strumenti, note); la conferma delle eliminazioni diventa un nodo del grafo che sospende il turno. Nuovo pacchetto `agent_service/`: conversione dei messaggi, esecuzione del turno (riusa `stream_turn` con un osservatore che produce eventi), errori, app FastAPI, avvio. La CLI usa `assistant/agent_client.py` (HTTP + SSE + avvio automatico) e la sua `TurnView` di oggi.

**Tech Stack:** Python, FastAPI 0.162.2, uvicorn 0.54.0, httpx 0.28.1, LangGraph 1.2.17, langchain-core 1.7.0, pytest. Nessuna nuova dipendenza.

**Spec:** `docs/superpowers/specs/2026-11-17-agente-servizio-design.md`

## Global Constraints

- Branch `feature/agente-servizio` da `developer`; Conventional Commits in italiano con la riga `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; `git status`, controllo del diff, staging selettivo; nessun push; mai `.env`. Non leggere né toccare `lezione-03/`.
- Test senza LM Studio; suite completa verde (`.venv/Scripts/python.exe -m pytest`, controllare l'exit code) prima di ogni commit. Test esistenti adattati solo dove cambia l'interfaccia.
- Nessuna nuova dipendenza; SSE scritto a mano: ogni evento è `event: <nome>\ndata: <json>\n\n`, JSON con `ensure_ascii=False`, media type `text/event-stream; charset=utf-8`.
- Nomi degli eventi (spec 5.3): `ragionamento`, `risposta`, `strumento`, `esito_strumento`, `riga`, `fine`, `errore`.
- Ruoli dei messaggi JSON: `utente`, `assistente`, `strumento`. Esiti: `completato`, `conferma_richiesta`.
- Codici e stati HTTP degli errori: tabella della spec 5.6, copiati esatti. Testi:
  - `modello_non_raggiungibile` 503: «LM Studio non è raggiungibile all'indirizzo {base_url}. Controlla che sia attivo e riprova.»
  - `modello_timeout` 504: «Il modello non ha risposto entro {timeout:g} secondi. Riprova.»
  - `contesto_pieno` 422: «Il contesto del modello è pieno: usa 'clear' per svuotare la cronologia.»
  - `errore_modello` 502: «Errore dell'API del modello: {errore}»
  - `strumenti_non_raggiungibili` 503: «Il server degli strumenti non risponde: riavvia l'agente (in locale basta riavviare l'assistente).»
  - `note_non_raggiungibili` 503: «Il servizio delle note non risponde: riavvia l'agente (in locale basta riavviare l'assistente).»
  - `risposta_vuota` 502: «Il modello non ha dato una risposta: riprova.»
  - `prompt_rifiutato` 422: «Il server ha rifiutato il prompt: {errore}»
  - `errore_imprevisto` 500: «Errore imprevisto: {errore}. Riprova o usa 'clear'.»
  - CLI, agente irraggiungibile: «L'agente non risponde: esci e riavvia l'assistente.»
- Porta predefinita dell'agente **8001** (8000 è delle note). Variabile `AGENT_SERVICE_URL` (vuota = avvio automatico).
- Testo delle domande di conferma invariato: `f"Elimino la nota {id} «{testo}» · {due_phrase}? [s/N] "`; risposte sì: `s`, `si`, `sì` (senza maiuscole/spazi).
- Il messaggio di sistema non viaggia mai nelle risposte né nelle richieste.

## Review Focus

1. **Chiudere la CLI non lascia processi orfani** (agente, servizio note sulla 8000, server MCP): su Windows `terminate()` uccide senza `finally`, quindi il servizio note figlio resterebbe vivo e il riavvio direbbe «porta 8000 già in uso». Chiusura con `CTRL_BREAK_EVENT` su Windows (uvicorn 0.54 gestisce SIGBREAK) e SIGTERM altrove, `kill` solo dopo 10 s. Test di integrazione nel Task 6.
2. **Ctrl+C a metà turno, poi una nuova domanda**: l'agente rilascia il lock e il turno successivo funziona. Il cliente che se ne va imposta l'annullamento. Test nei Task 3 e 4.
3. **Cronologia malformata dal chiamante** (ruolo sconosciuto, `strumento` senza `id_chiamata`, `sospeso` manomesso, `ripresa` insieme a `messaggi`): risposta 422 con messaggio, mai 500. Test nei Task 1 e 4.
4. **Testo italiano e a capo negli eventi** («è», «»», `\n`, emoji ⚠): arrivano intatti fino al terminale, anche su Windows. Test nei Task 4 e 6.
5. **Turno lungo** (router, modello e revisore oltre 2 minuti): il client non deve tagliarlo per un timeout di lettura (`httpx` di default è 5 s). Test nel Task 6.

---

### Task 1: Messaggi JSON ↔ LangChain

**Files:**
- Create: `agent_service/__init__.py` (docstring «Agente come servizio HTTP.»), `agent_service/messages.py`
- Test: `tests/test_agent_messages.py`

**Interfaces:**
- Produces:
  - `class ToolCall(BaseModel)`: `id: str`, `nome: str`, `argomenti: dict`
  - `class Message(BaseModel)`: `ruolo: Literal["utente", "assistente", "strumento"]`, `contenuto: str = ""`, `chiamate: list[ToolCall] = []`, `id_chiamata: str | None = None`, `nome: str | None = None`, `errore: bool = False`. Validatore: `strumento` richiede `id_chiamata` e `nome`; `chiamate` solo per `assistente`.
  - `to_langchain(messages: list[Message]) -> list[AnyMessage]` (utente → `HumanMessage`, assistente → `AIMessage` con `tool_calls`, strumento → `ToolMessage` con `status="error"` se `errore`)
  - `from_langchain(messages: list[AnyMessage]) -> list[Message]` (scarta `SystemMessage`; contenuto non stringa → testo dei blocchi `text` uniti)
  - `dump_state_messages(messages) -> list[dict]` / `load_state_messages(data: list[dict]) -> list[AnyMessage]`: senza perdite (id, `additional_kwargs` come il marcatore `review_feedback`), con `messages_to_dict`/`messages_from_dict` di langchain-core; `load_state_messages` solleva `ValueError("stato sospeso non valido")` su dati non leggibili. Servono per lo stato sospeso (opaco).

- [ ] **Step 1: test che falliscono**: andata e ritorno di utente, assistente con due chiamate, strumento con `errore=True` (`status == "error"`); `from_langchain` scarta il `SystemMessage`; `Message(ruolo="strumento", contenuto="x")` → `ValidationError`; `Message(ruolo="sistema")` → `ValidationError`; `load_state_messages(dump_state_messages([feedback_message("m")]))` conserva `is_review_feedback` e l'id; `load_state_messages([{"x": 1}])` → `ValueError`.
- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_agent_messages.py -q` → FAIL (modulo mancante).
- [ ] **Step 3:** implementare `agent_service/messages.py`.
- [ ] **Step 4:** stesso comando → PASS; suite completa verde.
- [ ] **Step 5: commit** `feat(agente): schema dei messaggi JSON e conversione LangChain`

### Task 2: Conferma delle eliminazioni come nodo del grafo

**Files:**
- Modify: `assistant/notes.py` (`build_note_tools`, nuova `build_confirmation_check`; tolto `delete_lock`)
- Modify: `assistant/graph.py` (stato, nodo `confirm`, ingresso di ripresa, decisioni ai tool)
- Modify: `assistant/__main__.py` (solo la chiamata a `build_note_tools` senza `ask_in_terminal`; la CLI in-process resta senza conferma fino al Task 7: stato intermedio accettato sul branch)
- Test: `tests/test_notes_tools.py`, `tests/test_graph.py`

**Interfaces:**
- Produces:
  - `build_note_tools(client: httpx.Client, today: Callable[[], date]) -> list[BaseTool]` (niente `confirm`). `delete_note(note_id: int, config: RunnableConfig)` legge `config["configurable"]["note_decisions"]: dict[int, bool]`: `True` → elimina come oggi; `False` → «Eliminazione della nota N annullata dall'utente.»; assente → stesso testo di annullamento e `logger.warning("[note] eliminazione della nota %s senza conferma: annullata")`. Il parametro `config` non deve comparire nello schema del tool (verificare `"config" not in tool.args`).
  - `build_confirmation_check(client: httpx.Client, today: Callable[[], date]) -> Callable[[list[dict], dict[int, bool]], list[dict]]`: per ogni chiamata `delete_note` con `note_id` intero non presente nelle decisioni (id ripetuti una volta sola) legge la nota; nota inesistente (404) → nessuna conferma; restituisce `[{"id_nota": int, "domanda": str}]` con il testo delle Global Constraints. Errore di collegamento → `NotesConnectionError` (come `_call`).
  - `State` aggiunge `decisions: NotRequired[dict[int, bool]]` e `confirmations: NotRequired[list[dict]]`.
  - `build_graph(..., confirmation_check=None)`: con `confirmation_check`:
    - `route_after_model` manda a `"confirm"` invece che a `"tools"`;
    - nodo `confirm`: `needed = confirmation_check(last.tool_calls, state.get("decisions", {}))` → `{"confirmations": needed}`; poi `END` se `needed`, altrimenti `"tools"`;
    - ingresso: da `START` un instradamento condizionale va a `"confirm"` se l'ultimo messaggio è un `AIMessage` con `tool_calls` (ripresa), altrimenti dove va oggi (summarizer o router o model);
    - `tools_node` passa `state.get("decisions", {})` ai tool come `configurable["note_decisions"]` (unendo la `configurable` esistente).
    Senza `confirmation_check` il grafo è identico a oggi.
  - Restano per ora (li toglie il Task 7): `ask_in_terminal`, `confirmation_pending`, `reset_confirmation`, `YES`.

- [ ] **Step 1: test che falliscono** (`tests/test_notes_tools.py`, con `TestClient` del servizio note come oggi):
  - `delete_note` con decisione `True` elimina, con `False` annulla (log «annullata dall'utente»), senza decisione annulla con avviso;
  - `build_confirmation_check`: una domanda per nota esistente con il testo esatto (`"Elimino la nota 1 «report» · senza scadenza? [s/N] "`), nessuna per nota inesistente, nessuna per id già deciso, una sola per id ripetuto, chiamate non `delete_note` ignorate;
  - grafo con `confirmation_check`, modello finto `add_note` + `delete_note` nello **stesso** messaggio: il turno finisce con `confirmations` non vuoto e **nessuna nota creata** (nessun `ToolMessage`);
  - ripresa: stato = messaggi del turno sospeso + `decisions={1: True}` → la nota sparisce, l'`add_note` gira una volta sola (una nota in tutto), `confirmations == []` a fine turno;
  - dopo la ripresa, il modello chiede di nuovo `delete_note` per la stessa nota (già decisa `False`) → nessuna nuova sospensione, secondo annullamento;
  - due `delete_note` in un messaggio → due conferme nella stessa sospensione.
  Sostituire i test di oggi su `confirm` (`test_delete_note_confirmed`, `_declined`, `_confirmations_are_serialized`, `test_graph_delete_declined`) con questi; i test di `ask_in_terminal` restano.
- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_notes_tools.py tests/test_graph.py -q` → FAIL.
- [ ] **Step 3:** implementare in `notes.py` e `graph.py`; aggiornare la chiamata in `assistant/__main__.py`.
- [ ] **Step 4:** stesso comando → PASS; suite completa verde (i test del grafo senza `confirmation_check` invariati).
- [ ] **Step 5: commit** `feat(note): conferma dell'eliminazione come sospensione del grafo`

### Task 3: Esecuzione del turno senza stato ed errori

**Files:**
- Create: `agent_service/errors.py`, `agent_service/turn.py`
- Test: `tests/test_agent_turn.py`

**Interfaces:**
- Consumes: `stream_turn(graph, state, view, config)` di `assistant/stream_view.py` (invariata: unico interprete del grafo), `dump_state_messages`/`load_state_messages` (Task 1), grafo del Task 2.
- Produces:
  - `errors.py`: `class AgentError(Exception)` con `status: int`, `code: str`, `message: str`; `classify(error: BaseException, settings: Settings) -> AgentError` per `openai.APITimeoutError` (prima di `APIConnectionError`), `openai.APIConnectionError`, `openai.APIError` con «context» → contesto pieno, altro `APIError`, `MCPConnectionError`, `NotesConnectionError`, qualsiasi altra → `errore_imprevisto`; `empty_answer() -> AgentError`. Testi e codici dalle Global Constraints.
  - `turn.py`:
    - `class TurnCancelled(Exception)`, `class CancelOnInterrupt(BaseCallbackHandler)` spostate da `assistant/cli.py` (stesso codice: `raise_error = True`, `on_llm_new_token` solleva se l'Event è impostato). Le definizioni in `cli.py` restano fino al Task 7.
    - `class EventRecorder`: stessa interfaccia di `TurnView` (`reasoning`, `answer`, `tool_call`, `tool_result`, `extra`, `finish`). Costruttore `EventRecorder(emit: Callable[[str, dict], None] | None = None, tools: list[dict] | None = None, lines: list[str] | None = None)`. Inoltra a `emit` gli eventi della spec 5.3 con i dati `{testo}`, `{nome, argomenti}`, `{nome, contenuto, errore}`. Accumula `tools` (`{nome, argomenti, esito, errore}`, abbinando chiamate e risultati in ordine FIFO) e `lines` (testi di `extra`).
    - `@dataclass class Suspended`: `messages: list[AnyMessage]` (senza sistema), `steps: int`, `reviews: int`, `summary: str`, `decisions: dict[int, bool]`, `tools: list[dict]`, `lines: list[str]`; `to_dict() -> dict` (chiavi italiane: `messaggi` con `dump_state_messages`, `passaggi`, `revisioni`, `riassunto`, `decisioni`, `strumenti`, `righe`) e `Suspended.from_dict(data: dict) -> Suspended` (`ValueError("stato sospeso non valido")` su chiavi mancanti o tipi sbagliati; chiavi di `decisioni` convertite in `int`).
    - `@dataclass class TurnOutcome`: `status: str` (`completato`/`conferma_richiesta`), `answer: str`, `tools: list[dict]`, `lines: list[str]`, `history: list[AnyMessage]`, `summary: str`, `confirmations: list[dict]`, `suspended: Suspended | None`.
    - `run_turn(graph, system: str, history: list[AnyMessage], new: list[AnyMessage], summary: str, emit=None, cancelled: threading.Event | None = None) -> TurnOutcome`
    - `resume_turn(graph, system: str, suspended: Suspended, decisions: dict[int, bool], emit=None, cancelled=None) -> TurnOutcome`: stato `{"messages": [SystemMessage(system)] + suspended.messages, "steps", "reviews", "summary", "decisions": {**suspended.decisions, **decisions}}`; il recorder parte con `suspended.tools`/`suspended.lines`, così l'esito finale copre tutto il turno (spec 5.4) e `emit` riceve solo gli eventi nuovi.
    - Entrambe: `config = {"callbacks": [CancelOnInterrupt(cancelled)]}`; eccezioni → `raise classify(error, settings)`; `TurnCancelled` si propaga così com'è. `confirmations` non vuoto nello stato finale → `conferma_richiesta` con `Suspended` costruito dallo stato finale (le decisioni accumulate restano). Altrimenti risposta vuota → `empty_answer()`; altrimenti `completato` con `history = messages[1:]`. Per `classify` le funzioni ricevono anche `settings: Settings` (parametro finale obbligatorio in entrambe).

- [ ] **Step 1: test che falliscono**, con `build_graph` sul modello finto di `tests/fakes.py` e `fake_clock`:
  - turno con strumento: `status == "completato"`, `tools == [{"nome": "get_current_time", "argomenti": {}, "esito": "Europe/Rome: 2026-10-26T14:32:05+01:00", "errore": False}]`, `history` senza `SystemMessage` e con 4 messaggi;
  - `emit` riceve nell'ordine `strumento`, `esito_strumento`, `risposta`;
  - l'agente non tiene stato: due `run_turn` sullo stesso grafo con cronologie diverse non si influenzano;
  - un rifiuto del router finto finisce in `lines` e nella risposta;
  - sospensione e ripresa con le note (come nel Task 2): l'esito finale dopo la ripresa contiene in `tools` anche le chiamate di prima della sospensione; `Suspended.from_dict(s.to_dict())` è equivalente; `from_dict({"messaggi": "x"})` → `ValueError`;
  - errori: un grafo che solleva `openai.APIConnectionError` → `AgentError` 503 `modello_non_raggiungibile` con il testo esatto; parametrizzare tutta la tabella di `classify`; risposta vuota → 502 `risposta_vuota`;
  - `cancelled` già impostato con un modello finto che emette token → `TurnCancelled`; un secondo `run_turn` dopo funziona.
- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_agent_turn.py -q` → FAIL.
- [ ] **Step 3:** implementare `errors.py` e `turn.py`.
- [ ] **Step 4:** PASS; suite completa verde.
- [ ] **Step 5: commit** `feat(agente): esecuzione del turno senza stato, sospensione ed errori`

### Task 4: API FastAPI

**Files:**
- Create: `agent_service/app.py`, `agent_service/schemas.py`
- Test: `tests/test_agent_api.py`

**Interfaces:**
- Consumes: Task 1 e Task 3; `PromptInfo` e `MCPPromptError`/`MCPConnectionError` di `assistant/mcp_client.py`.
- Produces:
  - `@dataclass class Agent` (in `app.py`): `graph`, `system: str`, `settings: Settings`, `list_prompts: Callable[[], list[PromptInfo]]`, `get_prompt: Callable[[str, dict[str, str]], list[tuple[str, str]]]`, `status: Callable[[], dict]` (restituisce `{"modello": {...}, "strumenti": {...}, "note": {...}}`, ciascuno con `raggiungibile: bool` e `messaggio: str`), `lock: threading.Lock` (predefinito nuovo lock).
  - `create_app(agent: Agent) -> FastAPI` (titolo «Agente del laboratorio»).
  - Schemi in `schemas.py`: `Resume(sospeso: dict, decisioni: dict[int, bool])`; `TurnRequest(messaggi: list[Message] = [], cronologia: list[Message] = [], riassunto: str = "", ripresa: Resume | None = None)` con validatore: senza `ripresa` `messaggi` non vuoto e solo ruoli `utente`/`assistente`; con `ripresa` `messaggi` e `cronologia` devono essere vuoti; `TurnResponse(esito, risposta="", strumenti=[], righe=[], cronologia: list[Message]=[], riassunto="", conferme: list[dict]=[], sospeso: dict | None = None)`; `ErrorBody(codice, messaggio)`; schemi dei prompt (`nome`, `descrizione`, `argomenti: [{nome, descrizione, obbligatorio}]`) e `PromptRequest(argomenti: dict[str, str] = {})` → `{messaggi: [Message]}` (ruolo MCP `user` → `utente`, `assistant` → `assistente`).
  - Endpoint della spec 5.2. `AgentError` → `JSONResponse(status, {"codice", "messaggio"})`; `ValueError` di `Suspended.from_dict` → 422 `sospeso_non_valido` con il messaggio; `MCPPromptError` → 422 `prompt_rifiutato`; `MCPConnectionError` sui prompt → 503 `strumenti_non_raggiungibili`.
  - `/chat` (sincrono, gira nel threadpool): prende `agent.lock`, `run_turn` o `resume_turn`, converte con `from_langchain`.
  - `/chat/stream`: un thread esegue il turno sotto `agent.lock` con `emit` che mette `(evento, dati)` in una `queue.Queue`; alla fine mette `fine` (stesso corpo di `/chat`) o `errore` (`{codice, messaggio}`); un generatore **asincrono** legge la coda senza bloccare il ciclo (`get_nowait` + `asyncio.sleep(0.05)`), produce le righe SSE e nel `finally` imposta `cancelled`. Dopo aver preso il lock il thread salta il turno se `cancelled` è già impostato. `TurnCancelled` non produce eventi.
  - `/stato`: `{"agente": "ok", **agent.status()}`, 200 se tutti raggiungibili, altrimenti 503 con lo stesso corpo.
  - Log `assistant.agent` a INFO: `[api] turno: %d messaggi in cronologia, %d nuovi` (o `[api] ripresa: %d decisioni`), una riga `[api] strumento %s %s → %s` per ogni elemento di `tools`, `[api] turno %s in %.1f s` con l'esito o il codice d'errore.

- [ ] **Step 1: test che falliscono** con `TestClient` e `Agent` costruito su `build_graph` + modello finto (status e prompt finti):
  - `POST /chat` con «che ore sono?» e il modello che chiama `get_current_time` → 200, `esito == "completato"`, `strumenti[0]["nome"] == "get_current_time"`, `cronologia` di 4 messaggi con ruoli `utente`, `assistente`, `strumento`, `assistente`; log INFO con `[api] strumento get_current_time`;
  - `POST /chat/stream`: parsing del corpo SSE → sequenza `strumento`, `esito_strumento`, `risposta`, `fine`; il `fine` ha lo stesso contenuto di `/chat`; testo «è «x» ⚠\nriga» intatto nel `data`;
  - conferma via API: prima chiamata → `conferma_richiesta` con `conferme[0]["domanda"]` esatta e `sospeso`; seconda chiamata con `ripresa={"sospeso": ..., "decisioni": {"1": true}}` → `completato`, nota eliminata, `strumenti` copre tutto il turno; la ripresa funziona anche su una **nuova** app (`create_app` di nuovo: nessuno stato tra le richieste);
  - errori: grafo che solleva `openai.APIConnectionError` → 503 `{"codice": "modello_non_raggiungibile", ...}` su `/chat` ed evento `errore` su `/chat/stream`; ruolo `sistema` → 422; `strumento` senza `id_chiamata` → 422; `ripresa` con `messaggi` → 422; `sospeso` manomesso → 422 `sospeso_non_valido`; `messaggi` vuoto senza ripresa → 422;
  - lock: dopo un turno finito in errore il lock è libero (`agent.lock.locked() is False`) e un nuovo `/chat` risponde 200;
  - annullamento: chiudere il generatore dello streaming (`aclose()` sull'iteratore, test asincrono con `asyncio.run`) imposta l'Event `cancelled` (esporlo come attributo testabile o tramite un callback iniettabile, a scelta dell'implementatore);
  - `/stato` 200 e 503; `GET /prompts`; `POST /prompts/spiega` 200, rifiuto → 422 `prompt_rifiutato`, collegamento perso → 503; `GET /openapi.json` 200 con i percorsi `/chat`, `/chat/stream`, `/stato`, `/prompts`.
- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_agent_api.py -q` → FAIL.
- [ ] **Step 3:** implementare `schemas.py` e `app.py`.
- [ ] **Step 4:** PASS; suite completa verde.
- [ ] **Step 5: commit** `feat(agente): API FastAPI con chat, streaming SSE, stato e prompt`

### Task 5: Avvio del servizio dell'agente

**Files:**
- Create: `agent_service/startup.py`, `agent_service/__main__.py`
- Modify: `assistant/mcp_client.py` (`ping`)
- Test: `tests/test_agent_startup.py`, `tests/test_mcp_client.py`

**Interfaces:**
- Consumes: tutto l'avvio oggi in `assistant/__main__.py::_start` (configurazione, ambito, client MCP, preferenze, prompt, servizio note, `build_note_tools`, `build_confirmation_check`, `build_graph` con router, revisore, riassunto, `check_note_claims`); `configure_logging` e `quiet_library_warnings` importati da `assistant.__main__`.
- Produces:
  - `MCPClient.ping() -> None` (`send_ping` sulla sessione con `_await_session`, errori → `MCPConnectionError`).
  - `model_status(settings: Settings, list_models=list_models) -> dict`: `{"raggiungibile": bool, "messaggio": str, "modello": settings.model}`; messaggi: ok «Modello {id} disponibile.», LM Studio spento → testo di `modello_non_raggiungibile`, modello assente → testo di `ModelNotFound`.
  - `build_agent(settings: Settings, root: Path) -> tuple[Agent, Callable[[], None]]`: costruisce tutto e restituisce l'`Agent` e la funzione che chiude servizio note, client HTTP e client MCP. Modello spento all'avvio → `logger.warning("[modello] %s", messaggio)` e si prosegue; `ConfigError`, `MCPConnectionError`, `NotesConnectionError` si propagano (dopo aver chiuso quanto già aperto). `status()` controlla modello (`model_status`), strumenti (`ping`, messaggio ok «Server degli strumenti attivo ({n} strumenti).») e note (`_responds`, messaggio ok «Servizio delle note attivo ({url}).»).
  - `python -m agent_service [--host 127.0.0.1] [--port 8001] [--quiet]`: UTF-8 su stdout/stderr come oggi, `load_dotenv`, `load_settings`, logging (`--quiet` → livello WARNING per tutti i logger e niente log degli accessi; altrimenti `LOG_LEVEL`); `build_agent`; errori di avvio → messaggio su stderr e codice 1 **prima** di uvicorn; poi `uvicorn.run(create_app(agent), ...)` e nel `finally` la chiusura. Righe di avvio di oggi (`[router] ambito`, `[mcp] catalogo`, `[mcp] prompt`, `[note] servizio`, `[revisore] limite`, `[riassunto] soglia`) più `[api] agente in ascolto su http://{host}:{port}`.

- [ ] **Step 1: test che falliscono**:
  - `MCPClient.ping()` contro `tests/mcp_test_server.py` passa; dopo `close()` → `MCPConnectionError`;
  - `model_status` con `list_models` finto: ok, `LMStudioUnavailable`, modello assente;
  - `build_agent` con server MCP reale di prova, servizio note avviato dal test su porta libera (`NOTES_SERVICE_URL`) e LM Studio su una porta chiusa: restituisce l'agente (non solleva), `status()["modello"]["raggiungibile"] is False`, strumenti e note raggiungibili; la chiusura libera il servizio;
  - `SCOPE_FILE` inesistente → `ConfigError`; comando MCP inesistente → `MCPConnectionError`;
  - `python -m agent_service` con `SCOPE_FILE` inesistente (sottoprocesso) → codice 1 e messaggio su stderr.
- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_agent_startup.py tests/test_mcp_client.py -q` → FAIL.
- [ ] **Step 3:** implementare.
- [ ] **Step 4:** PASS; suite completa verde.
- [ ] **Step 5: commit** `feat(agente): avvio del servizio con stato di modello, strumenti e note`

### Task 6: Client dell'agente e avvio automatico

**Files:**
- Create: `assistant/agent_client.py`
- Test: `tests/test_agent_client.py`, `tests/test_agent_launcher.py`

**Interfaces:**
- Produces:
  - `class AgentUnavailable(Exception)` (messaggio «L'agente non risponde: esci e riavvia l'assistente.»); `class AgentRequestError(Exception)` con `code`, `message`.
  - `parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]`: funzione pura; righe `event:`/`data:` (più righe `data:` si uniscono con `\n`), evento chiuso dalla riga vuota.
  - `class AgentClient(base_url: str, transport: httpx.BaseTransport | None = None)`: `httpx.Client` con `Timeout(10.0, read=None)`; `status() -> dict` (accetta 200 e 503); `prompts() -> list[PromptInfo]`; `get_prompt(name, arguments) -> list[tuple[str, str]]` (ruoli tornati `user`/`assistant`; `prompt_rifiutato` → `MCPPromptError(messaggio senza il prefisso «Il server ha rifiutato il prompt: »)`, `strumenti_non_raggiungibili` → `MCPConnectionError`, così il codice dei prompt della CLI resta uguale); `stream_turn(payload: dict) -> Iterator[tuple[str, dict]]` (generatore: `client.stream("POST", "/chat/stream")`, risposta non 200 → `AgentRequestError` dal corpo, `httpx.TransportError` → `AgentUnavailable`; chiudere il generatore chiude la connessione); `close()`.
  - `class LocalAgentService(port: int = 8001, quiet: bool = True)`: `start() -> str` come `LocalNotesService.start` (porta già in uso → `AgentUnavailable("La porta 8001 è già in uso (forse l'agente di Docker è acceso: docker compose down).")`; pronto quando `GET /stato` risponde con qualsiasi codice; attesa fino a 60 s; gruppo di processi separato; stderr del figlio in un `tempfile.TemporaryFile`, **non** in una pipe, che bloccherebbe il figlio a buffer pieno; se il processo esce prima di essere pronto → `AgentUnavailable("L'agente non è partito: " + ultime 5 righe non vuote dello stderr)`); `close()`: su Windows `os.kill(pid, signal.CTRL_BREAK_EVENT)`, altrove `terminate()`; attesa 10 s, poi `kill()`. Con `quiet` passa `--quiet` e lo stderr va solo nel file temporaneo; senza `quiet` (DEBUG) lo stderr resta quello del terminale. Il codice comune con `LocalNotesService` (porta in uso, attesa, gruppo di processi) si può estrarre in una funzione condivisa se resta semplice; non è obbligatorio.

- [ ] **Step 1: test che falliscono**:
  - `parse_sse` su eventi con testo italiano, `\n` nel JSON, due eventi di seguito, riga vuota finale mancante (ultimo evento comunque restituito);
  - `AgentClient` con `httpx.MockTransport`: `stream_turn` produce gli eventi; 422 → `AgentRequestError` con codice; `httpx.ConnectError` → `AgentUnavailable`; `get_prompt` mappa `prompt_rifiutato` e `strumenti_non_raggiungibili`; `client._http.timeout.read is None` (nome dell'attributo a scelta, il test verifica che la lettura non abbia limite);
  - `AgentClient` contro `TestClient(create_app(...))` del Task 4 (come transport): un turno con strumento produce `fine` con `completato` (verifica dell'integrazione client-API);
  - launcher (integrazione, come `test_notes_launcher.py`): servizio note di prova su porta libera, `NOTES_SERVICE_URL` e `LMSTUDIO_BASE_URL` su porta chiusa nell'ambiente del figlio; `start()` restituisce l'url e `/stato` risponde 503 (modello spento); `close()` libera la porta dell'agente; **nessun processo orfano**: dopo `close()` la sessione MCP del figlio è chiusa (verificare che il processo dell'agente sia terminato con codice ≠ kill entro 10 s: niente `kill()` chiamato); porta occupata → messaggio «già in uso»; `SCOPE_FILE` inesistente → `AgentUnavailable` che contiene «SCOPE_FILE».
  - Per passare l'ambiente al figlio nei test, `LocalAgentService` accetta `env: Mapping[str, str] | None = None` (predefinito l'ambiente corrente).
- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_agent_client.py tests/test_agent_launcher.py -q` → FAIL.
- [ ] **Step 3:** implementare.
- [ ] **Step 4:** PASS; suite completa verde.
- [ ] **Step 5: commit** `feat(cli): client HTTP dell'agente con SSE e avvio automatico`

### Task 7: La CLI diventa client dell'API

**Files:**
- Modify: `assistant/config.py` (`agent_service_url`), `assistant/cli.py`, `assistant/__main__.py`, `assistant/prompts.py` (`prompt_messages`), `assistant/notes.py` (tolti `ask_in_terminal`, `confirmation_pending`, `reset_confirmation`, `_pending`; `YES` va in `cli.py`)
- Test: `tests/test_cli.py` (riscritto sull'agente finto), `tests/test_main.py`, `tests/test_config.py`, `tests/test_prompts_command.py`, `tests/test_notes_tools.py`, `tests/fakes.py` (`FakeAgent`)

**Interfaces:**
- Consumes: `AgentClient`, `AgentUnavailable`, `AgentRequestError`, `LocalAgentService` (Task 6); `TurnView` (invariata).
- Produces:
  - `Settings.agent_service_url: str = ""` da `AGENT_SERVICE_URL` (spazi e `/` finale tolti, come `NOTES_SERVICE_URL`).
  - `prompt_messages(messages: list[tuple[str, str]]) -> list[dict]`: `{"ruolo": "utente"|"assistente", "contenuto": testo}`, gli altri ruoli scartati.
  - `run(agent, settings, input_fn=input, output_fn=print, clear_fn=clear_screen, newline_on_interrupt=..., write_fn=None, color=False, model: str = "", prompt_list=())`: `agent` ha `stream_turn(payload)` e `get_prompt(name, args)`. Cronologia `list[dict]` e riassunto `str` della CLI; intestazione «Assistente del laboratorio — modello: {model}».
    - Turno: payload `{"messaggi": nuovi, "cronologia": history, "riassunto": summary}`; eventi → `TurnView` (`ragionamento` → `reasoning`, `risposta` → `answer`, `strumento` → `tool_call`, `esito_strumento` → `tool_result`, `riga` → `extra`); `fine` con `completato` → cronologia e riassunto sostituiti; con `conferma_richiesta` → per ogni conferma `input_fn(domanda)` (sì con `YES`; `EOFError` → no; `KeyboardInterrupt` → esce dalla sessione come oggi) e nuovo `stream_turn({"ripresa": {"sospeso": ..., "decisioni": {str(id): bool}}})`, fino a `completato`; `errore` o `AgentRequestError` → stampa il messaggio, cronologia invariata; `AgentUnavailable` → stampa il suo messaggio, sessione avanti; `KeyboardInterrupt` durante lo streaming → chiude il generatore, stampa `INTERRUPTED`, cronologia invariata.
    - `THINKING` con `SHOW_REASONING=false` come oggi; `help`, `clear` (svuota cronologia e riassunto), `/prompts`, `/prompt`, `quit`/`exit`, saluti e gestione di EOF/Ctrl+C invariati.
    - Tolti da `cli.py`: `error_message`, `TOOLS_DOWN`, `NOTES_DOWN`, `EMPTY_ANSWER`, `CancelOnInterrupt`, `TurnCancelled`, `cancel_on_ctrl_c` (ora nell'agente) e l'import di `graph`.
  - `assistant/__main__._start`: UTF-8, `load_dotenv`, `load_settings`, `configure_logging`; `LocalAgentService(quiet=settings.log_level != "DEBUG")` se `agent_service_url` è vuota, altrimenti quell'indirizzo; `AgentClient`; `status()`: modello o strumenti non raggiungibili → stampa il `messaggio` su stderr, codice 1; `prompts()` (errore → avviso `[mcp] prompt non disponibili` e lista vuota, come oggi); log `[agente] servizio: {url}`; `run(...)`; chiusura con `close_quietly` di client e servizio. `AgentUnavailable` all'avvio → messaggio su stderr, codice 1.
  - `FakeAgent` in `tests/fakes.py`: riceve una lista di sequenze di eventi (una per chiamata a `stream_turn`, oppure un'eccezione da sollevare), registra i payload; `get_prompt` configurabile.

- [ ] **Step 1: test che falliscono** (riscrivere `tests/test_cli.py` mantenendo i comportamenti dei test di oggi):
  - cronologia e riassunto della risposta inviati al turno successivo (payload registrato); `clear` li azzera;
  - stampa: ragionamento, `[strumento]`, righe del revisore e del riassunto, avviso ⚠, risposta senza duplicati; `THINKING` solo senza ragionamento;
  - conferma: `s` → la ripresa porta `{"1": true}`; `n` → `false`; EOF alla domanda → `false` e poi uscita; Ctrl+C alla domanda → uscita con saluto;
  - errori: evento `errore` e `AgentRequestError` stampano il messaggio e la cronologia resta quella di prima; `AgentUnavailable` → «L'agente non risponde: esci e riavvia l'assistente.»; Ctrl+C durante lo streaming → `INTERRUPTED`, generatore chiuso (il finto lo registra), cronologia invariata;
  - `/prompts`, `/prompt` (messaggi inviati come `{"ruolo": "utente", ...}`), errori dei prompt come oggi;
  - `test_main.py`: agente irraggiungibile all'avvio → codice 1 e messaggio; `status` con modello non raggiungibile → codice 1 e messaggio del modello; i test di oggi su logging, Ctrl+C all'avvio e import pesanti restano;
  - `test_config.py`: `AGENT_SERVICE_URL` letto e ripulito;
  - `test_notes_tools.py`: tolti i test di `ask_in_terminal`, `confirmation_pending`, `reset_confirmation`.
- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_cli.py tests/test_main.py tests/test_config.py tests/test_prompts_command.py -q` → FAIL.
- [ ] **Step 3:** implementare.
- [ ] **Step 4:** PASS; suite completa verde; `grep` di `ask_in_terminal|confirmation_pending|cancel_on_ctrl_c` in `assistant/` e `tests/` senza risultati.
- [ ] **Step 5: commit** `feat(cli): la CLI usa l'agente via HTTP con streaming e conferma`

### Task 8: Docker, configurazione e documentazione

**Files:**
- Modify: `compose.yaml`, `Dockerfile`, `.env.example`, `README.md`, `CLAUDE.md`
- Test: verifica manuale dei comandi (nessun test automatico nuovo)

**Interfaces:**
- `compose.yaml`: servizio `agent` (`build: .`, `command: ["python", "-m", "agent_service", "--host", "0.0.0.0", "--port", "8001"]`, `env_file: .env`, `LMSTUDIO_BASE_URL: http://host.docker.internal:1234/v1`, `NOTES_SERVICE_URL: http://notes:8000`, `depends_on: [notes]`, preferenze montate in sola lettura, `ports: ["127.0.0.1:8001:8001"]`, `extra_hosts` come oggi); `app`: `AGENT_SERVICE_URL: http://agent:8001`, `depends_on: [agent]`, senza `LMSTUDIO_BASE_URL`, `NOTES_SERVICE_URL`, volume delle preferenze né `extra_hosts`.
- `Dockerfile`: `COPY agent_service/ ./agent_service/`.
- `.env.example`: `AGENT_SERVICE_URL` commentata come `NOTES_SERVICE_URL` («Vuoto in locale: l'assistente avvia l'agente da solo. Docker Compose la imposta da solo (http://agent:8001).»).
- README: architettura (agente come servizio, CLI client), avvio dell'agente da solo, `/docs`, esempio PowerShell `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/chat -ContentType 'application/json; charset=utf-8' -Body '{"messaggi":[{"ruolo":"utente","contenuto":"Che ore sono?"}]}'`, `/stato`, conferma via API (due chiamate), errori e codici, limiti (un turno alla volta; nessuna riconnessione: `docker compose restart agent`), sezione «Prova reale dell'agente come servizio» con la checklist della spec 6 da compilare. Solo comandi verificati; quelli non ancora provati segnati «da provare».
- `CLAUDE.md`: in «Struttura e comandi» il pacchetto `agent_service/` (moduli e ruolo), `assistant/agent_client.py`, la CLI come client; comando `python -m agent_service`; in «Confini»/«Obiettivo» la frase sull'agente come servizio HTTP.

- [ ] **Step 1:** modificare i file.
- [ ] **Step 2:** `docker compose config` senza errori; `docker compose build` riuscito; suite completa verde.
- [ ] **Step 3:** prova di fumo senza modello: `python -m agent_service` da solo, `Invoke-RestMethod http://127.0.0.1:8001/stato` (503 con LM Studio spento, o 200 se acceso), `/docs` risponde 200; fermare con Ctrl+C e verificare che la porta 8000 sia libera.
- [ ] **Step 4: commit** `docs: agente come servizio (README, CLAUDE.md, Docker Compose)`

La prova reale con LM Studio (spec 6, «Prova reale») la fa l'utente dopo la review finale; gli esiti vanno nel README prima del merge.
