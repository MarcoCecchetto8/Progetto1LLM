# Preferenze come resource MCP — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** il server MCP espone `utente://preferenze` (lingua, fuso orario, stile da `config/preferenze.json`); l'assistente la legge una volta all'avvio, la valida con riserve e la mette in cima al prompt di sistema.

**Architecture:** validazione pura condivisa in `lab_server/preferences.py`; il server registra la resource (testo del file) e usa il fuso valido come predefinito; `MCPClient` legge la resource in modo sincrono; `assistant/preferences.py` la legge, valida e scrive i log; `system_prompt` riceve le preferenze.

**Tech Stack:** Python, FastMCP 3.4.11, mcp 1.30.0, langchain-mcp-adapters 0.3.2, LangGraph, pytest. Nessuna nuova dipendenza.

**Spec:** `docs/superpowers/specs/2026-11-17-preferenze-resource-design.md`

## Global Constraints

- Branch `feature/preferenze` da `developer`; Conventional Commits in italiano con la riga `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; `git status` e staging selettivo prima di ogni commit; nessun push.
- URI `utente://preferenze`, `name="preferenze"`, `mime_type="application/json"`, descrizione «Preferenze dell'utente per le risposte: lingua, fuso orario predefinito, stile.».
- Campi e valori ammessi (confronto esatto): `lingua` ∈ (`italiano`, `inglese`, `spagnolo`); `stile` ∈ (`sintetico`, `dettagliato`); `fuso_orario` nome IANA valido per `lab_server.timezones.get_timezone`. Riserve: `italiano`, `sintetico`, fuso di riserva (`DEFAULT_TIMEZONE`). Campi in più ignorati; campo assente = non valido.
- File `config/preferenze.json` versionato: `{"lingua": "italiano", "fuso_orario": "Europe/Rome", "stile": "sintetico"}`. Variabile `PREFERENCES_FILE`, predefinito `config/preferenze.json`, relativo alla radice del progetto.
- I testi fissi del programma e i prompt di router, revisore e riassunto restano in italiano e invariati. Il revisore non cambia.
- Le preferenze si leggono una volta per sessione; `clear` non le rilegge.
- Test senza LM Studio; suite completa verde (`python -m pytest`, controllare l'exit code) prima di ogni commit.

## Review Focus

1. **File salvato con BOM** (Blocco note di Windows): il server lo legge con `encoding="utf-8-sig"`, così il JSON resta valido. Test nel Task 2.
2. **Valori non stringa** (`"stile": 1`, `null`, una lista): campo non ammesso, riserva e avviso, nessuna eccezione. Test nel Task 1.
3. **Percorso relativo con directory di lavoro diversa** (Docker `/app`, avvio da un'altra cartella): `server_env` passa al server un percorso assoluto. Test nel Task 3.
4. **Avvisi doppi nel terminale**: il server registra i propri avvisi sulle preferenze a `DEBUG` (fuori da DEBUG il suo log è a `WARNING`), l'host li scrive una volta sola. Test nel Task 2.
5. **Lettura fallita che rompe la sessione**: dopo una lettura di resource fallita i tool funzionano ancora. Test nel Task 3.

---

### Task 1: Validazione delle preferenze e file predefinito

**Files:**
- Create: `lab_server/preferences.py`, `config/preferenze.json`
- Test: `tests/test_preferences.py`

**Interfaces:**
- Produces in `lab_server/preferences.py`:
  - `PREFERENCES_URI = "utente://preferenze"`, `LANGUAGES = ("italiano", "inglese", "spagnolo")`, `STYLES = ("sintetico", "dettagliato")`.
  - `@dataclass(frozen=True) class Preferences: lingua: str; fuso_orario: str; stile: str`.
  - `parse_preferences(text: str | None, fallback_timezone: str, reason: str = "") -> tuple[Preferences, list[str]]`: avvisi senza prefisso `[preferenze]`.

Testi esatti degli avvisi (`<tz>` = fuso di riserva):
- `text is None`: `resource non disponibile (<reason>): uso italiano, sintetico, <tz>`
- JSON illeggibile: `contenuto non valido (JSON non leggibile): uso italiano, sintetico, <tz>`
- JSON che non è un oggetto: `contenuto non valido (non è un oggetto JSON): uso italiano, sintetico, <tz>`
- campo assente: `<campo> mancante: uso '<riserva>'`
- campo non ammesso: `<campo> '<valore>' non ammesso: uso '<riserva>'` (`<valore>` con `str()`; per il fuso «non ammesso» vale anche per un nome sconosciuto).

- [ ] **Step 1: Test che falliscono** in `tests/test_preferences.py`:
  - `test_all_valid`: `parse_preferences('{"lingua": "inglese", "fuso_orario": "America/New_York", "stile": "dettagliato"}', "Europe/Rome")` → `(Preferences("inglese", "America/New_York", "dettagliato"), [])`.
  - `test_unavailable`: `parse_preferences(None, "Europe/Rome", "file mancante")` → `(Preferences("italiano", "Europe/Rome", "sintetico"), ["resource non disponibile (file mancante): uso italiano, sintetico, Europe/Rome"])`.
  - `test_invalid_json` (`"{"`) e `test_not_an_object` (`"[1, 2]"`): riserve e il rispettivo avviso.
  - `test_single_invalid_field_keeps_others`: stile `"medio"` con lingua e fuso validi → solo lo stile torna `sintetico`, avvisi `["stile 'medio' non ammesso: uso 'sintetico'"]`.
  - `test_unknown_timezone_uses_fallback`: `"fuso_orario": "Marte/Base"` → fuso `Europe/Rome`, avviso `"fuso_orario 'Marte/Base' non ammesso: uso 'Europe/Rome'"`.
  - `test_missing_field`: oggetto senza `lingua` → avviso `"lingua mancante: uso 'italiano'"`.
  - `test_non_string_values` (Review Focus 2): `{"lingua": null, "fuso_orario": 5, "stile": ["x"]}` → tutte le riserve, tre avvisi `non ammesso`, nessuna eccezione.
  - `test_case_sensitive`: `"lingua": "Inglese"` → non ammesso.
  - `test_extra_fields_ignored`: un campo `"tema": "scuro"` in più → nessun avviso.
  - `test_default_file_is_valid`: il testo di `config/preferenze.json` dà `Preferences("italiano", "Europe/Rome", "sintetico")` e nessun avviso.
- [ ] **Step 2: Verificare che falliscano** — `python -m pytest tests/test_preferences.py -v` → errori di import.
- [ ] **Step 3: Implementare** `lab_server/preferences.py` (usa `get_timezone` di `lab_server/timezones.py`; un valore è ammesso solo se è `str` e nell'elenco, per il fuso se `get_timezone` non dà `None`) e creare `config/preferenze.json`.
- [ ] **Step 4: Suite verde** — `python -m pytest`.
- [ ] **Step 5: Commit** — `feat(preferenze): validazione delle preferenze e file predefinito`.

### Task 2: Resource sul server MCP, fuso del server, elenco in `check`

**Files:**
- Modify: `lab_server/server.py`, `lab_server/__main__.py`, `lab_server/check.py`
- Test: `tests/test_server.py`, `tests/test_check.py`

**Interfaces:**
- Consumes: `PREFERENCES_URI`, `parse_preferences` (Task 1).
- Produces:
  - `create_server(default_timezone: str, now=utc_now, preferences_file: Path | None = None) -> FastMCP`: se `preferences_file` non è `None` registra la resource (vedi Global Constraints), che a ogni lettura restituisce `preferences_file.read_text(encoding="utf-8-sig")`; un `OSError` diventa un errore della lettura per il client (eccezione nella funzione della resource, con messaggio `file delle preferenze non leggibile: <percorso>`). Senza `preferences_file` nessuna resource (i test esistenti non cambiano).
  - `lab_server.__main__.server_timezone(env: Mapping[str, str], root: Path) -> tuple[str, Path]`: percorso = `PREFERENCES_FILE` (predefinito `config/preferenze.json`, relativo a `root` se non assoluto); fuso di riserva = `DEFAULT_TIMEZONE` o `Europe/Rome`; legge il file (`utf-8-sig`, `None` se illeggibile), `parse_preferences`, registra ogni avviso a **`DEBUG`** sul logger `lab_server` (Review Focus 4), restituisce `(preferences.fuso_orario, percorso)`. `main()` la usa con `root = Path(__file__).resolve().parent.parent` e passa fuso e percorso a `create_server`.
  - `check.py` senza argomenti: dopo i tool stampa una riga per resource: `resource <uri>: <name> (<mimeType>)`.

- [ ] **Step 1: Test che falliscono** (client FastMCP in memoria come in `tests/test_server.py`, file in `tmp_path`):
  - `test_preferences_resource_listed`: `list_resources` → un elemento con URI `utente://preferenze`, nome `preferenze`, tipo `application/json`; `list_tools` non contiene `preferenze`.
  - `test_preferences_resource_reads_file`: scritto un testo, la lettura restituisce lo stesso testo; modificato il file, la lettura successiva restituisce il nuovo testo.
  - `test_preferences_resource_bom` (Review Focus 1): file scritto con `encoding="utf-8-sig"` → testo senza BOM, `json.loads` funziona.
  - `test_preferences_resource_missing_file`: percorso inesistente → `read_resource` solleva un'eccezione.
  - `test_no_resource_without_file`: `create_server("Europe/Rome", FIXED)` → nessuna resource.
  - `test_server_timezone_from_preferences`: `server_timezone({"PREFERENCES_FILE": str(file)}, tmp_path)` con fuso `America/New_York` → `("America/New_York", file)`.
  - `test_server_timezone_fallback_logs_debug` (Review Focus 4): fuso non valido e `DEFAULT_TIMEZONE=Asia/Tokyo` → `"Asia/Tokyo"`; con `caplog` l'avviso è a `DEBUG`, nessun record `WARNING`.
  - `test_server_timezone_relative_path`: `PREFERENCES_FILE` relativo → percorso sotto `root`.
  - in `tests/test_check.py`, `test_check_lists_resource`: `check([])` (asincrona, server reale in stdio come oggi) stampa una riga che inizia con `resource utente://preferenze: preferenze (application/json)` (usare `capsys`; se lento, marcarlo come gli altri test che avviano il server).
- [ ] **Step 2: Verificare che falliscano.**
- [ ] **Step 3: Implementare** resource, `server_timezone`, `main()` e la riga in `check.py`.
- [ ] **Step 4: Suite verde.** Verifica a mano: `python -m lab_server.check` mostra la riga della resource.
- [ ] **Step 5: Commit** — `feat(server): resource utente://preferenze e fuso predefinito dalle preferenze`.

### Task 3: `PREFERENCES_FILE`, ambiente del server, lettura sincrona nel client

**Files:**
- Modify: `assistant/config.py`, `assistant/mcp_client.py`, `tests/mcp_test_server.py`, `.env.example`
- Test: `tests/test_config.py`, `tests/test_mcp_client.py`

**Interfaces:**
- Produces:
  - `Settings.preferences_file: str = "config/preferenze.json"` (ultimo campo), letto con `_get(env, "PREFERENCES_FILE", "config/preferenze.json")`.
  - `server_env(settings)` imposta anche `PREFERENCES_FILE` a un percorso **assoluto**: se relativo, rispetto alla radice del progetto (`Path(__file__).resolve().parent.parent`) (Review Focus 3).
  - `class MCPResourceError(Exception)` in `assistant/mcp_client.py`.
  - `MCPClient.read_resource(uri: str) -> str`: sulla stessa sessione dei tool (`ClientSession.read_resource(AnyUrl(uri))`, testo dei contenuti uniti); un errore MCP della lettura → `MCPResourceError(<messaggio>)`; timeout o sessione chiusa → `MCPConnectionError` come per i tool. La sessione resta utilizzabile dopo un `MCPResourceError`.
  - `tests/mcp_test_server.py`: resource `prova://testo` che restituisce `"ciao"` e `prova://rotta` che solleva un'eccezione.
- [ ] **Step 1: Test che falliscono**:
  - `test_config`: assente → `"config/preferenze.json"`; impostata → il valore.
  - `test_server_env_absolute_preferences_path`: relativo → assoluto sotto la radice; assoluto → invariato.
  - `test_read_resource`: `read_resource("prova://testo") == "ciao"`.
  - `test_read_resource_error_keeps_session` (Review Focus 5): `read_resource("prova://rotta")` → `MCPResourceError`; subito dopo il tool `echo` funziona.
  - `test_resource_not_in_tools`: i tool caricati non contengono nomi di resource.
- [ ] **Step 2: Verificare che falliscano.**
- [ ] **Step 3: Implementare**; `.env.example`: riga commentata in italiano «# File delle preferenze dell'utente (lingua, fuso orario, stile), relativo alla radice del progetto» e `PREFERENCES_FILE=config/preferenze.json`, dopo `SCOPE_FILE`.
- [ ] **Step 4: Suite verde.**
- [ ] **Step 5: Commit** — `feat(mcp): lettura sincrona delle resource e PREFERENCES_FILE`.

### Task 4: Prompt di sistema con le preferenze

**Files:**
- Modify: `assistant/graph.py`, `assistant/cli.py`
- Test: `tests/test_graph.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Preferences` (Task 1).
- Produces:
  - `system_prompt(preferences: Preferences) -> str` (sostituisce `system_prompt(default_timezone)`). Testo esatto del blocco in cima, seguito da una riga vuota e dalle istruzioni di oggi:
    ```
    Preferenze dell'utente (dalla resource utente://preferenze):
    - Rispondi sempre in {lingua}.
    - Stile: {testo dello stile}.
    - Fuso orario predefinito: {fuso_orario}; usalo quando l'utente non indica un fuso orario, senza chiederglielo.
    ```
    Testo dello stile: `sintetico` → `sintetico: rispondi in una o due frasi, solo con ciò che è chiesto`; `dettagliato` → `dettagliato: aggiungi alla risposta il contesto utile preso dai risultati degli strumenti, in qualche frase o in un breve elenco`.
    Le istruzioni di oggi cominciano con «Sei l'assistente del laboratorio. Quando l'utente ti saluta, presentati brevemente.» (tolti «Rispondi sempre in italiano, in modo chiaro e conciso.»); la frase del fuso usa `preferences.fuso_orario`.
  - `cli.run(..., preferences: Preferences | None = None)`: se `None`, `Preferences("italiano", settings.default_timezone, "sintetico")`; il prompt iniziale (anche dopo `clear`) è `system_prompt(preferences)`.
- [ ] **Step 1: Test che falliscono**:
  - il prompt inizia con `"Preferenze dell'utente (dalla resource utente://preferenze):\n- Rispondi sempre in inglese.\n"` per lingua inglese; contiene il testo di ciascuno stile; contiene `America/New_York` sia nel blocco sia nella frase del fuso; non contiene `"Rispondi sempre in italiano, in modo chiaro e conciso"`.
  - aggiornare i test esistenti che chiamano `system_prompt("Europe/Rome")` / `system_prompt(...)` alla nuova firma.
  - `test_model_receives_summary_in_system_prompt` resta verde: il riassunto è sempre in fondo.
  - `cli.run` con `preferences` inglese: il primo messaggio di sistema passato al grafo inizia con il blocco; dopo `clear` lo stesso testo; senza `preferences` vale italiano/sintetico/fuso di `settings`.
- [ ] **Step 2: Verificare che falliscano.**
- [ ] **Step 3: Implementare.**
- [ ] **Step 4: Suite verde.**
- [ ] **Step 5: Commit** — `feat(grafo): preferenze dell'utente in cima al prompt di sistema`.

### Task 5: Lettura all'avvio, log, Docker e documentazione

**Files:**
- Create: `assistant/preferences.py`
- Modify: `assistant/__main__.py`, `compose.yaml`, `README.md`, `CLAUDE.md`
- Test: `tests/test_assistant_preferences.py`

**Interfaces:**
- Consumes: `PREFERENCES_URI`, `parse_preferences`, `Preferences` (Task 1); `MCPClient.read_resource`, `MCPResourceError` (Task 3); `cli.run(..., preferences=)` (Task 4).
- Produces: `load_preferences(read: Callable[[str], str], fallback_timezone: str) -> Preferences` in `assistant/preferences.py`: chiama `read(PREFERENCES_URI)`; un `MCPResourceError` diventa `text=None` con `reason=str(errore)`; `parse_preferences`; per ogni avviso `logger.warning("[preferenze] %s", avviso)`; poi `logger.info("[preferenze] utente://preferenze: lingua=%s, fuso_orario=%s, stile=%s", ...)` sul logger `assistant`. `MCPConnectionError` non viene catturato.
- [ ] **Step 1: Test che falliscono** (`read` finto):
  - valido → preferenze attese, una sola riga `INFO` con il testo esatto, nessun `WARNING`.
  - `read` che solleva `MCPResourceError("file delle preferenze non leggibile: x")` → riserve, `WARNING` `[preferenze] resource non disponibile (file delle preferenze non leggibile: x): uso italiano, sintetico, Europe/Rome`, poi la riga `INFO`.
  - stile non ammesso → un `WARNING` con il campo, `INFO` con `stile=sintetico`.
  - `read` che solleva `MCPConnectionError` → l'eccezione passa.
- [ ] **Step 2: Verificare che falliscano.**
- [ ] **Step 3: Implementare** `assistant/preferences.py`; in `__main__._start`, subito dopo la riga `[mcp] catalogo`: `preferences = load_preferences(client.read_resource, settings.default_timezone)`; `zone = get_timezone(preferences.fuso_orario)` per le note; `run(graph, settings, color=color, preferences=preferences)`. I tool passati a `build_graph` restano quelli di oggi.
- [ ] **Step 4: Docker e documentazione**:
  - `compose.yaml`, servizio `app`: `volumes: - ./config/preferenze.json:/app/config/preferenze.json:ro`.
  - README: variabile `PREFERENCES_FILE` nella tabella di configurazione; sezione «Preferenze dell'utente» (file, campi e valori, riserve e avvisi, resource non tra i tool, lettura una volta per sessione, Docker montato, limiti: testi fissi in italiano, avviso delle note solo in italiano); righe di diagnosi per gli avvisi `[preferenze]`; tabella «Prova reale delle preferenze» con le prove della specifica 6 come «da provare».
  - `CLAUDE.md`, sezione Struttura: `assistant/preferences.py` (lettura della resource delle preferenze all'avvio, avvisi e riserve), `lab_server/preferences.py` (validazione delle preferenze, condivisa con l'host), `config/preferenze.json` (preferenze dell'utente: lingua, fuso, stile; percorso in `PREFERENCES_FILE`).
- [ ] **Step 5: Suite verde**; `docker compose config` senza errori.
- [ ] **Step 6: Commit** — codice `feat(preferenze): lettura della resource all'avvio`; documentazione e `compose.yaml` in un commit separato `docs: preferenze dell'utente (README, CLAUDE.md) e montaggio in Docker`.

### Dopo i task (controller)

- Review finale dell'intero branch.
- Prova reale con LM Studio (specifica 6): `America/New_York` e «Che ore sono?»; `inglese`; `dettagliato` con «chi ha creato Python?»; valore non ammesso; file mancante; `LOG_LEVEL=DEBUG` per la lettura una volta prima della prima domanda; giudizi del revisore con inglese e dettagliato; una nota in inglese (limite dell'avviso); Docker via pipe con modifica del file montato senza `build`. Esiti nel README, commit `docs: ...`.
- Ok dell'utente per merge `--no-ff` in `developer`, push, eliminazione del branch.
