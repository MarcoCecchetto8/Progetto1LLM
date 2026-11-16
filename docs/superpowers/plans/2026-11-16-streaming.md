# Streaming di ragionamento, strumenti e risposta — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** durante ogni turno il terminale mostra in tempo reale il ragionamento del modello (grigio, spegnibile), le chiamate agli strumenti con il loro esito e la risposta token per token; Ctrl+C ferma solo il turno.

**Architecture:** `assistant/llm.py` usa una sottoclasse di `ChatOpenAI` che conserva `reasoning_content` nei pezzi dello streaming; il nodo `model` del grafo lo toglie dal messaggio salvato. Un nuovo modulo `assistant/stream_view.py` contiene `TurnView` (scrive sul terminale: sezioni, colori, intestazioni) e `stream_turn` (legge `graph.stream(..., stream_mode=["messages", "updates", "values"])` e chiama `TurnView`). `assistant/cli.py` usa `stream_turn` al posto di `graph.invoke`. Il servizio delle note parte in un gruppo di processi separato, così il Ctrl+C non lo raggiunge.

**Tech Stack:** Python 3.14, LangGraph 1.2.17, langchain-core 1.7.0, langchain-openai 1.7.2; nessuna nuova dipendenza (colori con sequenze ANSI).

**Spec:** `docs/superpowers/specs/2026-11-16-streaming-design.md`

**Verificato prima del piano (spike nello scratchpad, 2026-11-16, grafo vero + LM Studio, «Che ore sono a Tokyo?»):** con la sottoclasse e `graph.stream(stream_mode=["messages", "updates", "values"])` arrivano, in modalità `messages`, `AIMessageChunk` del nodo `model` con `additional_kwargs["reasoning_content"]` (97), con `tool_call_chunks` (10) e con `content` (40), più un `ToolMessage` del nodo `tools` (da ignorare in quella modalità); in modalità `updates` arrivano `model`, `tools`, `model`. Senza intervento il ragionamento accumulato **resta** nel messaggio salvato (207 e 205 caratteri): va tolto. Il server MCP parte già isolato dal Ctrl+C (`start_new_session=True` su POSIX, `CREATE_NO_WINDOW` su Windows, nel pacchetto `mcp`); il servizio delle note (`subprocess.Popen(command)` in `assistant/notes.py`) no.

## Global Constraints

