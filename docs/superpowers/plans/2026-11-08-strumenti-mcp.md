# Strumenti MCP (prima parte) — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** spostare l'orologio in un server FastMCP avviato in stdio dall'assistente e aggiungere tre strumenti base (convertitore di unità, calcolatrice sicura, giorni e scadenze), scoperti tramite il catalogo MCP e usati dal grafo esistente.

**Architecture:** nuovo pacchetto `lab_server/` (server, indipendente da `assistant/`): logica di ogni strumento in funzioni pure che sollevano `ValueError`, registrate in `server.py` con `@mcp.tool` che converte `ValueError` in `ToolError`. Nell'assistente, `assistant/mcp_client.py` avvia `python -m lab_server`, tiene **una** sessione MCP aperta in un ciclo asyncio su un thread dedicato e converte il catalogo (`langchain-mcp-adapters`) in tool LangChain **sincroni**. Il grafo resta uguale; il `ToolNode` riceve un gestore d'errore tipizzato (solo `ToolException` torna al modello) e un `wrap_tool_call` che scrive il log di ogni chiamata.

**Tech Stack:** Python 3.14, langgraph 1.2.17, langchain-core 1.7.0, langchain-openai 1.7.2, fastmcp 3.4.11, mcp 1.30.0, langchain-mcp-adapters 0.3.2, tzdata 2026.5, python-dotenv 1.2.4, pytest 9.1.1.

**Spec:** `docs/superpowers/specs/2026-11-02-strumenti-mcp-design.md`

## Global Constraints

- Branch: ogni funzionalità in `feature/<nome>` creato da `developer` aggiornato; a fine funzionalità `git checkout developer`, `git merge --no-ff feature/<nome> -m "chore: unisce feature/<nome> in developer"`, `git push origin developer`, `git branch -d feature/<nome>`. Il branch feature non si pusha. Merge e push solo dopo la prova reale superata e l'ok dell'utente.
- Pezzi piccoli: un commit per task (o meno), mai blocchi grandi di codice.
- Versioni fissate con `==`: aggiungere a `requirements.txt` `fastmcp==3.4.11`, `mcp==1.30.0`, `langchain-mcp-adapters==0.3.2`. Verificato il 2026-11-08 in un venv pulito su Python 3.14 con le dipendenze esistenti: installazione e `pip check` ok. Se in locale l'installazione fallisce: fermarsi e chiedere all'utente (spec §8), nessun ripiego.
- Nessuna nuova variabile d'ambiente. Nessun `eval`/`exec`.
- Nomi nel codice in inglese; testi per l'utente, risultati e errori degli strumenti, log, README e commit in italiano (Conventional Commits).
- Con stdio `stdout` del server è riservato al protocollo: il server non scrive mai su stdout (niente `print`), log solo su `stderr`.
- Ogni risultato degli strumenti è una stringa; ogni input non valido solleva `ValueError` nella logica e diventa `ToolError` nel server, mai un risultato di successo.
- Testi fissati dalla spec:
  - risultato orologio `<fuso>: <ISO 8601 con offset>`, es. `Europe/Rome: 2026-10-26T14:32:05+01:00`;
  - errore fuso `Fuso orario sconosciuto: "<valore>". Usa un nome IANA, es. Europe/Rome.`;
  - conversione `1.5 km = 150000 cm`; calcolo `10 * 7 / 9 = 7.777777777777778`, `2^5 = 32`;
  - festività passata (oggi 2026-11-02): `Pasqua 2026 (2026-04-05, domenica) è già passata; la prossima è il 2027-03-28, domenica`;
  - ogni risultato delle date termina con `Indicativo, non normativo.`
- Comandi dalla radice con il venv attivo (`.\.venv\Scripts\Activate.ps1`); test: `python -m pytest`.
- Non leggere né modificare `lezione-03/`.

## Review Focus

1. **Il modello passa numeri come testo o con la virgola** (`"2.5"`, `"2,5"`) a `convert_units`: `"2.5"` funziona (conversione lasca di pydantic), `"2,5"` torna al modello come errore, non come crash. Test nel Task 9.
2. **Simboli non ASCII o virgola decimale nella calcolatrice** (`3 × 4`, `8 ÷ 2`, `2,5 * 2`): errore esplicito che dice quale carattere non è ammesso. Test nel Task 10.
3. **Date con spazi o con l'ora** (`" 2026-12-25 "`, `2026-12-25T10:00`): spazi ai bordi ignorati, ora rifiutata con il formato atteso. Test nel Task 13.
4. **Nomi di festività senza accento o in minuscolo** (`pasquetta`, `lunedi dell'angelo`, `NATALE`): riconosciuti. Test nel Task 12.
5. **Il sottoprocesso del server resta vivo o la sessione resta usabile dopo la chiusura**: `close()` termina il server, è idempotente e una chiamata successiva solleva `MCPConnectionError`. Test nel Task 4.

