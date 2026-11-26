# Riassunto della cronologia (lezione 6, step 3) — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** all'inizio di ogni turno, se la cronologia supera una soglia di token stimati, un nodo LLM sostituisce i turni vecchi con un riassunto (campo dello stato) e lascia intatti gli ultimi N turni; l'agente riceve il riassunto in cima al prompt di sistema; nel terminale compaiono la riga con i numeri e il testo del riassunto.

**Architecture:** nuovo modulo `assistant/summarizer.py` con funzioni pure (stima dei token, confini dei turni, punto di taglio, trascrizione, prompt esteso, riga del terminale) e `build_summarizer(model)`. `build_graph` riceve `summarizer`, `summary_threshold` e `summary_keep_turns` facoltativi: `START → summarizer → router|model`. `model_node` invia la cronologia con il prompt di sistema esteso dal riassunto (non salvato). `stream_view` mostra riga e testo. `cli.run` porta il riassunto da un turno all'altro e lo svuota con `clear`. `__main__` collega.

**Tech Stack:** Python 3.14, LangGraph 1.2.17, langchain-core 1.7.0, langchain-openai 1.7.2, openai; nessuna nuova dipendenza.

**Spec:** `docs/superpowers/specs/2026-11-16-riassunto-design.md`

**Verificato prima del piano (2026-11-16, sonde `probe_summary.py` nello scratchpad):** con le istruzioni qui sotto, ragionamento spento e il riassunto precedente in cima alla conversazione: primo riassunto 5/5 completo; aggiornamento: note conservate 3/3, argomenti vecchi persi 3/3 (limite accettato dall'utente). 8–14 s per riassunto.

## Global Constraints

- Branch `feature/riassunto` da `developer` (lo crea il controller); nessun push né merge senza l'ok dell'utente.
- Un commit per task; `git status`, diff, staging selettivo; exit code di pytest (`.venv/Scripts/python.exe -m pytest -q`). Conventional Commits in italiano con riga finale `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Nomi nel codice in inglese; testi per l'utente e log in italiano.
- Variabili: `SUMMARY_THRESHOLD` intero ≥ 1, default `4000`; `SUMMARY_KEEP_TURNS` intero ≥ 1, default `2`.
- Stima dei token = (somma dei caratteri) `// 4`, senza nuove dipendenze.
- Testi esatti (in `assistant/summarizer.py`):
  - `SUMMARIZER_INSTRUCTIONS = "Riassumi la conversazione tra l'utente e l'assistente del laboratorio, in italiano, in al massimo 120 parole. Conserva sempre, se presenti: il nome dell'utente, il fuso orario o la città che usa, gli ID delle note con il loro testo, gli argomenti principali di cui si è parlato. Se la conversazione inizia con un riassunto delle parti precedenti, riporta TUTTE le sue informazioni (nomi, note, argomenti) e aggiungi quelle nuove. Scrivi solo il riassunto, senza introduzioni."`
  - richiesta: `"Conversazione da riassumere:\n"` + (se c'è un riassunto in vigore) `"Riassunto delle parti precedenti: {riassunto}\n"` + trascrizione
  - prompt esteso: `"{prompt di sistema}\n\nRiassunto della conversazione precedente:\n{riassunto}"`
  - riga del terminale: `"[riassunto] {n_prima} → {n_dopo} messaggi (circa {t_prima} → {t_dopo} token)"`
  - log (logger `assistant.graph`): DEBUG con la stessa riga; WARNING `[riassunto] non riuscito ({motivo}): cronologia invariata`, dove il motivo è l'errore oppure `testo vuoto`; INFO all'avvio (logger `assistant`) `[riassunto] soglia: {n} token stimati, turni conservati: {k}`
- Non leggere né modificare `lezione-03/`.

## Review Focus

1. **Chiamata e risultato mai separati**: un turno con `AIMessage` con `tool_calls` + `ToolMessage` subito prima del confine → tutti e due compressi o tutti e due conservati. Test nel Task 2.
2. **Indicazioni del revisore non sono turni**: un `HumanMessage` marcato `review_feedback` non conta come inizio di turno. Test nel Task 2.
3. **Riassunto non riuscito**: `openai.APIError` o testo vuoto → nessuna rimozione, `summary` invariato, WARNING, il turno arriva comunque alla risposta. Test nel Task 3.
4. **Il riassunto non entra nella cronologia salvata**: dopo il turno il primo messaggio di sistema è identico a prima; il riassunto vive solo in `summary`. Test nel Task 3.
5. **Turno fallito o risposta vuota**: `cli.run` non aggiorna né cronologia né riassunto. Test nel Task 4.

---

### Task 1: Variabili SUMMARY_THRESHOLD e SUMMARY_KEEP_TURNS

**Files:** Modify `assistant/config.py`, `.env.example`; Test `tests/test_config.py`.

**Interfaces:** Produces `Settings.summary_threshold: int = 4000` e `Settings.summary_keep_turns: int = 2` (campi con default in fondo), letti con `_number(env, "SUMMARY_THRESHOLD", "4000", int, 1, "un intero")` e `_number(env, "SUMMARY_KEEP_TURNS", "2", int, 1, "un intero")`.

- [ ] **Step 1: Write the failing tests**: assenti → 4000 e 2; `"1500"` → 1500; `"3"` → 3; `"0"`, `"-1"` e `"abc"` → `ConfigError` con il nome della variabile nel messaggio (per ciascuna delle due).
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement**; `.env.example`: commenti in italiano + `SUMMARY_THRESHOLD=4000` («token stimati oltre i quali la cronologia viene riassunta (intero >= 1)») e `SUMMARY_KEEP_TURNS=2` («turni recenti tenuti interi nel riassunto (intero >= 1)»), dopo `MAX_REVIEWS`.
- [ ] **Step 4: Run tests** — suite verde.
- [ ] **Step 5: Commit** — `feat(config): aggiunge SUMMARY_THRESHOLD e SUMMARY_KEEP_TURNS`.

### Task 2: Modulo del riassunto

**Files:** Create `assistant/summarizer.py`; Test `tests/test_summarizer.py`.

**Interfaces:**
- Consumes: `is_review_feedback(message) -> bool` da `assistant/reviewer.py`.
- Produces in `assistant/summarizer.py`:
  - `SUMMARIZER_INSTRUCTIONS`, `SUMMARY_HEADER = "Riassunto della conversazione precedente:"` (testi nelle Global Constraints).
  - `estimate_tokens(messages: list[AnyMessage], summary: str = "") -> int`: caratteri del `content` se stringa (altrimenti 0), più per ogni `tool_calls` di un `AIMessage` `len(name) + len(json.dumps(args, ensure_ascii=False))`, più `len(summary)`; il totale `// 4`.
  - `turn_starts(messages) -> list[int]`: indici degli `HumanMessage` non marcati come indicazione del revisore.
  - `summary_cut(messages, keep_turns: int) -> int`: indice del primo messaggio conservato dopo il prompt di sistema; `0` se non c'è niente da comprimere. Con `starts = turn_starts(messages)`: l'ultimo è la domanda corrente; se i turni precedenti (`len(starts) - 1`) sono ≤ `keep_turns` → `0`; altrimenti `starts[-1 - keep_turns]`. I messaggi da comprimere sono `messages[first:cut]`, con `first = 1` se `messages[0]` è un `SystemMessage`, altrimenti `0`.
  - `transcript(messages) -> str`: una riga per messaggio, unite da `"\n"`: `Utente: {testo}`; `Assistente: {testo}` solo se il testo non è vuoto; `Strumento {name}: {contenuto}` per i `ToolMessage`; altri tipi saltati.
  - `summary_request(previous: str, conversation: str) -> str` (formato nelle Global Constraints).
  - `build_summarizer(model: BaseChatModel) -> Callable[[str, str], str]`: `(riassunto_in_vigore, trascrizione) -> testo`; `model.model_copy(update={"reasoning_effort": "none"})`, invocato con `[SystemMessage(SUMMARIZER_INSTRUCTIONS), HumanMessage(summary_request(previous, conversation))]`, restituisce `.content`.
  - `with_summary(messages, summary: str) -> list[AnyMessage]`: se `summary` è vuoto restituisce `messages`; altrimenti una nuova lista con il primo `SystemMessage` sostituito da una copia (`model_copy`) con contenuto esteso; la lista originale non cambia.
  - `summary_line(messages_before: int, messages_after: int, tokens_before: int, tokens_after: int) -> str`.

- [ ] **Step 1: Write the failing tests** in `tests/test_summarizer.py`:
  - `test_estimate_tokens`: `[SystemMessage("a"*40), HumanMessage("b"*40)]` → 20; con `summary="c"*40` → 30; un `AIMessage("", tool_calls=[{"name": "calc", "args": {"x": 1}, "id": "1"}])` conta `len("calc") + len('{"x": 1}')`.
  - `test_cut_keeps_last_turns`: sistema + 4 turni completi + domanda corrente, `keep_turns=2` → il taglio cade sull'indice della domanda del 3° turno.
  - `test_cut_nothing_to_compress`: sistema + 2 turni + domanda, `keep_turns=2` → `0`; solo sistema + domanda → `0`.
  - `test_cut_never_splits_tool_call`: turno con `AIMessage` con `tool_calls`, `ToolMessage`, risposta, subito prima del primo turno conservato → chiamata e `ToolMessage` stanno entrambi in `messages[1:cut]`.
  - `test_review_feedback_is_not_a_turn`: un `HumanMessage(..., additional_kwargs={"review_feedback": True})` non compare in `turn_starts`.
  - `test_transcript_lines`: `Utente: ciao, mi chiamo Marco`, `Strumento add_note: Nota 7 salvata`, `Assistente: Ho salvato la nota 7.`; un `AIMessage` vuoto con sole chiamate non produce righe.
  - `test_summary_request_with_and_without_previous`: senza → inizia con `"Conversazione da riassumere:\n"` seguito dalla trascrizione; con → contiene `"Riassunto delle parti precedenti: R\n"` prima della trascrizione.
  - `test_with_summary_extends_system_only_for_call`: il primo messaggio restituito ha `"PROMPT\n\nRiassunto della conversazione precedente:\nR"`; la lista e il messaggio originali sono invariati; con `summary=""` stessa lista.
  - `test_build_summarizer_uses_no_reasoning`: con un modello finto che registra i messaggi e il `model_copy` → riceve `reasoning_effort="none"`, sistema = `SUMMARIZER_INSTRUCTIONS`, restituisce il testo.
  - `test_summary_line`: `summary_line(24, 5, 5200, 1400) == "[riassunto] 24 → 5 messaggi (circa 5200 → 1400 token)"`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests** — suite verde.
- [ ] **Step 5: Commit** — `feat(riassunto): modulo del riassunto della cronologia`.

### Task 3: Nodo del riassunto nel grafo e nello streaming

**Files:** Modify `assistant/graph.py`, `assistant/stream_view.py`; Test `tests/test_graph.py`, `tests/test_stream_view.py`.

**Interfaces:**
- Consumes: tutto il Task 2.
- Produces: `build_graph(model, tools, max_steps, answer_check=None, router=None, reviewer=None, max_reviews=3, summarizer: Callable[[str, str], str] | None = None, summary_threshold: int = 4000, summary_keep_turns: int = 2)`. Campi di stato `NotRequired`: `summary: str`, `summary_line: str`.

**Comportamento (deciso qui):**
- Con `summarizer`: `START → "summarizer" → "router"` (o `"model"` senza router). Senza: grafo identico a oggi.
- Nodo `summarizer`: `summary = state.get("summary", "")`; `before = estimate_tokens(messages, summary)`; se `before <= summary_threshold` → `{}` (nessuna chiamata). `cut = summary_cut(messages, summary_keep_turns)`; se `0` → `{}`. Chiama `summarizer(summary, transcript(messages[first:cut]))`; `openai.APIError` → WARNING, `{}`; testo vuoto dopo `strip()` → WARNING `testo vuoto`, `{}`. Altrimenti restituisce `RemoveMessage` per `messages[first:cut]`, `summary` = nuovo testo, `summary_line` = `summary_line(len(messages), len(messages) - (cut - first), before, estimate_tokens(conservati, nuovo))`, e il log DEBUG.
- `model_node` invoca il modello con `with_summary(state["messages"], state.get("summary", ""))`; i messaggi restituiti nello stato non cambiano.
- `stream_turn`: aggiornamento del nodo `summarizer` non vuoto con `summary_line` → `view.extra(summary_line)` e poi `view.extra(summary)`. I pezzi in modalità `messages` del nodo `summarizer` sono già ignorati (filtro su `langgraph_node == "model"`).

- [ ] **Step 1: Write the failing tests** (funzione di riassunto simulata che registra `(previous, conversation)` e restituisce un testo fisso; `summary_threshold` basso per superarlo):
  - `test_summarizer_below_threshold_not_called`: soglia alta → mai chiamata, messaggi finali come senza riassunto.
  - `test_summarizer_compresses_old_turns`: sistema + 3 turni + domanda, `keep_turns=2`, soglia 1 → chiamata una volta con la trascrizione del 1° turno; messaggi finali = sistema + turni 2 e 3 + domanda + risposta; `summary` nel risultato = testo simulato.
  - `test_summarizer_replaces_previous_summary`: stato iniziale con `summary="VECCHIO"` → la funzione riceve `"VECCHIO"`; risultato `summary == "NUOVO"`, nessun accodamento.
  - `test_summarizer_failure_keeps_history`: funzione che solleva `openai.APIConnectionError(request=httpx.Request("POST", "http://x"))`, e poi una che restituisce `"  "` → messaggi e `summary` invariati, WARNING con `cronologia invariata`, il turno arriva alla risposta del modello.
  - `test_model_receives_summary_in_system_prompt`: con `summary="R"` → il modello finto riceve come primo messaggio il prompt esteso; il primo messaggio dello stato finale è il prompt originale.
  - `test_summarizer_runs_once_with_reviewer_retry`: revisore no/sì → riassunto chiamato una sola volta nel turno.
  - `test_summarizer_runs_before_router`: con router simulato → l'ordine delle chiamate è riassunto, router.
  - `tests/test_stream_view.py::test_stream_turn_summary_lines`: grafo vero sopra la soglia → nell'uscita, in ordine e una volta: `[riassunto] … messaggi (circa … token)`, il testo del riassunto, la risposta.
  - Grafo senza `summarizer`: test esistenti invariati.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests** — suite verde.
- [ ] **Step 5: Commit** — `feat(grafo): nodo del riassunto della cronologia all'inizio del turno`.

### Task 4: Terminale, collegamento e documentazione

**Files:** Modify `assistant/cli.py`, `assistant/__main__.py`, `README.md`, `CLAUDE.md`; Test `tests/test_cli.py`.

**Interfaces:** Consumes il Task 3 (`summary` nello stato) e il Task 1 (`Settings`).

- [ ] **Step 1: Write the failing tests** in `tests/test_cli.py` (con `FakeStreamGraph` di `tests/fakes.py` o un grafo vero):
  - `test_summary_carried_to_next_turn`: il primo turno restituisce `summary="R"` → il secondo turno riceve nello stato `summary == "R"`; il primo turno riceve `summary == ""`.
  - `test_clear_resets_summary`: dopo `clear` il turno successivo riceve `summary == ""`.
  - `test_failed_turn_keeps_summary`: un turno con errore (`openai.APIError`) o risposta vuota non cambia il riassunto passato al turno successivo.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement**: `cli.run` tiene `summary` accanto a `history`, lo passa in `stream_turn(..., {"messages": ..., "steps": 0, "summary": summary}, ...)`, a turno riuscito `summary = result.get("summary", "")`, con `clear` lo azzera. `__main__`: `build_graph(..., summarizer=build_summarizer(model), summary_threshold=settings.summary_threshold, summary_keep_turns=settings.summary_keep_turns)` e log INFO di avvio (Global Constraints).
- [ ] **Step 4: Docs**: README — righe di configurazione `SUMMARY_THRESHOLD` e `SUMMARY_KEEP_TURNS`; sezione sul riassunto (quando scatta, che cosa conserva, dove finisce il riassunto, riga e testo nel terminale, `clear`, costo ~10 s, **limite accettato**: gli argomenti più vecchi si perdono ai riassunti successivi); riga in Diagnosi (riassunto lento o troppo frequente → alzare `SUMMARY_THRESHOLD`; WARNING `non riuscito` → cronologia invariata, il turno prosegue); tabella «Prova reale del riassunto» con le righe della specifica (sezione 6) a `da provare`. `CLAUDE.md`: `summarizer.py` nella struttura, nodo riassunto in `graph.py`.
- [ ] **Step 5: Run tests** — suite verde; avvio `echo quit | .venv/Scripts/python.exe -m assistant` → codice 0 e riga `[riassunto] soglia: 4000 token stimati, turni conservati: 2`.
- [ ] **Step 6: Commit** — `feat(riassunto): attiva il riassunto all'avvio e lo porta da un turno all'altro`.

### Dopo i task (controller)

- Revisione finale del branch.
- Prova reale via pipe (locale e Docker `-T`) con `SUMMARY_THRESHOLD=1500`: nome al primo turno, domande con strumenti e una nota, riga e testo del riassunto, «come mi chiamo?» dopo la compressione, secondo riassunto (che cosa resta), tempi; sotto la soglia nessuna riga. Esiti nel README; poi ok dell'utente per il merge.
