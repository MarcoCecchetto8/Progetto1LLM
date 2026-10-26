# Assistente del laboratorio — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** applicazione da terminale che conversa con il modello di LM Studio tramite un grafo LangGraph esplicito, con strumento orologio, limite di passaggi, cronologia di sessione e avvio con Docker Compose.

**Architecture:** pacchetto `assistant/` con moduli piccoli: `config` (variabili d'ambiente) → `llm` (LM Studio) e `tools` (orologio) → `graph` (stato, nodi `model`/`tools`/`step_limit`, instradamento) → `cli` (ciclo da terminale, comandi, errori) → `__main__` (assemblaggio). La cronologia vive nella sessione del `cli` come lista di messaggi passata al grafo a ogni turno: niente checkpointer, ripristino banale in caso di errore.

**Tech Stack:** Python 3.14, langgraph 1.2.17, langchain-openai 1.7.2, langchain-core 1.7.0, tzdata 2026.5, python-dotenv 1.2.4, pytest 9.1.1, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-26-assistente-laboratorio-design.md`

## Global Constraints

- Python 3.14 in locale e `python:3.14-slim` in Docker. Le versioni sopra sono state installate e importate con successo su Python 3.14.2 il 2026-10-26.
- Dipendenze fissate con `==`: `requirements.txt` (runtime) e `requirements-dev.txt` (`-r requirements.txt` + pytest). Nessun'altra dipendenza.
- Nomi nel codice in inglese; testi per l'utente, log, README e commit in italiano.
- Commit: Conventional Commits in italiano; prima di ogni commit `git status`, controllo del diff, staging selettivo. Mai versionare `.env`, `.venv/`, cache.
- Non leggere né modificare `lezione-03/`.
- Nessuno streaming, nessun altro strumento, nessuna persistenza.
- Comandi da eseguire dalla radice `Progetto1LLM/` con il venv attivo (`.\.venv\Scripts\Activate.ps1`).
- Testi esatti dalla specifica:
  - `LIMIT_MESSAGE = "Limite di passaggi raggiunto: prova a riformulare la domanda o chiedimi altro."`
  - errore fuso: `Fuso orario sconosciuto: "<valore>". Usa un nome IANA, es. Europe/Rome.`
  - log strumento: `[strumento] get_current_time(timezone=<fuso>) → <risultato>`
  - risultato strumento: `<fuso>: <ISO 8601 con offset>`, es. `Europe/Rome: 2026-10-26T14:32:05+01:00`

## Review Focus

1. **Fuso con spazi o vuoto dal modello** (`" Asia/Tokyo "`, `""`, `null`): spazi rimossi, vuoto → fuso predefinito. Test nel Task 2.
2. **Fuso malevolo o malformato** (`"../etc/passwd"`, `"Europe/"`): `ZoneInfo` solleva `ValueError` oltre a `ZoneInfoNotFoundError`; deve diventare il messaggio d'errore per il modello, non un crash. Test nel Task 2.
3. **Il modello chiama lo strumento con argomenti sbagliati** (`{"tz": "Asia/Tokyo"}`) **o due chiamate in un solo messaggio**: nessun crash; il risultato o l'errore torna al modello, una `ToolMessage` per chiamata. Test nel Task 3.
4. **Ctrl+C mentre il modello sta lavorando**: uscita pulita con codice 0, senza traceback. Test nel Task 5.
5. **`LMSTUDIO_BASE_URL` con la barra finale** (`http://localhost:1234/v1/`): la verifica di `/v1/models` funziona comunque. Test nel Task 4.

---

### Task 1: Struttura del progetto e configurazione

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `.env.example`, `assistant/__init__.py`, `assistant/config.py`, `tests/__init__.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `class ConfigError(Exception)`: messaggio in italiano che nomina la variabile.
  - `@dataclass(frozen=True) class Settings`: `base_url: str`, `model: str`, `timeout: float`, `temperature: float`, `max_steps: int`, `default_timezone: str`, `log_level: str`.
  - `load_settings(env: Mapping[str, str]) -> Settings`.

- [ ] **Step 1: Crea il venv e i file di base.** `python -m venv .venv`; `requirements.txt` con le cinque dipendenze runtime fissate; `requirements-dev.txt` con `-r requirements.txt` e `pytest==9.1.1`; `pip install -r requirements-dev.txt`. `.gitignore` con `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`. In `.env.example` tutte le variabili della sez. 9 della specifica, con `LMSTUDIO_BASE_URL=http://localhost:1234/v1`, `LMSTUDIO_MODEL=google/gemma-4-e2b`, i valori predefiniti e un commento con l'indirizzo per Docker.

- [ ] **Step 2: Scrivi i test che falliscono** in `tests/test_config.py`:

```python
BASE = {"LMSTUDIO_BASE_URL": "http://localhost:1234/v1", "LMSTUDIO_MODEL": "google/gemma-4-e2b"}

def test_defaults():
    s = load_settings(BASE)
    assert (s.timeout, s.temperature, s.max_steps, s.default_timezone, s.log_level) == (120.0, 0.2, 5, "Europe/Rome", "INFO")

@pytest.mark.parametrize("missing", ["LMSTUDIO_BASE_URL", "LMSTUDIO_MODEL"])
def test_missing_required(missing):
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ConfigError, match=missing): load_settings(env)

def test_blank_required_counts_as_missing():
    with pytest.raises(ConfigError, match="LMSTUDIO_MODEL"): load_settings({**BASE, "LMSTUDIO_MODEL": "  "})

@pytest.mark.parametrize("var,value", [("MAX_STEPS", "0"), ("MAX_STEPS", "abc"), ("LMSTUDIO_TIMEOUT", "-1"),
    ("LMSTUDIO_TEMPERATURE", "x"), ("DEFAULT_TIMEZONE", "Marte/Base"), ("LOG_LEVEL", "LOUD")])
def test_invalid_values(var, value):
    with pytest.raises(ConfigError, match=var): load_settings({**BASE, var: value})

def test_overrides_and_log_level_case():
    s = load_settings({**BASE, "MAX_STEPS": "3", "DEFAULT_TIMEZONE": "Asia/Tokyo", "LOG_LEVEL": "debug"})
    assert (s.max_steps, s.default_timezone, s.log_level) == (3, "Asia/Tokyo", "DEBUG")
```

- [ ] **Step 3: Verifica che falliscano.** `python -m pytest tests/test_config.py -v`. Atteso: errore di import.

- [ ] **Step 4: Implementa `assistant/config.py`.** Valori `strip()`-ati. `LOG_LEVEL` va in maiuscolo e deve essere uno fra `DEBUG`, `INFO`, `WARNING`, `ERROR`. Il fuso si valida con `ZoneInfo`, intercettando `ZoneInfoNotFoundError` e `ValueError`. Timeout > 0, `MAX_STEPS` ≥ 1.

- [ ] **Step 5: Verifica che passino.** `python -m pytest tests/test_config.py -v`. Atteso: tutti PASS.

- [ ] **Step 6: Commit.** `chore: aggiunge struttura, dipendenze e configurazione` (requirements, `.gitignore`, `.env.example`, `assistant/`, `tests/`).

### Task 2: Strumento orologio

**Files:**
- Create: `assistant/tools.py`, `tests/test_tools.py`

**Interfaces:**
- Produces:
  - `utc_now() -> datetime`: istante attuale con `tzinfo=UTC`.
  - `make_clock_tool(default_timezone: str, now: Callable[[], datetime] = utc_now) -> BaseTool`: strumento `get_current_time` con parametro `timezone: str | None = None`. La descrizione per il modello dice che il fuso è un nome IANA e che, se omesso, si usa il fuso predefinito. Restituisce una stringa, mai un'eccezione. Logga a INFO su `logging.getLogger("assistant.tools")` la riga esatta delle Global Constraints, anche in caso di errore.

- [ ] **Step 1: Scrivi i test che falliscono:**

```python
FIXED = lambda: datetime(2026, 10, 26, 13, 32, 5, tzinfo=UTC)   # dopo il cambio dell'ora legale

def test_default_timezone():
    assert make_clock_tool("Europe/Rome", FIXED).invoke({}) == "Europe/Rome: 2026-10-26T14:32:05+01:00"

def test_explicit_timezone():
    assert make_clock_tool("Europe/Rome", FIXED).invoke({"timezone": "Asia/Tokyo"}) == "Asia/Tokyo: 2026-10-26T22:32:05+09:00"

def test_summer_time():
    tool = make_clock_tool("Europe/Rome", lambda: datetime(2026, 7, 1, 10, 0, tzinfo=UTC))
    assert tool.invoke({}) == "Europe/Rome: 2026-07-01T12:00:00+02:00"

@pytest.mark.parametrize("value", ["", "   ", None])
def test_blank_uses_default(value):
    assert make_clock_tool("Europe/Rome", FIXED).invoke({"timezone": value}).startswith("Europe/Rome: ")

def test_strips_spaces():
    assert make_clock_tool("Europe/Rome", FIXED).invoke({"timezone": " Asia/Tokyo "}).startswith("Asia/Tokyo: ")

@pytest.mark.parametrize("bad", ["Marte/Base", "../etc/passwd", "Europe/"])
def test_unknown_timezone(bad):
    assert make_clock_tool("Europe/Rome", FIXED).invoke({"timezone": bad}) == \
        f'Fuso orario sconosciuto: "{bad}". Usa un nome IANA, es. Europe/Rome.'

def test_logs_call(caplog):
    caplog.set_level(logging.INFO, "assistant.tools")
    make_clock_tool("Europe/Rome", FIXED).invoke({})
    assert "[strumento] get_current_time(timezone=Europe/Rome) → Europe/Rome: 2026-10-26T14:32:05+01:00" in caplog.text
```

- [ ] **Step 2: Verifica che falliscano.** `python -m pytest tests/test_tools.py -v`. Atteso: errore di import.
- [ ] **Step 3: Implementa `assistant/tools.py`.** Usa `langchain_core.tools.tool` dentro la factory, `now().astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")` e intercetta `ZoneInfoNotFoundError` e `ValueError`.
- [ ] **Step 4: Verifica che passino.** `python -m pytest tests/test_tools.py -v`. Atteso: tutti PASS.
- [ ] **Step 5: Commit.** `feat(strumenti): aggiunge l'orologio con fuso orario esplicito`.

### Task 3: Grafo LangGraph

**Files:**
- Create: `assistant/graph.py`, `tests/fakes.py`, `tests/test_graph.py`

**Interfaces:**
- Consumes: `make_clock_tool` (Task 2).
- Produces:
  - `LIMIT_MESSAGE: str` (testo delle Global Constraints).
  - `class State(TypedDict)`: `messages: Annotated[list[AnyMessage], add_messages]`, `steps: int`.
  - `system_prompt(default_timezone: str) -> str`: testo della sez. 7 della specifica con il fuso inserito.
  - `build_graph(model: BaseChatModel, tools: list[BaseTool], max_steps: int)`: grafo compilato. Nodi `"model"`, `"tools"` (`langgraph.prebuilt.ToolNode`), `"step_limit"`; instradamento come nella sez. 5 della specifica. Il chiamante invoca con `{"messages": history + [HumanMessage(text)], "steps": 0}` e legge `result["messages"]`. `history[0]` è sempre `SystemMessage(system_prompt(...))`.
  - `tests/fakes.py`: `class FakeToolModel(GenericFakeChatModel)` con `bind_tools(self, tools, **kw)` che restituisce `self`. `GenericFakeChatModel.bind_tools` solleva `NotImplementedError`: verificato su langchain-core 1.7.0. Più gli helper `tool_call(args: dict, id: str) -> AIMessage` e `fake(*msgs) -> FakeToolModel` (`messages=iter(msgs)`).

- [ ] **Step 1: Scrivi i test che falliscono.** `start(text)` restituisce `{"messages": [SystemMessage("s"), HumanMessage(text)], "steps": 0}`, il clock usa l'istante fisso `FIXED`, `max_steps=5`.

```python
def test_direct_answer():
    out = build_graph(fake(AIMessage("Ciao!")), [clock], 5).invoke(start("ciao"))
    assert out["messages"][-1].content == "Ciao!" and out["steps"] == 1

def test_tool_round_trip():
    out = build_graph(fake(tool_call({}, "a"), AIMessage("Sono le 14:32")), [clock], 5).invoke(start("che ora è?"))
    kinds = [type(m).__name__ for m in out["messages"]]
    assert kinds == ["SystemMessage", "HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert out["messages"][3].content == "Europe/Rome: 2026-10-26T14:32:05+01:00"

def test_step_limit_cleans_history():
    model = fake(*[tool_call({}, f"c{i}") for i in range(10)])
    out = build_graph(model, [clock], 5).invoke(start("che ora è?"))
    assert out["steps"] == 5
    assert [m.content for m in out["messages"][1:]] == ["che ora è?", LIMIT_MESSAGE]
    assert not any(isinstance(m, ToolMessage) for m in out["messages"])

def test_previous_turns_survive_cleanup():
    # un turno completo, poi un turno che arriva al limite: il primo turno resta intatto
    ...  # history = output del primo turno + HumanMessage; assert che i suoi 5 messaggi siano ancora presenti e in ordine

def test_wrong_tool_args_do_not_crash():
    out = build_graph(fake(tool_call({"tz": 1}, "a"), AIMessage("ok")), [clock], 5).invoke(start("ora?"))
    assert out["messages"][-1].content == "ok"    # il ToolMessage d'errore è tornato al modello

def test_two_calls_in_one_message():
    msg = AIMessage("", tool_calls=[{"name": "get_current_time", "args": {}, "id": "a"},
                                    {"name": "get_current_time", "args": {"timezone": "Asia/Tokyo"}, "id": "b"}])
    out = build_graph(fake(msg, AIMessage("ok")), [clock], 5).invoke(start("ora a Roma e Tokyo?"))
    assert sum(isinstance(m, ToolMessage) for m in out["messages"]) == 2

def test_system_prompt_mentions_timezone_and_tool():
    p = system_prompt("Asia/Tokyo")
    assert "Asia/Tokyo" in p and "get_current_time" in p and "italiano" in p

def test_limit_logged(caplog): ...  # caplog INFO "assistant.graph": contiene "limite di passaggi"
```

- [ ] **Step 2: Verifica che falliscano.** `python -m pytest tests/test_graph.py -v`. Atteso: errore di import.
- [ ] **Step 3: Implementa `assistant/graph.py`.**
  - Il nodo `model` invoca `model.bind_tools(tools)` sulla cronologia e restituisce `{"messages": [risposta], "steps": steps + 1}`.
  - Il nodo `step_limit` cerca l'indice dell'ultimo `HumanMessage` e restituisce `RemoveMessage(id=m.id)` per ogni messaggio successivo, più `AIMessage(LIMIT_MESSAGE)`. Gli id li assegna già `add_messages` (verificato).
  - Log su `assistant.graph`: a DEBUG nodo, instradamento, `steps/max_steps` e messaggi rimossi; a INFO `[grafo] limite di passaggi raggiunto (5/5)`.
- [ ] **Step 4: Verifica che passino.** `python -m pytest -v`. Atteso: tutti PASS, anche i task precedenti.
- [ ] **Step 5: Commit.** `feat(grafo): aggiunge grafo con orologio e limite di passaggi`.

### Task 4: Collegamento a LM Studio

**Files:**
- Create: `assistant/llm.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: `Settings` (Task 1).
- Produces:
  - `class LMStudioUnavailable(Exception)`: il messaggio contiene l'URL provato.
  - `class ModelNotFound(Exception)`: attributo `available: list[str]`; il messaggio elenca i modelli disponibili.
  - `list_models(base_url: str, timeout: float) -> list[str]`: `GET {base_url.rstrip('/')}/models` con `urllib.request`, senza dipendenze nuove. Restituisce gli `id` di `data`. Gli errori di rete o di JSON diventano `LMStudioUnavailable`.
  - `check_model(settings: Settings) -> None`: solleva `ModelNotFound` se `settings.model` non è fra i modelli.
  - `build_chat_model(settings: Settings) -> ChatOpenAI`: `base_url`, `model`, `api_key="lm-studio"`, `timeout`, `temperature`, `max_retries=0` (il timeout resta quello dichiarato).

- [ ] **Step 1: Scrivi i test che falliscono.** Usano un `http.server.ThreadingHTTPServer` locale su porta 0, in un thread (fixture), che risponde a `/v1/models` con `{"data": [{"id": "google/gemma-4-e2b"}, {"id": "altro"}]}`.

```python
def test_list_models(server): assert list_models(f"{server}/v1", 5) == ["google/gemma-4-e2b", "altro"]
def test_trailing_slash(server): assert list_models(f"{server}/v1/", 5) == ["google/gemma-4-e2b", "altro"]
def test_unreachable():
    with pytest.raises(LMStudioUnavailable, match="127.0.0.1:9"): list_models("http://127.0.0.1:9/v1", 2)
def test_model_missing(server):
    with pytest.raises(ModelNotFound) as e: check_model(settings(f"{server}/v1", "inventato"))
    assert e.value.available == ["google/gemma-4-e2b", "altro"]
def test_model_present(server): check_model(settings(f"{server}/v1", "google/gemma-4-e2b"))
def test_build_chat_model():
    m = build_chat_model(settings("http://h:1234/v1", "google/gemma-4-e2b"))
    assert (m.model_name, m.max_retries, m.temperature) == ("google/gemma-4-e2b", 0, 0.2)
```

- [ ] **Step 2: Verifica che falliscano.** `python -m pytest tests/test_llm.py -v`. Atteso: errore di import.
- [ ] **Step 3: Implementa `assistant/llm.py`.**
- [ ] **Step 4: Verifica che passino.** `python -m pytest -v`. Atteso: tutti PASS.
- [ ] **Step 5: Commit.** `feat(modello): aggiunge il collegamento a LM Studio con verifica del modello`.

### Task 5: Interfaccia da terminale e avvio

**Files:**
- Create: `assistant/cli.py`, `assistant/__main__.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_settings`, `ConfigError`, `make_clock_tool`, `build_graph`, `system_prompt`, `check_model`, `build_chat_model`, `LMStudioUnavailable`, `ModelNotFound`.
- Produces:
  - `run(graph, settings: Settings, input_fn=input, output_fn=print) -> int`: ciclo della sessione. Restituisce sempre 0.
    - All'avvio stampa le due righe della sez. 4 della specifica.
    - Comandi senza distinzione maiuscole/minuscole e con spazi ai bordi rimossi: `help`, `clear` (conferma `Cronologia svuotata.`), `quit` ed `exit`. La riga vuota è ignorata.
    - Prima di ogni invocazione stampa `…sto pensando`.
    - `EOFError` e `KeyboardInterrupt`, sia sull'input sia durante l'invocazione, portano a `Arrivederci!`.
    - Se l'invocazione fallisce, la cronologia resta quella di prima e compare un messaggio:
      - `openai.APITimeoutError` (va intercettato prima del genitore `APIConnectionError`): timeout di N secondi, riprova;
      - `openai.APIConnectionError`: LM Studio non raggiungibile all'URL;
      - `openai.BadRequestError` con "context" nel testo (senza distinzione maiuscole/minuscole): contesto pieno, usa `clear`;
      - altri `openai.APIError`: messaggio generico con il dettaglio.
  - `assistant/__main__.py` con `main() -> int`:
    - `load_dotenv()` e `load_settings(os.environ)`;
    - `configure_logging(level)`: formato `%(message)s` se il livello non è DEBUG, altrimenti `%(asctime)s %(levelname)s %(name)s: %(message)s`; su stderr; `httpx`, `openai` e `httpcore` a WARNING salvo DEBUG;
    - `check_model`, poi `build_graph(build_chat_model(s), [make_clock_tool(s.default_timezone)], s.max_steps)` e `run(...)`;
    - con `ConfigError`, `LMStudioUnavailable` o `ModelNotFound`: messaggio su stderr e codice 1.
    - In fondo, `raise SystemExit(main())`.

- [ ] **Step 1: Scrivi i test che falliscono.** `inputs(*lines)` produce un `input_fn` che restituisce le righe e poi solleva `EOFError`. `output_fn` raccoglie in una lista. Il grafo è un `build_graph` con `fake(...)`, oppure uno stub con `invoke` che solleva l'eccezione voluta.

```python
def test_conversation_keeps_history(): ...   # due domande; al 2° invoke l'input contiene la 1ª domanda e la 1ª risposta
def test_clear_resets_history(): ...         # dopo "clear" l'input del grafo contiene solo SystemMessage + nuova domanda; output contiene "Cronologia svuotata."
@pytest.mark.parametrize("cmd", ["quit", "EXIT", "  Quit  "])
def test_quit_commands(cmd): ...             # run(...) == 0, "Arrivederci!" in output, il grafo non è mai invocato
def test_help_lists_commands(): ...          # output contiene "help", "clear", "quit", "exit", "Ctrl+C"
def test_blank_line_ignored(): ...           # "" e "   " non invocano il grafo
def test_eof_exits_cleanly(): ...            # nessun input → codice 0, "Arrivederci!"
def test_ctrl_c_during_model(): ...          # invoke solleva KeyboardInterrupt → codice 0, "Arrivederci!"
@pytest.mark.parametrize("exc,expected", [
    (openai.APITimeoutError(request=REQ), "120"),
    (openai.APIConnectionError(request=REQ), "http://localhost:1234/v1"),
    (bad_request("context length exceeded"), "clear")])
def test_model_errors_keep_session(exc, expected): ...  # messaggio contiene expected; la domanda successiva va a buon fine e la sua cronologia non contiene la domanda fallita
```

`REQ = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")`. `bad_request(text)` costruisce `openai.BadRequestError(text, response=httpx.Response(400, request=REQ), body=None)`. `httpx` va usato solo nei test: è già presente come dipendenza di `openai`.

- [ ] **Step 2: Verifica che falliscano.** `python -m pytest tests/test_cli.py -v`. Atteso: errore di import.
- [ ] **Step 3: Implementa `assistant/cli.py` e `assistant/__main__.py`.**
- [ ] **Step 4: Verifica che passino.** `python -m pytest -v`. Atteso: tutti PASS.
- [ ] **Step 5: Verifica d'avvio senza modello.**
  - Senza `.env`: `python -m assistant` mostra il messaggio su `LMSTUDIO_BASE_URL` e termina con exit code 1, senza traceback.
  - Con `.env` copiato da `.env.example`: si avvia con LM Studio attivo e termina con `quit`. Registra l'esito.
- [ ] **Step 6: Commit.** `feat(cli): aggiunge l'interfaccia da terminale e l'avvio`.

### Task 6: Docker Compose

**Files:**
- Create: `Dockerfile`, `compose.yaml`, `.dockerignore`

**Interfaces:**
- Consumes: `python -m assistant` (Task 5).

- [ ] **Step 1: Scrivi `Dockerfile`.** `FROM python:3.14-slim`, `ENV PYTHONUNBUFFERED=1`. Installa solo `requirements.txt` (senza dev). Copia `assistant/` in `/app`, poi `useradd` un utente non root e `CMD ["python", "-m", "assistant"]`.
- [ ] **Step 2: Scrivi `.dockerignore`** (`.venv`, `.env`, `.git`, `__pycache__`, `.pytest_cache`, `tests`, `docs`, `lezione-03`).
- [ ] **Step 3: Scrivi `compose.yaml`.** Servizio `app` con `build: .`, `env_file: .env`, `environment: LMSTUDIO_BASE_URL: http://host.docker.internal:1234/v1` (sovrascrive il valore locale del `.env`), `stdin_open: true`, `tty: true`, `extra_hosts: ["host.docker.internal:host-gateway"]`.
- [ ] **Step 4: Verifica il build.** `docker compose build`. Atteso: build completato.
- [ ] **Step 5: Verifica la configurazione.** `docker compose config` mostra `LMSTUDIO_BASE_URL` con `host.docker.internal`. Poi `docker compose run --rm app python -c "import assistant, zoneinfo; print(zoneinfo.ZoneInfo('Europe/Rome'))"`, che deve stampare `Europe/Rome`.
- [ ] **Step 6: Commit.** `build(docker): aggiunge Dockerfile e Compose`.

### Task 7: README, prova reale e CLAUDE.md

**Files:**
- Create: `README.md` (nuovo, nella radice del progetto accanto a `CLAUDE.md`; il README in `lezione-03/` non va letto né usato come base)
- Modify: `CLAUDE.md` (aggiungere le sezioni struttura e comandi; la modifica non committata dell'utente va inclusa solo con il suo consenso)

- [ ] **Step 1: Scrivi `README.md` in italiano.** Sezioni:
  - requisiti: Python 3.14, Docker Desktop, LM Studio con il server attivo;
  - configurazione: copia di `.env.example` e scelta dell'id da `GET /v1/models` (`Invoke-RestMethod http://localhost:1234/v1/models`);
  - avvio locale con PowerShell (venv, `pip install -r requirements.txt`, `python -m assistant`);
  - avvio con Docker (`docker compose build`, `docker compose run --rm app`);
  - comandi;
  - log e `LOG_LEVEL`;
  - test (`pip install -r requirements-dev.txt`, `python -m pytest`);
  - prova reale (sez. 14 della specifica, con l'esito atteso per ogni passo);
  - diagnosi (una riga per ogni caso della sez. 10, più "container non raggiunge LM Studio").
- [ ] **Step 2: Esegui la prova reale in locale.** È esplicita e richiede LM Studio con `google/gemma-4-e2b`. Segui i passi 2-6 del README e annota gli esiti reali, compreso se il modello chiama davvero lo strumento e se converte "Tokyo" in `Asia/Tokyo`.
- [ ] **Step 3: Esegui la prova reale con Docker** (`docker compose run --rm app`), con gli stessi passi. Se il container non raggiunge LM Studio, attiva in LM Studio l'opzione per servire sulla rete locale e riprova. Scrivi nel README che cosa è servito davvero.
- [ ] **Step 4: Togli dal README i comandi non verificati** o marcali come tali. Aggiorna `CLAUDE.md` con struttura e comandi di test stabili.
- [ ] **Step 5: Verifica finale.** `python -m pytest -v` (tutti PASS) e `git status` (nessun `.env`, `.venv` o cache fra i file da aggiungere).
- [ ] **Step 6: Commit.** `docs: aggiunge README con avvio, test, prova reale e diagnosi`. Nel resoconto all'utente: cosa è stato eseguito, con quale esito e cosa resta da provare.