---

## Funzionalità 1 — `feature/mcp-orologio`

### Task 1: Branch e modulo dei fusi nel server

**Files:**
- Create: `lab_server/__init__.py` (docstring), `lab_server/timezones.py` (spostato da `assistant/timezones.py` con `git mv`, contenuto invariato)
- Modify: `assistant/config.py` (import), `assistant/tools.py` (import, temporaneo fino al Task 6)
- Test: `tests/test_config.py` (invariato, deve restare verde)

**Interfaces:**
- Produces: `lab_server.timezones.get_timezone(name: str) -> ZoneInfo | None`, `known_timezones() -> frozenset[str]`

- [ ] **Step 1:** `git checkout developer`, `git pull`, `git checkout -b feature/mcp-orologio`.
- [ ] **Step 2:** `git mv assistant/timezones.py lab_server/timezones.py`; crea `lab_server/__init__.py` con `"""Server MCP del laboratorio."""`; aggiorna gli import in `assistant/config.py` e `assistant/tools.py` a `from lab_server.timezones import get_timezone`.
- [ ] **Step 3:** `python -m pytest` → 81 passed.
- [ ] **Step 4:** commit `refactor(strumenti): sposta l'elenco dei fusi nel pacchetto del server`.

### Task 2: Logica dell'orologio nel server

**Files:**
- Create: `lab_server/clock.py`
- Test: `tests/test_server_clock.py` (porta i casi di `tests/test_tools.py` sulla funzione pura)

**Interfaces:**
- Produces: `utc_now() -> datetime`; `current_time(timezone: str | None, default_timezone: str, now: Callable[[], datetime] = utc_now) -> str` — solleva `ValueError` con il testo d'errore del fuso.

- [ ] **Step 1: test** (istante `FIXED = datetime(2026, 10, 26, 13, 32, 5, tzinfo=UTC)`):
  - `current_time(None, "Europe/Rome", FIXED) == "Europe/Rome: 2026-10-26T14:32:05+01:00"`
  - `current_time("Asia/Tokyo", ...) == "Asia/Tokyo: 2026-10-26T22:32:05+09:00"`
  - ora legale: `now=2026-07-01T10:00Z` → `"Europe/Rome: 2026-07-01T12:00:00+02:00"`
  - `""`, `"   "`, `None` → fuso predefinito; `" Asia/Tokyo "` → `Asia/Tokyo`
  - per ognuno di `["Marte/Base", "../etc/passwd", "Europe/", "x" * 300, "Europe/Rome.", "Europe\\Rome", "Europe/Rome::$DATA", "posixrules"]`: `pytest.raises(ValueError, match=...)` con messaggio esatto `Fuso orario sconosciuto: "<bad>". Usa un nome IANA, es. Europe/Rome.`
- [ ] **Step 2:** `python -m pytest tests/test_server_clock.py` → FAIL (modulo mancante).
- [ ] **Step 3:** implementa `lab_server/clock.py` (stessa logica di `assistant/tools.py`, ma solleva `ValueError` invece di restituire il testo; nessun log qui).
- [ ] **Step 4:** test → PASS.
- [ ] **Step 5:** commit `feat(server): aggiunge la logica dell'orologio al server MCP`.

### Task 3: Server FastMCP con l'orologio

**Files:**
- Modify: `requirements.txt` (tre righe nuove, vedi Global Constraints)
- Create: `lab_server/server.py`, `lab_server/__main__.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `current_time`, `utc_now` (Task 2)
- Produces: `create_server(default_timezone: str, now: Callable[[], datetime] = utc_now) -> FastMCP` (nome server `"Strumenti del laboratorio"`); tool `get_current_time(timezone: str | None = None) -> str` con la docstring dell'orologio attuale (nome IANA, es. Europe/Rome, Asia/Tokyo; se omesso fuso predefinito).
- Produces: `python -m lab_server` legge `DEFAULT_TIMEZONE` (default `Europe/Rome`) e `LOG_LEVEL` dall'ambiente, configura il logging su stderr (`DEBUG` se `LOG_LEVEL=DEBUG`, altrimenti `WARNING`) e chiama `create_server(...).run(show_banner=False)` (stdio).

- [ ] **Step 1:** `pip install -r requirements-dev.txt` dopo aver aggiunto le pin; `pip check` → `No broken requirements found.`
- [ ] **Step 2: test** in `tests/test_server.py`, con un helper sincrono `call(server, coro_fn)` che esegue `asyncio.run` su `async with fastmcp.Client(server) as client:` (client in memoria, nessun plugin pytest):
  - `test_catalog_lists_clock`: `list_tools()` contiene `get_current_time`, con `inputSchema["properties"]` che ha `timezone` e descrizione non vuota.
  - `test_clock_call`: `call_tool("get_current_time", {"timezone": "Asia/Tokyo"})` → testo `"Asia/Tokyo: 2026-10-26T22:32:05+09:00"` (server creato con `now=FIXED`).
  - `test_clock_unknown_timezone_is_error`: `call_tool(..., {"timezone": "Marte/Base"}, raise_on_error=False)` → `is_error is True` e testo uguale al messaggio d'errore del fuso.
- [ ] **Step 3:** test → FAIL.
- [ ] **Step 4:** implementa `server.py`: dentro `create_server`, il tool chiama `current_time(...)` e converte `ValueError` in `fastmcp.exceptions.ToolError(str(error))` (`from None`); log `DEBUG` del server su `logging.getLogger("lab_server")`. Implementa `__main__.py`.
- [ ] **Step 5:** test → PASS; poi `python -m pytest` → tutto verde.
- [ ] **Step 6:** commit `feat(server): espone l'orologio con FastMCP` (requirements compreso).

