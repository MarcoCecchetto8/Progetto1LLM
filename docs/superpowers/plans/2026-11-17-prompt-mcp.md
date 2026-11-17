# Prompt MCP richiamati dalla CLI — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** due prompt MCP (`spiega`, `riassumi_conversazione`) sul server e i comandi `/prompts` e `/prompt` nella CLI, con controllo degli argomenti nell'host; il testo compilato passa dal grafo come una domanda.

**Architecture:** testi e validazione in `lab_server/prompts.py`, registrati in `server.py`; `MCPClient` elenca e compila i prompt sulla sessione esistente; `assistant/prompts.py` (funzioni pure) analizza e controlla i comandi; `cli.run` li usa e manda i messaggi al grafo; `__main__` legge l'elenco all'avvio.

**Tech Stack:** Python, FastMCP 3.4.11, mcp 1.30.0, LangGraph, pytest. Nessuna nuova dipendenza.

**Spec:** `docs/superpowers/specs/2026-11-17-prompt-mcp-design.md`

## Global Constraints

- Branch `feature/prompt` da `developer`; Conventional Commits in italiano con la riga `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; `git status` e staging selettivo; nessun push; mai `.env`.
- Prompt `spiega(argomento, livello="base")`, livelli `base`, `intermedio`, `avanzato`; `riassumi_conversazione(stile="sintetico")`, stili `sintetico`, `dettagliato`. Descrizioni: «Spiega un argomento al livello richiesto.», «Riassume i turni della sessione corrente.»; argomenti: `argomento` «concetto da spiegare», `livello` «base, intermedio o avanzato», `stile` «sintetico o dettagliato».
- I messaggi d'errore della CLI sono quelli della specifica 5.3, copiati esatti nei test.
- Un comando con errore non chiama né il modello né il grafo; la cronologia non cambia.
- **Decisione del piano (scostamento dalla specifica 5.3, `shlex`)**: gli argomenti si dividono sugli spazi e **solo le virgolette doppie** raggruppano un valore con spazi; l'apostrofo è un carattere normale, così `argomento=l'IA` funziona (con `shlex` darebbe «virgolette non chiuse»). Virgolette doppie non chiuse → «Virgolette non chiuse: controlla il comando.».
- Test senza LM Studio; suite completa verde (`.venv/Scripts/python.exe -m pytest`, controllare l'exit code) prima di ogni commit.

## Review Focus

1. **Apostrofi e caratteri italiani nei valori** (`argomento=l'IA`, `argomento="perché «MCP»?"`): valore passato intatto. Test nel Task 3.
2. **Valore vuoto** (`argomento=` oppure `argomento=""`): arriva al server, che lo rifiuta con «argomento vuoto: indica il concetto da spiegare»; la CLI mostra «Il server ha rifiutato il prompt: …» senza chiamare il grafo. Test nei Task 1 e 4.
3. **Server degli strumenti caduto durante `/prompt`**: messaggio `TOOLS_DOWN` di oggi, nessun traceback, cronologia invariata. Test nel Task 4.
4. **Ctrl+C durante il turno di un prompt**: come una domanda («Risposta interrotta.»), cronologia invariata. Test nel Task 4.
5. **Maiuscole nei comandi** (`/PROMPTS`, `/Prompt spiega …`): i comandi si riconoscono senza distinguere maiuscole (come `help`/`clear`), il **nome del prompt** e degli argomenti invece si confrontano esatti. Test nel Task 4.

---

### Task 1: Prompt sul server MCP e elenco in `check`

**Files:**
- Create: `lab_server/prompts.py`
- Modify: `lab_server/server.py`, `lab_server/check.py`
- Test: `tests/test_server_prompts.py`, `tests/test_check.py`

**Interfaces:**
- Produces in `lab_server/prompts.py`:
  - `LEVELS: dict[str, str]` = `{"base": "Usa parole semplici, spiega i termini tecnici e fai un esempio concreto.", "intermedio": "Dai per note le basi: spiega come funziona, con un esempio.", "avanzato": "Entra nei dettagli tecnici: funzionamento interno, scelte di progetto e limiti."}`
  - `SUMMARY_STYLES: dict[str, str]` = `{"sintetico": "in poche frasi, solo gli argomenti principali.", "dettagliato": "per ogni argomento, che cosa è stato chiesto e che cosa è stato risposto, in un breve elenco."}`
  - `explain_text(argomento: str, livello: str = "base") -> str` → `f"Spiegami «{argomento.strip()}» a livello {livello}. {LEVELS[livello]}"`; `ValueError("argomento vuoto: indica il concetto da spiegare")` se vuoto o solo spazi; `ValueError(f"livello '{livello}' non ammesso (ammessi: base, intermedio, avanzato)")`.
  - `summary_text(stile: str = "sintetico") -> str` → `"Riassumi la conversazione fin qui, basandoti solo sui messaggi precedenti e senza usare strumenti: " + SUMMARY_STYLES[stile]`; `ValueError(f"stile '{stile}' non ammesso (ammessi: sintetico, dettagliato)")`.
- `create_server` registra sempre i due prompt (`@mcp.prompt(name="spiega")`, `@mcp.prompt(name="riassumi_conversazione")`), argomenti `Annotated[str, Field(description=...)]` con le descrizioni delle Global Constraints e le docstring come descrizioni; il `ValueError` passa al client come errore (verificato nella specifica, 2).
- `check.py` senza argomenti, dopo le resource: per ogni prompt `prompt <nome>: <descrizione>` e per ogni argomento `  <nome> (obbligatorio|facoltativo): <descrizione fino al primo "\n\n">`.

- [ ] **Step 1: Test che falliscono**:
  - `explain_text("MCP")` == `"Spiegami «MCP» a livello base. Usa parole semplici, spiega i termini tecnici e fai un esempio concreto."`; un test per `intermedio` e `avanzato` con il testo esatto; `explain_text("  ")` e `explain_text("MCP", "esperto")` → `ValueError` con il messaggio esatto.
  - `summary_text()` e `summary_text("dettagliato")` testi esatti; `summary_text("lungo")` → `ValueError` esatto.
  - server in memoria (`fastmcp.Client(create_server("Europe/Rome", FIXED))`): `list_prompts` → `spiega` (argomento `required=True`, livello `False`) e `riassumi_conversazione` (stile `False`), descrizioni esatte (per gli argomenti, la parte prima di `"\n\n"`); `get_prompt("spiega", {"argomento": "MCP", "livello": "avanzato"})` → un messaggio `user` col testo di `explain_text`; `get_prompt("spiega", {"argomento": "MCP", "livello": "esperto"})` → eccezione il cui testo contiene `livello 'esperto' non ammesso`; `argomento=""` → eccezione con `argomento vuoto` (Review Focus 2).
  - `test_check_lists_prompts` (come `test_check_lists_resource`, con `capfd`): righe `prompt spiega: Spiega un argomento al livello richiesto.` e `  argomento (obbligatorio): concetto da spiegare`.
- [ ] **Step 2: Verificare che falliscano.**
- [ ] **Step 3: Implementare.**
- [ ] **Step 4: Suite verde**; a mano `python -m lab_server.check` mostra i due prompt.
- [ ] **Step 5: Commit** — `feat(server): prompt spiega e riassumi_conversazione`.

### Task 2: Prompt nel client MCP

**Files:**
- Modify: `assistant/mcp_client.py`, `tests/mcp_test_server.py`
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Produces in `assistant/mcp_client.py`:
  - `@dataclass(frozen=True) class PromptArgument: name: str; description: str; required: bool`
  - `@dataclass(frozen=True) class PromptInfo: name: str; description: str; arguments: tuple[PromptArgument, ...]`
  - `class MCPPromptError(Exception)`
  - `MCPClient.list_prompts() -> list[PromptInfo]`: descrizioni degli argomenti ridotte alla parte prima di `"\n\n"`, descrizione mancante → `""`, `required` mancante → `False`.
  - `MCPClient.get_prompt(name: str, arguments: dict[str, str]) -> list[tuple[str, str]]`: `(ruolo, testo)` per ogni messaggio di testo.
  - Errori come `read_resource`: `McpError` con codice in `CONNECTION_CODES`, timeout, sessione chiusa o altro → `MCPConnectionError`; altro `McpError` → `MCPPromptError` (per `get_prompt`) con il prefisso `Error rendering prompt '<nome>': ` tolto se presente. Estrarre l'attesa sulla sessione e la mappatura degli errori in un metodo privato comune a `read_resource`, `list_prompts` e `get_prompt` (stesso comportamento di oggi per `read_resource`; i suoi test restano verdi).
  - `tests/mcp_test_server.py`: prompt `saluta(nome: str)` → `f"Saluta {nome}."` con docstring «Prompt di prova.» e prompt `rotto()` che solleva `ValueError("prompt rotto")`.
- [ ] **Step 1: Test che falliscono**: `list_prompts()` contiene `PromptInfo("saluta", "Prompt di prova.", (PromptArgument("nome", <descrizione senza la frase di FastMCP>, True),))` (la descrizione non contiene `"Provide as a JSON string"`); `get_prompt("saluta", {"nome": "Marco"}) == [("user", "Saluta Marco.")]`; `get_prompt("rotto", {})` → `MCPPromptError` con testo `"prompt rotto"` (senza `Error rendering prompt`), e subito dopo `echo` funziona; `get_prompt("inesistente", {})` → `MCPPromptError`; dopo il crash del server (`die`) `get_prompt` → `MCPConnectionError`; i test esistenti di `read_resource` restano verdi.
- [ ] **Step 2: Verificare che falliscano.**
- [ ] **Step 3: Implementare.**
- [ ] **Step 4: Suite verde.**
- [ ] **Step 5: Commit** — `feat(mcp): elenco e compilazione dei prompt nel client`.

### Task 3: Analisi e controllo dei comandi

**Files:**
- Create: `assistant/prompts.py`
- Test: `tests/test_prompts_command.py`

**Interfaces:**
- Consumes: `PromptInfo`, `PromptArgument` (Task 2).
- Produces in `assistant/prompts.py`:
  - `class PromptCommandError(Exception)` (il messaggio è il testo da mostrare).
  - `format_prompt_list(prompts: list[PromptInfo]) -> str`: formato della specifica 5.3 (`<nome> — <descrizione>`, poi `  <arg> (obbligatorio|facoltativo): <descrizione>`), righe unite da `\n`; lista vuota → `"Nessun prompt disponibile sul server."`.
  - `parse_prompt_command(rest: str, prompts: list[PromptInfo]) -> tuple[str, dict[str, str]]`: `rest` è il testo dopo `/prompt`. Controlli e messaggi nell'ordine 1–7 della specifica 5.3, con la divisione delle Global Constraints (solo virgolette doppie; le virgolette che racchiudono il valore si tolgono). Nell'errore 1 il testo è esattamente `Uso: /prompt <nome> argomento=valore …  (elenco con /prompts)`.
  - `prompt_messages(messages: list[tuple[str, str]]) -> list[AnyMessage]`: `user` → `HumanMessage`, `assistant` → `AIMessage`, altri ruoli ignorati.
  - `prompt_log_line(name: str, arguments: dict[str, str], messages: list[tuple[str, str]]) -> str` → `f"[prompt] {name} {json.dumps(arguments, ensure_ascii=False)} → {primo testo con gli spazi compressi}"`.
- [ ] **Step 1: Test che falliscono** (con un elenco di prova che ricalca i due prompt reali):
  - `parse_prompt_command(' spiega argomento="Model Context Protocol" livello=base', P)` == `("spiega", {"argomento": "Model Context Protocol", "livello": "base"})`.
  - Review Focus 1: `argomento=l'IA` → `"l'IA"`; `argomento="perché «MCP»?"` → `"perché «MCP»?"`.
  - Review Focus 2: `argomento=` e `argomento=""` → valore `""` (nessun errore nell'host).
  - Ogni errore 1–7 con il testo esatto della specifica: `""`; `'spiega argomento="MCP'`; `"spiegami"` (→ `Prompt sconosciuto: spiegami. Disponibili: spiega, riassumi_conversazione.`); `"spiega MCP"`; `"spiega =x"`; `"spiega argomento=a argomento=b"`; `"spiega tema=x"` (→ `Argomento sconosciuto per spiega: tema (ammessi: argomento, livello).`); `"spiega livello=base"` (→ `Argomento obbligatorio mancante per spiega: argomento.`).
  - `format_prompt_list` sul formato atteso della specifica e sulla lista vuota.
  - `prompt_messages([("user", "a"), ("assistant", "b")])` → `[HumanMessage("a"), AIMessage("b")]`.
  - `prompt_log_line("spiega", {"argomento": "MCP"}, [("user", "Spiegami\n«MCP»")])` == `'[prompt] spiega {"argomento": "MCP"} → Spiegami «MCP»'`.
- [ ] **Step 2: Verificare che falliscano.**
- [ ] **Step 3: Implementare** (la divisione con una regex su token `nome=valore`, `nome="valore con spazi"` e parole; nessuna dipendenza nuova).
- [ ] **Step 4: Suite verde.**
- [ ] **Step 5: Commit** — `feat(cli): analisi e controllo dei comandi /prompt`.

### Task 4: Comandi nella CLI, avvio, ambito e documentazione

**Files:**
- Modify: `assistant/cli.py`, `assistant/__main__.py`, `config/ambito.txt`, `README.md`, `CLAUDE.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 2 (`MCPClient.list_prompts`, `get_prompt`, `MCPPromptError`, `MCPConnectionError`), Task 3 (tutte le funzioni).
- Produces: `cli.run(..., prompt_list: list[PromptInfo] = (), get_prompt: Callable[[str, dict[str, str]], list[tuple[str, str]]] | None = None)`.
  - Riconoscimento (sul testo senza spazi agli estremi, comando in minuscolo): `/prompts` → `output_fn(format_prompt_list(prompt_list))`; `/prompt` o testo che inizia con `/prompt ` → analisi; altro testo che inizia con `/` → `Comando sconosciuto: <primo token>. Comandi: help, clear, /prompts, /prompt.`. Il resto della riga di `/prompt` si passa a `parse_prompt_command` **senza** cambiare le maiuscole.
  - Esito valido: `logging.getLogger("assistant.cli").info(prompt_log_line(...))`, con più messaggi una riga `DEBUG` per ciascuno; poi lo stesso turno di una domanda con `history + prompt_messages(...)` al posto di `history + [HumanMessage(text)]` (stesso codice: estrarre il turno in una funzione interna se serve, senza cambiare il comportamento di oggi).
  - Errori: `PromptCommandError` → il suo testo; `MCPPromptError` → `f"Il server ha rifiutato il prompt: {errore}"`; `MCPConnectionError` → come durante un turno (`logger.warning` + `TOOLS_DOWN`). Senza `get_prompt` (`None`) `/prompt` risponde `Nessun prompt disponibile sul server.`.
  - `HELP_TEXT`: due righe `  /prompts    elenca i prompt del server` e `  /prompt     richiama un prompt: /prompt nome argomento=valore …`.
  - `__main__._start`: dentro il `try/except MCPConnectionError` dove oggi si leggono le preferenze, `prompt_list = client.list_prompts()` e `logging.getLogger("assistant").info("[mcp] prompt: %s", ", ".join(p.name for p in prompt_list) or "nessuno")`; `run(..., prompt_list=prompt_list, get_prompt=client.get_prompt)`.
  - `config/ambito.txt`: esempio `- «Riassumi la conversazione fin qui» → conversazione (domanda sulla conversazione)` dopo «Di cosa abbiamo parlato?».
- [ ] **Step 1: Test che falliscono** in `tests/test_cli.py` (grafo finto che registra lo stato ricevuto, `get_prompt` finto):
  - `/prompts` stampa l'elenco; `help` contiene le due righe nuove.
  - `/prompt spiega argomento="MCP"`: il grafo riceve `history + [HumanMessage(<testo dal get_prompt finto>)]`; `get_prompt` chiamato con `("spiega", {"argomento": "MCP"})`; la riga `[prompt] …` è nel log (`caplog`); a turno riuscito la cronologia contiene il messaggio del prompt.
  - Per ciascun errore (`/prompt`, `/prompt spiega tema=x`, `/prompt spiega livello=base`, `/prompt nessuno`): messaggio esatto e grafo **non** chiamato; poi una domanda normale riceve la cronologia invariata.
  - `get_prompt` che solleva `MCPPromptError("argomento vuoto: indica il concetto da spiegare")` → `Il server ha rifiutato il prompt: argomento vuoto: indica il concetto da spiegare` e grafo non chiamato (Review Focus 2).
  - `get_prompt` che solleva `MCPConnectionError` → `TOOLS_DOWN`, nessuna eccezione (Review Focus 3).
  - Ctrl+C durante il turno di un prompt (grafo finto che solleva `KeyboardInterrupt` come nei test esistenti) → messaggio di interruzione, cronologia invariata (Review Focus 4).
  - `/PROMPTS` funziona; `/Prompt spiega argomento=x` funziona; `/prompt Spiega argomento=x` → `Prompt sconosciuto: Spiega. …` (Review Focus 5).
  - `/promt x` → `Comando sconosciuto: /promt. Comandi: help, clear, /prompts, /prompt.` e grafo non chiamato.
- [ ] **Step 2: Verificare che falliscano.**
- [ ] **Step 3: Implementare** `cli.py`, `__main__.py`, `config/ambito.txt`.
- [ ] **Step 4: Suite verde**; avvio a mano con `quit` mostra la riga `[mcp] prompt: spiega, riassumi_conversazione`.
- [ ] **Step 5: Commit** — `feat(cli): comandi /prompts e /prompt`.
- [ ] **Step 6: Documentazione**: README (comandi `/prompts` e `/prompt` nella sezione d'uso e in `help`; sezione «Prompt MCP» con i due prompt, argomenti, valori, controlli ed errori, riga di log, regola delle virgolette doppie; diagnosi per «Il server ha rifiutato il prompt» e «Prompt sconosciuto»; tabella «Prova reale dei prompt» con le prove della specifica 6 come «da provare»); `CLAUDE.md` Struttura: `lab_server/prompts.py` (testi e validazione dei prompt `spiega` e `riassumi_conversazione`) e `assistant/prompts.py` (comandi `/prompts` e `/prompt`: analisi, controllo degli argomenti, testi). Commit `docs: prompt MCP e comandi /prompts e /prompt (README, CLAUDE.md)`.

### Dopo i task (controller)

- Review finale dell'intero branch.
- Prova reale con LM Studio (specifica 6, locale e Docker via pipe), esiti nel README, commit `docs: ...`.
- Ok dell'utente per merge `--no-ff` in `developer`, push, eliminazione del branch.