- Branch `feature/streaming` da `developer` (lo crea il controller prima del Task 1); nessun push, nessun merge senza l'ok dell'utente.
- Pezzi piccoli, un commit per task; prima di ogni commit `git status`, diff, staging selettivo; controllare l'**exit code** di pytest (`.venv/Scripts/python.exe -m pytest -q` dalla radice).
- Conventional Commits in italiano, con la riga finale `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nomi nel codice in inglese, testi per l'utente in italiano.
- Testi esatti:
  - `REASONING_HEADER = "[ragionamento]"`
  - riga di chiamata: `[strumento] <nome> <argomenti in JSON, ensure_ascii=False>` (es. `[strumento] get_current_time {"timezone": "Asia/Tokyo"}`)
  - riga d'esito: `[strumento] <nome> → <contenuto>`; con errore: `[strumento] <nome> errore → <contenuto>`
  - `INTERRUPTED = "Risposta interrotta."`
  - `THINKING = "…sto pensando"` (il testo di oggi)
  - colori: attenuato `"\x1b[2m"`, ripristino `"\x1b[0m"`; solo il ragionamento e la sua intestazione sono attenuati.
- Il ragionamento non entra mai nella cronologia né nei messaggi rimandati al modello.
- La chiave del ragionamento nei pezzi è `REASONING_KEY = "reasoning_content"` (in `additional_kwargs`), definita in `assistant/llm.py`.
- Non leggere né modificare `lezione-03/`.

## Review Focus

1. **Risposta del modello che arriva senza pezzi in streaming** (modelli finti, o un provider che non manda token): la risposta va comunque mostrata una volta, prendendola dall'aggiornamento del nodo `model`. Test nel Task 3.
2. **Ctrl+C alla domanda `[s/N]`** (la conferma gira in un thread del `ToolNode`): resta il comportamento attuale (nulla eliminato, l'assistente si chiude), non «Risposta interrotta.». Test nel Task 4.
3. **Errore a metà streaming** (timeout di LM Studio dopo una parte della risposta): il messaggio d'errore va su una riga nuova, cronologia invariata. Test nel Task 4.
4. **Avviso dei falsi successi**: compare una volta sola, in fondo, e la risposta non viene ristampata. Test nel Task 3.
5. **Uscita non su terminale**: nessun carattere `\x1b` nell'uscita. Test nel Task 3.

---

### Task 1: Ragionamento dal modello, tolto dalla cronologia; log degli strumenti a DEBUG

**Files:**
- Modify: `assistant/llm.py`, `assistant/graph.py`
- Test: `tests/test_llm.py`, `tests/test_graph.py`

**Interfaces:**
- Produces: `REASONING_KEY = "reasoning_content"`; `class ReasoningChatOpenAI(ChatOpenAI)` in `assistant/llm.py`; `build_chat_model(settings)` restituisce un `ReasoningChatOpenAI` (stessi parametri di oggi). Nel grafo, il messaggio che il nodo `model` mette nello stato non ha `REASONING_KEY` in `additional_kwargs`.

- [ ] **Step 1: Write the failing tests**
  - `tests/test_llm.py::test_reasoning_kept_in_stream_chunk`: istanza di `ReasoningChatOpenAI` (base_url finta, nessuna rete); chiamare `_convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)` con `chunk = {"choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": "Thinking"}, "finish_reason": None}], "id": "x", "model": "m", "object": "chat.completion.chunk", "created": 0}` → `result.message.additional_kwargs[REASONING_KEY] == "Thinking"`; con `delta = {"content": "Ciao"}` → nessuna chiave `REASONING_KEY` e `content == "Ciao"`; con `"choices": []` → nessuna eccezione.
  - `tests/test_llm.py::test_build_chat_model_keeps_reasoning`: `isinstance(build_chat_model(settings), ReasoningChatOpenAI)`.
  - `tests/test_graph.py::test_reasoning_not_saved_in_history`: modello finto che restituisce `AIMessage("ok", additional_kwargs={REASONING_KEY: "pensiero", "altro": 1})` → nel risultato l'ultimo messaggio ha `content == "ok"`, nessuna `REASONING_KEY`, `additional_kwargs["altro"] == 1` (si toglie solo il ragionamento). Stesso controllo per un messaggio con `tool_calls` (il `ToolMessage` correlato c'è ancora).
  - `tests/test_graph.py`: il test esistente che controlla il log `[strumento]` (`test_tool_call_logged_with_call_id`) passa a `caplog.at_level(logging.DEBUG, ...)`; nuovo `test_tool_call_not_logged_at_info`: a livello `INFO` nessuna riga `[strumento]`.

- [ ] **Step 2: Run to verify they fail** — `.venv/Scripts/python.exe -m pytest tests/test_llm.py tests/test_graph.py -q` → ImportError su `ReasoningChatOpenAI`/`REASONING_KEY` e fallimenti sul ragionamento e sul livello del log.

- [ ] **Step 3: Implement**
  - `ReasoningChatOpenAI._convert_chunk_to_generation_chunk(self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None)`: chiama `super()`; se il risultato non è `None` e `chunk["choices"][0]["delta"]` contiene un `reasoning_content` non vuoto, lo copia in `result.message.additional_kwargs[REASONING_KEY]`. Commento breve: perché serve (langchain-openai lo scarta, verificato con la 1.7.2).
  - `model_node`: dopo `invoke`, se `REASONING_KEY` è in `response.additional_kwargs`, sostituire la risposta con `response.model_copy(update={"additional_kwargs": <senza quella chiave>})` (stesso `id`, `tool_calls` intatti).
  - `log_tool_calls`: `logger.info` → `logger.debug` (stesso testo).

- [ ] **Step 4: Run tests** — suite completa verde (exit code 0).

- [ ] **Step 5: Commit** — `feat(modello): conserva il ragionamento in streaming e lo esclude dalla cronologia`.

### Task 2: Variabile SHOW_REASONING

**Files:**
- Modify: `assistant/config.py`, `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.show_reasoning: bool = True` (campo con valore predefinito, in fondo come `notes_service_url`), letto da `SHOW_REASONING`.

- [ ] **Step 1: Write the failing tests** in `tests/test_config.py`: assente → `True`; `"true"`, `"TRUE"`, `" True "` → `True`; `"false"`, `"False"` → `False`; `"forse"` → `ConfigError` con messaggio `SHOW_REASONING non valida: 'forse' (valori ammessi: true, false).`
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** in `load_settings` con `_get(env, "SHOW_REASONING", "true").lower()`, nello stile di `LOG_LEVEL`. In `.env.example` aggiungere, con un commento di una riga in italiano: `SHOW_REASONING=true`. Compose legge già `.env` (`env_file`), nessuna modifica a `compose.yaml`.
- [ ] **Step 4: Run tests** — suite verde.
- [ ] **Step 5: Commit** — `feat(config): aggiunge SHOW_REASONING per mostrare o nascondere il ragionamento`.

### Task 3: Vista del turno e lettura dello streaming del grafo

**Files:**
- Create: `assistant/stream_view.py`
- Modify: `tests/fakes.py` (grafo finto in streaming)
- Test: `tests/test_stream_view.py`

**Interfaces:**
- Consumes: `REASONING_KEY` (Task 1); il grafo di `build_graph` con i nodi `model`, `tools`, `step_limit`, `answer_check`.
- Produces:
  - `class TurnView(write: Callable[[str], None], color: bool, show_reasoning: bool)` con i metodi `reasoning(text)`, `answer(text)`, `tool_call(name: str, args: dict)`, `tool_result(name: str, content: str, error: bool)`, `extra(text)`, `finish()`.
  - `stream_turn(graph, state: dict, view: TurnView) -> dict` (restituisce lo stato finale, come oggi `graph.invoke`).
  - `REASONING_HEADER`, `INTERRUPTED`, `THINKING` (testi nei Global Constraints) definiti qui.
  - In `tests/fakes.py`: `class FakeStreamGraph(events: list[tuple[str, object]], final: dict)` con `stream(state, stream_mode)` che restituisce gli eventi dati e alla fine `("values", final)`.

**Regole di `TurnView` (decise qui):**
- Tiene la sezione corrente (`None`, `"reasoning"`, `"answer"`) e se l'ultimo carattere scritto è un a capo.
- `reasoning(text)`: ignorato se `show_reasoning` è falso; se la sezione non è già `"reasoning"`, va a capo se serve e scrive `REASONING_HEADER` + `"\n"`; poi scrive `text`. Con `color`, intestazione e ogni frammento sono racchiusi fra attenuato e ripristino.
- `answer(text)`: se la sezione non è già `"answer"`, va a capo se serve (e, se c'era ragionamento, la risposta parte su una riga nuova); scrive `text` senza colori.
- `tool_call` / `tool_result` / `extra`: vanno a capo se serve, scrivono la riga completa + `"\n"`, sezione `None`.
- `finish()`: va a capo se l'ultimo carattere non è un a capo. Senza `color` non si scrive mai `"\x1b"`.

**Regole di `stream_turn` (decise qui):**
- `graph.stream(state, stream_mode=["messages", "updates", "values"])`; ogni elemento è `(mode, payload)`.
- `messages`: solo `AIMessageChunk` con `metadata["langgraph_node"] == "model"`; `additional_kwargs[REASONING_KEY]` (stringa non vuota) → `view.reasoning`; `content` stringa non vuota → `view.answer`. Tutto il resto si ignora (per esempio il `ToolMessage` del nodo `tools`).
- `updates` (`{nodo: aggiornamento}`, aggiornamento eventualmente `None`):
  - `model`: l'`AIMessage` aggiornato; se in questo passaggio non è arrivato nessun pezzo di risposta e il messaggio ha `content` stringa non vuoto → `view.answer(content)` (Review Focus 1); per ogni `tool_call` → `view.tool_call(name, args)`; ricorda il `content` come testo già mostrato.
  - `tools`: per ogni `ToolMessage` → `view.tool_result(m.name, m.content, m.status == "error")`.
  - `answer_check`: nuovo contenuto dell'ultimo messaggio; se inizia con il testo già mostrato, `view.extra` della parte aggiunta senza gli a capo iniziali; altrimenti `view.extra` del contenuto intero.
  - `step_limit`: `view.extra` del contenuto dell'`AIMessage` aggiunto (`LIMIT_MESSAGE`).
- `values`: l'ultimo è lo stato finale restituito.
- `view.finish()` sempre, anche con eccezione (`try/finally`); le eccezioni (compreso `KeyboardInterrupt`) si propagano.

- [ ] **Step 1: Write the failing tests** in `tests/test_stream_view.py` (con `write` che accumula in una lista e `"".join`):
  - `test_reasoning_then_answer_plain`: `color=False` → `"[ragionamento]\nPenso.\nCiao!\n"` per `reasoning("Pen")`, `reasoning("so.")`, `answer("Ciao")`, `answer("!")`, `finish()`; nessun `"\x1b"`.
  - `test_reasoning_dimmed_with_color`: `color=True` → l'intestazione e i frammenti del ragionamento fra `"\x1b[2m"` e `"\x1b[0m"`; la risposta senza sequenze.
  - `test_reasoning_hidden`: `show_reasoning=False` → solo `"Ciao!\n"`.
  - `test_tool_lines`: `tool_call("get_current_time", {"timezone": "Asia/Tokyo"})`, `tool_result("get_current_time", "Asia/Tokyo: 22:32", False)`, `tool_result("add_note", "Errore: x", True)` → righe esatte dei Global Constraints, ciascuna su una riga, dopo un ragionamento non terminato da a capo.
  - `test_stream_turn_order`: `FakeStreamGraph` con eventi: pezzi di ragionamento del nodo `model`, aggiornamento `model` con una `tool_call`, un `ToolMessage` in modalità `messages` dal nodo `tools` (da ignorare), aggiornamento `tools`, pezzi di risposta, aggiornamento `model` finale → testo atteso esatto e stato finale restituito.
  - `test_stream_turn_answer_without_chunks`: solo l'aggiornamento `model` con `AIMessage("ok")` → `"ok\n"` una volta.
  - `test_stream_turn_warning_once`: pezzi `"Ho salvato la nota."`, aggiornamento `model`, aggiornamento `answer_check` con `"Ho salvato la nota.\n\n⚠ Attenzione: …"` → la risposta compare una volta e l'avviso una volta, su una riga sua.
  - `test_stream_turn_step_limit`: aggiornamento `step_limit` con `AIMessage(LIMIT_MESSAGE)` → `LIMIT_MESSAGE` stampato.
  - `test_stream_turn_finishes_line_on_error`: grafo finto che solleva `RuntimeError` dopo un pezzo di risposta → l'eccezione si propaga e l'uscita termina con `"\n"`.
  - `test_stream_turn_with_real_graph`: `build_graph(fake(...), [clock], 5)` con `tool_call` + `AIMessage("Sono le 14:32")` → l'uscita contiene la riga di chiamata, la riga d'esito e `Sono le 14:32` una sola volta; lo stato finale è uguale a quello di `invoke`.
- [ ] **Step 2: Run to verify they fail** (`ModuleNotFoundError`).
- [ ] **Step 3: Implement** `assistant/stream_view.py` secondo le Regole; `FakeStreamGraph` in `tests/fakes.py`.
- [ ] **Step 4: Run tests** — suite verde.
- [ ] **Step 5: Commit** — `feat(cli): mostra ragionamento, strumenti e risposta mentre arrivano`.

### Task 4: Ciclo da terminale in streaming e Ctrl+C che ferma il turno

**Files:**
- Modify: `assistant/cli.py`, `assistant/notes.py`
- Test: `tests/test_cli.py`, `tests/test_notes_tools.py`

**Interfaces:**
- Consumes: `TurnView`, `stream_turn`, `INTERRUPTED`, `THINKING` (Task 3); `Settings.show_reasoning` (Task 2).
- Produces:
  - `run(graph, settings, input_fn=input, output_fn=print, clear_fn=clear_screen, newline_on_interrupt=..., write_fn=None, color=False)`; con `write_fn=None` scrive su `sys.stdout` con `flush` a ogni frammento.
  - In `assistant/notes.py`: `confirmation_pending() -> bool` e `reset_confirmation() -> None`. `ask_in_terminal` segna la conferma come in corso prima di `input` e la azzera **solo** quando arriva una risposta normale; con `EOFError` o `KeyboardInterrupt` resta segnata (comportamento di ritorno invariato: `EOFError` → `False`; `KeyboardInterrupt` → `False` anche lui, così il thread dello strumento non elimina nulla).

**Comportamento del turno (decise qui):**
- Al posto di `graph.invoke`: `reset_confirmation()`, poi se `settings.show_reasoning` è falso `output_fn(THINKING)`, poi `stream_turn(graph, stato, TurnView(write, color, settings.show_reasoning))`.
- La risposta **non** viene più stampata con `output_fn(answer)` (è già scritta in streaming). Restano: `EMPTY_ANSWER` se la risposta finale è vuota (turno fuori dalla cronologia), la cronologia aggiornata con lo stato finale, i messaggi d'errore di oggi per `openai.APIError`, `MCPConnectionError`, `NotesConnectionError` ed errori imprevisti.
- `KeyboardInterrupt` durante `stream_turn`: se `confirmation_pending()` → comportamento di oggi (uscita con «Arrivederci!»); altrimenti `output_fn(INTERRUPTED)`, cronologia invariata, si torna al prompt.
- Ctrl+C al prompt `>` e `EOF`: invariati.

- [ ] **Step 1: Write the failing tests**
  - In `tests/test_cli.py` adattare i grafi finti (`Recorder`, `Stub`) perché offrano `stream(state, stream_mode)` coerente con `invoke` (per esempio un aggiornamento `model` con la risposta e lo stato finale in `values`), e l'helper di sessione perché raccolga anche `write_fn`; le asserzioni esistenti mantengono il loro significato (la risposta compare una volta, la cronologia è quella attesa).
  - `test_ctrl_c_during_model` cambia: `Stub(KeyboardInterrupt())` con le righe `"ciao"`, `"quit"` → nell'uscita `Risposta interrotta.`, la sessione continua e termina con «Arrivederci!»; la seconda domanda non contiene la prima nella cronologia.
  - `test_ctrl_c_at_confirmation_exits`: grafo finto che, durante lo `stream`, chiama `ask_in_terminal` con un `input_fn` che solleva `KeyboardInterrupt` e poi solleva lui stesso `KeyboardInterrupt` → uscita con «Arrivederci!», nessun `Risposta interrotta.`.
  - `test_thinking_line_only_without_reasoning`: con `show_reasoning=False` compare `…sto pensando`; con `True` no.
  - `test_error_after_partial_answer`: grafo finto che scrive un pezzo di risposta e poi solleva un `openai.APITimeoutError` → il messaggio di timeout su una riga sua, cronologia invariata.
  - `test_answer_not_printed_twice`: con il grafo vero e un modello finto, il testo della risposta compare una sola volta nell'uscita complessiva.
  - In `tests/test_notes_tools.py`: `ask_in_terminal` con risposta `"s"` → `True` e `confirmation_pending()` falso; con `EOFError` → `False` e `confirmation_pending()` vero; con `KeyboardInterrupt` → `False` e `confirmation_pending()` vero; `reset_confirmation()` lo azzera.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** in `assistant/cli.py` e `assistant/notes.py` secondo il Comportamento (stato della conferma con un `threading.Event` o equivalente a livello di modulo: la conferma gira in un thread del `ToolNode`).
- [ ] **Step 4: Run tests** — suite verde.
- [ ] **Step 5: Commit** — `feat(cli): risposta in streaming e Ctrl+C che interrompe solo il turno`.

### Task 5: Processi figli protetti dal Ctrl+C, avvio e documentazione

**Files:**
- Modify: `assistant/notes.py` (`LocalNotesService.start`), `assistant/__main__.py`, `README.md`, `CLAUDE.md`
- Test: `tests/test_notes_launcher.py`

**Interfaces:**
- Consumes: `run(..., write_fn, color)` (Task 4), `Settings.show_reasoning` (Task 2).

- [ ] **Step 1: Write the failing test** `test_service_started_in_own_process_group` in `tests/test_notes_launcher.py`: sostituendo `subprocess.Popen` con un finto che registra i parametri (e un `_responds`/`wait_until_ready` finti), `start()` passa `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP` su Windows e `start_new_session=True` altrove (parametrizzare su `os.name` con monkeypatch, o verificare solo il ramo della piattaforma corrente; scelta dell'implementer, motivata nel report).
- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Implement**
  - `LocalNotesService.start`: `subprocess.Popen(command, **kw)` con `kw` come nel test; commento breve: su Windows Ctrl+C arriva a tutti i processi della console, e senza gruppo separato il servizio morirebbe quando Ctrl+C ferma solo il turno.
  - `assistant/__main__.py`: `color = sys.stdout.isatty()`; su Windows, se `color`, attivare le sequenze ANSI della console con `os.system("")` (commento: abilita l'elaborazione VT nella console classica; Windows Terminal e VS Code la hanno già); passare `color` a `run`.
  - `README.md`: sezione su che cosa si vede durante un turno (ragionamento attenuato, strumenti, risposta, avviso in fondo), `SHOW_REASONING` nella configurazione, Ctrl+C (ferma il turno; al prompt esce; alla conferma `[s/N]` esce senza eliminare), che le righe `[strumento]` del log ora si vedono con `LOG_LEVEL=DEBUG`; una riga in Diagnosi per «il ragionamento non compare» (modello che non manda `reasoning_content` o `SHOW_REASONING=false`). Tabella «Prova reale dello streaming» con gli esiti `da provare` (le righe della specifica, sezione 7).
  - `CLAUDE.md`: `stream_view.py` nella struttura di `assistant/`; nell'obiettivo/confini lo streaming della risposta non è più escluso (se il file lo dice).
- [ ] **Step 4: Run tests** — suite verde; poi avvio di prova `echo quit | .venv/Scripts/python.exe -m assistant` → codice 0, nessun traceback (se LM Studio non è raggiungibile, annotarlo nel report).
- [ ] **Step 5: Commit** — `feat(note): protegge il servizio delle note dal Ctrl+C e documenta lo streaming`.

### Dopo i task (controller, non subagent)

- Revisione finale dell'intero branch.
- Prova reale con LM Studio in locale (PowerShell) e con Docker, righe della specifica sezione 7; il controller esegue quelle possibili con input da pipe (`-T`, senza colori) e lascia all'utente quelle che richiedono un terminale vero (colori, Ctrl+C durante un ragionamento, poi domanda con strumento MCP e nota). Esiti nel README.