### Task 4: Client MCP dell'assistente

**Files:**
- Create: `assistant/mcp_client.py`, `tests/mcp_test_server.py` (server di prova con tool `echo(text: str) -> str`, `fail() -> str` che solleva `ToolError("errore di prova")`, `die() -> str` che chiama `os._exit(3)`; avviabile con `python -m tests.mcp_test_server`, `show_banner=False`)
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Produces: `class MCPConnectionError(Exception)` — server non avviabile, sessione chiusa, nessuna risposta; messaggio in italiano.
- Produces: `class MCPClient` con `__init__(self, command: list[str], env: Mapping[str, str], errlog=None, timeout: float = 30.0)`; `start() -> list[BaseTool]`; `close() -> None` (idempotente); context manager (`__enter__` → `start()` restituisce i tool, `__exit__` → `close()`).
- Produces: `server_command() -> list[str]` = `[sys.executable, "-m", "lab_server"]`; `server_env(settings: Settings) -> dict[str, str]` = copia di `os.environ` più `DEFAULT_TIMEZONE`, `LOG_LEVEL` e `FASTMCP_LOG_LEVEL` (`DEBUG` se `LOG_LEVEL=DEBUG`, altrimenti `ERROR`, così FastMCP non scrive le righe «Error calling tool» nel terminale).
- Tool restituiti: `StructuredTool` **sincroni** con `name`, `description`, `args_schema` presi dal catalogo; il risultato è il testo dei blocchi `text` uniti con `\n`; un risultato MCP con errore solleva `ToolException(<testo del server>)`; ogni altra eccezione (es. `McpError`, `anyio.ClosedResourceError`, `TimeoutError`) diventa `MCPConnectionError`.

Approccio (verificato con una prova il 2026-11-08): ciclo `asyncio` in un thread daemon; una coroutine apre `mcp.client.stdio.stdio_client(StdioServerParameters(command=command[0], args=command[1:], env=dict(env)), errlog=errlog or sys.stderr)` e `ClientSession`, chiama `initialize()`, `load_mcp_tools(session, handle_tool_errors=False)` (con `True` l'errore arriverebbe al modello come successo), consegna i tool e resta in attesa di un evento di chiusura; ogni chiamata usa `asyncio.run_coroutine_threadsafe(tool.ainvoke(args), loop).result(timeout)`. `start()` attende i tool con `timeout`; un fallimento → `MCPConnectionError` con `command` nel messaggio.

- [ ] **Step 1: test** (server reale `[sys.executable, "-m", "tests.mcp_test_server"]`, `env=os.environ`):
  - `test_catalog_from_server`: i nomi dei tool sono `{"echo", "fail", "die"}` e `echo` ha `text` nello schema (non scritto nel test client: viene dal server).
  - `test_call_returns_text`: `echo` con `{"text": "ciao"}` → `"ciao"`.
  - `test_tool_error_raises_tool_exception`: `fail` → `pytest.raises(ToolException, match="errore di prova")`.
  - `test_dead_server_raises_connection_error`: `die`, poi `echo` → entrambi `pytest.raises(MCPConnectionError)`.
  - `test_close_is_idempotent_and_final` (Review Focus 5): `close()` due volte senza errori; poi `echo` → `MCPConnectionError`.
  - `test_server_not_found`: `command=[sys.executable, "-m", "modulo_inesistente"]` → `start()` solleva `MCPConnectionError` entro il timeout (`timeout=10`).
  - `test_server_env`: `server_env(settings)` con `LOG_LEVEL="INFO"` contiene `FASTMCP_LOG_LEVEL="ERROR"` e `DEFAULT_TIMEZONE`; con `"DEBUG"` → `"DEBUG"`.
- [ ] **Step 2:** test → FAIL.
- [ ] **Step 3:** implementa `tests/mcp_test_server.py` e `assistant/mcp_client.py`.
- [ ] **Step 4:** test → PASS; `python -m pytest` → tutto verde.
- [ ] **Step 5:** commit `feat(mcp): aggiunge il client MCP con sessione unica e tool sincroni`.

### Task 5: Grafo con errori tipizzati e log delle chiamate

**Files:**
- Modify: `assistant/graph.py`, `tests/fakes.py`, `tests/test_graph.py`

**Interfaces:**
- Consumes: tool LangChain sincroni (Task 4); `ToolException` da `langchain_core.tools`.
- Produces: `tool_error_message(error: ToolException) -> str` = `f"Errore: {error}"` (l'annotazione `ToolException` fa sì che il `ToolNode` gestisca **solo** quegli errori; gli altri, come `MCPConnectionError`, escono da `graph.invoke`).
- Produces: `ToolNode(tools, handle_tool_errors=tool_error_message, wrap_tool_call=log_tool_call)`; `log_tool_call(request, execute)` esegue la chiamata e scrive a `INFO` su `assistant.graph`: `[strumento] <nome> call_id=<id> argomenti=<json> esito=<ok|errore> → <contenuto>` (`json.dumps(args, ensure_ascii=False)`).
- `tests/fakes.py`: `tool_call(args: dict, id: str, name: str = "get_current_time") -> AIMessage`; `fake_clock` = tool LangChain `get_current_time(timezone: str | None = None) -> str` che restituisce `"Europe/Rome: 2026-10-26T14:32:05+01:00"` (o `"Asia/Tokyo: 2026-10-26T22:32:05+09:00"`) e solleva `ToolException` col testo del fuso sconosciuto per altri valori.

- [ ] **Step 1: test** (sostituiscono `clock` con `fake_clock` in tutto `test_graph.py`; i test esistenti restano):
  - `test_tool_error_returns_error_status`: chiamata con `{"timezone": "Marte/Base"}` → un `ToolMessage` con `status == "error"`, contenuto che inizia con `Errore: Fuso orario sconosciuto`, e risposta finale del modello finto.
  - `test_unknown_tool_name`: chiamata a `"inesistente"` → `ToolMessage` con `status == "error"`, il grafo arriva alla risposta finale.
  - `test_connection_error_propagates`: tool che solleva `MCPConnectionError` → `pytest.raises(MCPConnectionError)` su `graph.invoke`.
  - `test_tool_call_logged_with_call_id` (caplog INFO): contiene `[strumento] get_current_time call_id=a argomenti={} esito=ok → Europe/Rome: 2026-10-26T14:32:05+01:00`; per l'errore `esito=errore`.
  - `test_graph_with_mcp_tool`: `MCPClient` sul server di prova del Task 4 + modello finto che chiama `echo` con id `"m1"` → `ToolMessage` con `tool_call_id == "m1"`, contenuto `"ciao"`, risposta finale.
  - rimuovi `test_invalid_tool_args_return_error_to_model` e `test_unknown_tool_args_are_ignored` (la validazione degli argomenti è ora del server, coperta nei Task 3 e 9).
- [ ] **Step 2:** test → FAIL.
- [ ] **Step 3:** aggiorna `graph.py`.
- [ ] **Step 4:** `python -m pytest` → tutto verde.
- [ ] **Step 5:** commit `feat(grafo): restituisce al modello solo gli errori degli strumenti e registra ogni chiamata`.

### Task 6: Avvio, interfaccia e Docker con il server MCP

**Files:**
- Modify: `assistant/__main__.py`, `assistant/cli.py`, `Dockerfile`, `tests/test_cli.py`, `tests/test_main.py`
- Delete: `assistant/tools.py`, `tests/test_tools.py`

**Interfaces:**
- Consumes: `MCPClient`, `server_command`, `server_env`, `MCPConnectionError` (Task 4); `build_graph` (Task 5).
- `_start()`: dopo `check_model`, `with MCPClient(server_command(), server_env(settings)) as tools:` log `INFO` `[mcp] catalogo: <nomi separati da virgola>`, poi `build_graph(...)` e `run(...)`. `MCPConnectionError` all'avvio → messaggio su stderr e `return 1`. Catalogo vuoto → stesso trattamento (`MCPConnectionError("Il server degli strumenti non espone nessuno strumento.")`).
- `cli.run`: durante un turno `MCPConnectionError` → `output_fn(TOOLS_DOWN)` con `TOOLS_DOWN = "Il server degli strumenti non risponde: esci e riavvia l'assistente."`; la cronologia non cambia; la sessione continua.
- `Dockerfile`: `COPY lab_server/ ./lab_server/` accanto a quello di `assistant/`.

- [ ] **Step 1: test**:
  - `tests/test_cli.py::test_tools_down_keeps_session`: grafo finto che solleva `MCPConnectionError` al primo turno e risponde al secondo → output contiene `TOOLS_DOWN`, la cronologia del secondo turno non contiene la prima domanda.
  - `tests/test_main.py`: aggiorna `test_heavy_imports_happen_inside_main` includendo `assistant.mcp_client` fra i moduli non importati prima di `main()`.
- [ ] **Step 2:** test → FAIL.
- [ ] **Step 3:** implementa; elimina `assistant/tools.py` e `tests/test_tools.py` (`git rm`).
- [ ] **Step 4:** `python -m pytest` → tutto verde; `docker compose build` → ok.
- [ ] **Step 5:** commit `feat(avvio): collega l'assistente al server MCP e rimuove l'orologio locale`.

### Task 7: Verifica diretta, documentazione e prova reale dell'orologio

**Files:**
- Create: `lab_server/check.py`
- Modify: `README.md`, `CLAUDE.md`

**Interfaces:**
- `parse_args(items: list[str]) -> dict[str, object]` (chiave=valore → dizionario).
- `python -m lab_server.check` stampa il catalogo (nome, descrizione, schema JSON di ogni tool) ottenuto avviando `python -m lab_server` in stdio con `fastmcp.Client`; `python -m lab_server.check <tool> chiave=valore ...` invoca il tool e stampa il risultato o `ERRORE: <testo>` con codice d'uscita 1. Ogni valore viene letto come JSON se possibile (`2.5` → numero), altrimenti come testo. Nessun JSON da scrivere in PowerShell.

- [ ] **Step 1: test** `tests/test_check.py`: `parse_args(["timezone=Asia/Tokyo", "value=2.5"]) == {"timezone": "Asia/Tokyo", "value": 2.5}`; argomento senza `=` → `SystemExit`.
- [ ] **Step 2:** implementa; test → PASS.
- [ ] **Step 3:** verifica a mano in PowerShell: `python -m lab_server.check` (catalogo con `get_current_time`), `python -m lab_server.check get_current_time timezone=Asia/Tokyo` (ora di Tokyo), `python -m lab_server.check get_current_time timezone=Mars/Olympus` (`ERRORE: Fuso orario sconosciuto...`, codice 1).
- [ ] **Step 4:** README: architettura host/client/server, nuova struttura, comandi di verifica diretta (solo quelli eseguiti), nuova riga di log, diagnosi (server non avviato, catalogo vuoto, `TOOLS_DOWN`), numero di test. `CLAUDE.md`: struttura con `lab_server/` e `assistant/mcp_client.py`, comando di verifica diretta, confini (MCP in uso; catalogo, note, meteo da fare).
- [ ] **Step 5:** commit `feat(server): aggiunge la verifica diretta del catalogo e delle chiamate` e `docs: documenta il server MCP e la verifica diretta`.
- [ ] **Step 6: prova reale (utente, LM Studio acceso):** `python -m assistant` → nel log `[mcp] catalogo: get_current_time`; «che ora è?» e «e a Tokyo?» con righe `[strumento] get_current_time call_id=... esito=ok`; memoria e `clear`; poi `docker compose run --rm app` con «che ora è a Tokyo?». Registra l'esito nel README (commit `docs: ...`).
- [ ] **Step 7:** con l'ok dell'utente: merge `--no-ff` in `developer`, push, eliminazione del branch (Global Constraints).

---

## Funzionalità 2 — `feature/convertitore-unita`

### Task 8: Logica del convertitore

**Files:**
- Create: `lab_server/units.py`
- Test: `tests/test_server_units.py`

**Interfaces:**
- Produces: `Unit = Literal["mm", "cm", "dm", "m", "dam", "hm", "km", "mg", "cg", "dg", "g", "dag", "hg", "kg", "q", "t", "ml", "cl", "dl", "l", "dal", "hl", "m3", "C", "K"]`; `convert(value: float, from_unit: str, to_unit: str) -> str`.
- Fattori come `Decimal` rispetto a m, g, l (`q` = 100000 g, `t` = 1000000 g, `m3` = 1000 l); temperatura `K = C + 273.15`. Valore convertito con `Decimal(str(value))`; uscita senza notazione esponenziale e senza zeri finali (`format(d.normalize(), "f")`, `"-0"` → `"0"`).

- [ ] **Step 1: test** (`convert(...) ==` / `pytest.raises(ValueError, match=...)`):
  - `(1.5, "km", "cm")` → `"1.5 km = 150000 cm"`; `(1.1, "km", "cm")` → `"1.1 km = 110000 cm"`; `(3, "hl", "l")` → `"3 hl = 300 l"`; `(2, "q", "kg")` → `"2 q = 200 kg"`; `(1, "t", "q")` → `"1 t = 10 q"`; `(2, "m3", "hl")` → `"2 m3 = 20 hl"`; `(250, "mg", "g")` → `"250 mg = 0.25 g"`; `(5, "km", "km")` → `"5 km = 5 km"`
  - `(20, "C", "K")` → `"20 C = 293.15 K"`; `(0, "K", "C")` → `"0 K = -273.15 C"`; `(-10, "C", "K")` → `"-10 C = 263.15 K"`
  - errori: `(5, "km", "kg")` → match `"lunghezza"` e `"peso"`; `(1, "mi", "km")` → match `"non ammessa"` e `"km"` (elenco); `(-3, "km", "m")` → match `"negativ"`; `(-300, "C", "K")` e `(-1, "K", "C")` → match `"zero assoluto"`.
- [ ] **Step 2:** test → FAIL. **Step 3:** implementa. **Step 4:** test → PASS.
- [ ] **Step 5:** commit `feat(convertitore): aggiunge la logica di conversione delle unità`.

### Task 9: Tool `convert_units`, istruzioni e prova reale

**Files:**
- Modify: `lab_server/server.py`, `assistant/graph.py` (`system_prompt`), `README.md`, `CLAUDE.md` se cambia la struttura
- Test: `tests/test_server.py`, `tests/test_graph.py`

**Interfaces:**
- Produces: tool `convert_units(value: float, from_unit: Unit, to_unit: Unit) -> str`; la docstring elenca le categorie e spiega `q` = quintale, `t` = tonnellata, `m3` = metro cubo, `C` = gradi Celsius, `K` = kelvin, e dice che si converte solo dentro la stessa categoria.

- [ ] **Step 1: test** in `tests/test_server.py`:
  - `test_units_schema_is_closed_list`: `inputSchema["properties"]["from_unit"]["enum"]` uguale all'elenco di `Unit`.
  - `test_units_call`: `{"value": 2.5, "from_unit": "km", "to_unit": "cm"}` → `"2.5 km = 250000 cm"`.
  - `test_units_incompatible_is_error`: `km` → `kg` → `is_error`.
  - Review Focus 1: `{"value": "2.5", ...}` → successo; `{"value": "2,5", ...}` → `is_error` (nessuna eccezione nel test).
  - `tests/test_graph.py::test_system_prompt_mentions_tools`: il prompt contiene `convert_units`.
- [ ] **Step 2:** FAIL → implementa (tool + frase nel prompt: «per conversioni di unità usa `convert_units`») → PASS; `python -m pytest` tutto verde.
- [ ] **Step 3:** commit `feat(convertitore): espone convert_units nel server MCP`.
- [ ] **Step 4:** `python -m lab_server.check convert_units value=3 from_unit=hl to_unit=l` → `3 hl = 300 l`; con `to_unit=kg` → `ERRORE: ...`.
- [ ] **Step 5: prova reale (utente):** «quanti cm sono 2,5 km?», «converti 3 hl in litri», «quanti kg sono 2 quintali?», «20 °C in kelvin», «converti 5 km in kg»; README aggiornato con esiti e comandi; commit `docs: ...`.
- [ ] **Step 6:** con l'ok dell'utente: merge, push, eliminazione del branch.

---

## Funzionalità 3 — `feature/calcolatrice-sicura`

### Task 10: Logica della calcolatrice

**Files:**
- Create: `lab_server/calculator.py`
- Test: `tests/test_server_calculator.py`

**Interfaces:**
- Produces: `calculate(expression: str) -> str`; costanti `MAX_LENGTH = 200`, `MAX_EXPONENT = 1000`, `MAX_RESULT = 10**100`.
- Approccio: rifiuta se più lunga di `MAX_LENGTH` o vuota; rifiuta `=` (messaggio che suggerisce di riscrivere l'equazione come espressione); controlla i caratteri ammessi (cifre, `.`, spazi, `+ - * / ^ ( )`) e nomina il primo carattere non ammesso; sostituisce `^` con `**`; `ast.parse(..., mode="eval")`; visita ricorsiva che accetta solo `Expression`, `BinOp` (`Add`, `Sub`, `Mult`, `Div`, `Pow`), `UnaryOp` (`UAdd`, `USub`), `Constant` int/float; esponente con valore assoluto > `MAX_EXPONENT` e risultato con valore assoluto > `MAX_RESULT` rifiutati **prima** di calcolare la potenza successiva; `ZeroDivisionError` → errore. Uscita `f"{expression.strip()} = {valore}"`, con un float intero mostrato senza `.0`.

- [ ] **Step 1: test**:
  - `"10 * 7 / 9"` → `"10 * 7 / 9 = 7.777777777777778"`; `"2^5"` → `"2^5 = 32"`; `"2**5"` → `"2**5 = 32"`; `"-3 + 5"` → `"-3 + 5 = 2"`; `"(2 + 3) * 4"` → `"(2 + 3) * 4 = 20"`; `"8 / 2"` → `"8 / 2 = 4"`; `"2.5 * 2"` → `"2.5 * 2 = 5"`
  - errori `ValueError` con il motivo nel messaggio: `"x + 1"`, `"sqrt(4)"`, `"__import__('os')"` (carattere non ammesso); `"2x = 28"` (match `"equazion"`); `"1/0"` (match `"zero"`); `"3 +* 4"`, `"(2 + 3"`, `""` (match `"non valida"` o `"vuota"`); `"9^9^9"` e `"10^101"` (match `"troppo grand"`) — ciascuno deve terminare in meno di 1 secondo; `"1" * 201` (match `"lung"`).
  - Review Focus 2: `"3 × 4"`, `"8 ÷ 2"`, `"2,5 * 2"` → errore che cita il carattere (`×`, `÷`, `,`).
- [ ] **Step 2:** FAIL → **Step 3:** implementa → **Step 4:** PASS.
- [ ] **Step 5:** commit `feat(calcolatrice): aggiunge il calcolo sicuro delle espressioni senza eval`.

### Task 11: Tool `calculate`, istruzioni e prova reale

**Files:**
- Modify: `lab_server/server.py`, `assistant/graph.py`, `README.md`
- Test: `tests/test_server.py`, `tests/test_graph.py`

**Interfaces:**
- Produces: tool `calculate(expression: str) -> str`; docstring: operazioni ammesse (`+ - * /`, parentesi, potenza `^` o `**`, decimali con il punto), niente funzioni né lettere, niente equazioni.

- [ ] **Step 1: test:** catalogo contiene `calculate`; `{"expression": "2^5"}` → `"2^5 = 32"`; `{"expression": "__import__('os')"}` → `is_error`; il prompt contiene `calculate` e la frase sulle equazioni («riscrivi le equazioni semplici come espressione, per esempio 2x = 28 → 28 / 2»).
- [ ] **Step 2:** FAIL → implementa → PASS; `python -m pytest` tutto verde; commit `feat(calcolatrice): espone calculate nel server MCP`.
- [ ] **Step 3:** `python -m lab_server.check calculate "expression=10 * 7 / 9"` → `10 * 7 / 9 = 7.777777777777778`.
- [ ] **Step 4: prova reale (utente):** «quanto fa 10 * 7 / 9?», «2 alla 5», «risolvi 2x = 28» (nel log `calculate` con `28 / 2` o equivalente), un input da rifiutare; README; commit `docs: ...`.
- [ ] **Step 5:** con l'ok dell'utente: merge, push, eliminazione del branch.

---

## Funzionalità 4 — `feature/giorni-scadenze`

### Task 12: Festività e Pasqua

**Files:**
- Create: `lab_server/holidays.json`, `lab_server/holidays.py`
- Test: `tests/test_server_holidays.py`

**Interfaces:**
- `holidays.json`: `{"fixed": [{"name", "month", "day", "aliases": [...]}, ...], "easter": [{"name", "offset", "aliases": [...]}]}` con le 10 festività fisse e Pasqua (`offset` 0) / Lunedì dell'Angelo (`offset` 1, alias `Pasquetta`, `Lunedi dell'Angelo`) della spec §5.4; alias utili: `Capodanno`/`1 gennaio`, `Liberazione`/`25 aprile`, `Festa dei lavoratori`/`1 maggio`, `Immacolata`/`8 dicembre`, `Santo Stefano`/`26 dicembre`.
- Produces: `MIN_YEAR = 1900`, `MAX_YEAR = 2200`; `easter(year: int) -> date` (algoritmo gregoriano anonimo, Meeus/Jones/Butcher); `holiday_date(name: str, year: int) -> tuple[str, date]` (nome canonico, data) — `ValueError` per nome sconosciuto (messaggio con i nomi disponibili) o anno fuori intervallo; `holiday_name(day: date) -> str | None`. Nomi confrontati con `casefold()` e spazi normalizzati. File letto con `importlib.resources` una sola volta.

- [ ] **Step 1: test:** `easter(2026) == date(2026, 4, 5)`, `easter(2027) == date(2027, 3, 28)`, `easter(2000) == date(2000, 4, 23)`, `easter(2025) == date(2025, 4, 20)`; `holiday_date("Natale", 2026) == ("Natale", date(2026, 12, 25))`; Review Focus 4: `"pasquetta"`, `"lunedi dell'angelo"`, `"NATALE"`, `" 25 aprile "` riconosciuti; `holiday_name(date(2026, 4, 6)) == "Lunedì dell'Angelo"`, `holiday_name(date(2026, 3, 3)) is None`; `"Halloween"` → `ValueError` con `"Natale"` nel messaggio; anno 1899 e 2201 → `ValueError`.
- [ ] **Step 2:** FAIL → implementa → PASS; commit `feat(date): aggiunge le festività da file locale e il calcolo della Pasqua`.

### Task 13: Logica di giorni e scadenze

**Files:**
- Create: `lab_server/dates.py`
- Test: `tests/test_server_dates.py`

**Interfaces:**
- Consumes: `easter`, `holiday_date`, `holiday_name`, `MIN_YEAR`, `MAX_YEAR` (Task 12).
- Produces (tutte con `today: date` esplicito, calcolato dal server):
  - `parse_iso(text: str) -> date` — spazi ai bordi ignorati; solo `AAAA-MM-GG` (regex `^\d{4}-\d{2}-\d{2}$` poi `date.fromisoformat`); altrimenti `ValueError` con «formato atteso AAAA-MM-GG»; data inesistente → `ValueError` «data inesistente».
  - `describe(day: date, today: date) -> str` — `"<ISO>, <giorno>[ (<festività>)] — <passata|oggi|futura>."`, giorni `lunedì … domenica`.
  - `date_info(day: str, today: date) -> str`; `find_holiday(name: str, year: int | None, today: date) -> str`; `add_days(days: int, start: str | None, today: date) -> str`; `days_between(end: str, start: str | None, today: date) -> str`.
  - Ogni risultato termina con `" Indicativo, non normativo."`; anni fuori `MIN_YEAR..MAX_YEAR` (in ingresso o nel risultato) → `ValueError`.

- [ ] **Step 1: test** (`TODAY = date(2026, 11, 2)`):
  - `date_info("2026-12-25", TODAY)` contiene `"2026-12-25, venerdì (Natale) — futura."` e termina con `"Indicativo, non normativo."`; `date_info("2026-01-01", TODAY)` contiene `"passata"`; `date_info("2026-11-02", TODAY)` contiene `"oggi"`; `date_info("2028-02-29", TODAY)` contiene `"martedì"`.
  - `find_holiday("Pasqua", None, TODAY)` contiene `"Pasqua 2026 (2026-04-05, domenica) è già passata; la prossima è il 2027-03-28, domenica"`; `find_holiday("Natale", None, TODAY)` contiene `"2026-12-25, venerdì"` e non `"già passat"`; `find_holiday("Pasqua", 2025, TODAY)` contiene `"2025-04-20"` e `"già passata"`; `find_holiday("Ognissanti", None, date(2026, 11, 1))` non segnala passata (è oggi).
  - `add_days(24, None, TODAY)` contiene `"2026-11-26, giovedì"`; `add_days(24, "2026-12-20", TODAY)` contiene `"2027-01-13"`; `add_days(-2, None, TODAY)` contiene `"passata"`.
  - `days_between("2026-12-25", None, TODAY)` contiene `"53 giorni"`; `days_between("2026-11-01", None, TODAY)` contiene `"-1 giorni"` e `"passata"`. Formato: `"Dal <start> al <end>: <n> giorni. <describe(end)> Indicativo, non normativo."`
  - Review Focus 3: `" 2026-12-25 "` accettata; `"25/12/2026"`, `"2026-12-25T10:00"` → `ValueError` con `"AAAA-MM-GG"`; `"2026-02-30"` → `ValueError` `"inesistente"`; `add_days(100000, None, TODAY)` → `ValueError`.
- [ ] **Step 2:** FAIL → implementa → PASS.
- [ ] **Step 3:** commit `feat(date): aggiunge informazioni su date, festività e scadenze`.

### Task 14: Tool delle date, istruzioni e prova reale

**Files:**
- Modify: `lab_server/server.py`, `assistant/graph.py`, `README.md`, `CLAUDE.md`
- Test: `tests/test_server.py`, `tests/test_graph.py`

**Interfaces:**
- Produces: tool `date_info(date: str)`, `find_holiday(name: str, year: int | None = None)`, `add_days(days: int, start: str | None = None)`, `days_between(end: str, start: str | None = None)`, tutti `-> str`; `today` = `now().astimezone(ZoneInfo(default_timezone)).date()` in `create_server`. Docstring con il formato ISO e i default (oggi).

- [ ] **Step 1: test:** catalogo con i 7 tool (`get_current_time`, `convert_units`, `calculate`, `date_info`, `find_holiday`, `add_days`, `days_between`); con `now=FIXED_NOV` (`2026-11-02T10:00Z`) `find_holiday {"name": "Pasqua"}` contiene `"già passata"` e `"2027-03-28"`; `date_info {"date": "25/12/2026"}` → `is_error`; il prompt cita le date ISO e i quattro tool.
- [ ] **Step 2:** FAIL → implementa → PASS; `python -m pytest` tutto verde; commit `feat(date): espone gli strumenti di giorni e scadenze nel server MCP`.
- [ ] **Step 3:** `python -m lab_server.check find_holiday name=Pasqua` e `python -m lab_server.check add_days days=24`.
- [ ] **Step 4: prova reale (utente):** «che giorno della settimana è Pasqua?» (avviso e Pasqua 2027), «che giorno sarà Natale?», «che giorno sarà tra 24 giorni?», «quanti giorni mancano a Natale?»; continuità (memoria, `clear`, limite di passaggi); almeno una domanda in Docker. README (esiti, numero di test) e `CLAUDE.md` (struttura finale); commit `docs: ...`.
- [ ] **Step 5:** con l'ok dell'utente: merge, push, eliminazione del branch; aggiornare la memoria di progetto.
