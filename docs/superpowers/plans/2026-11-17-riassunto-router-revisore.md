# Router e revisore con il riassunto — piano

Specifica: `docs/superpowers/specs/2026-11-16-riassunto-design.md`, sezioni 5.7 e 5.8 (revisioni del 2026-11-17; Task 2b e 2c aggiunti dopo la prova reale). Branch: `feature/riassunto` (lo stesso dello step 3). Esecuzione: in linea, a pezzi piccoli, TDD; suite verde e commit dopo ogni task.

## Global Constraints

- Intestazione del riassunto: «Riassunto della conversazione precedente:», la stessa dell'agente. Il router riusa `SUMMARY_HEADER` di `assistant/summarizer.py`; per il revisore vedi Task 2.
- Conversazione recente del revisore: `transcript(router_context(messages[:indice_domanda]))`, con `router_context` di `assistant/router.py` e `transcript` di `assistant/summarizer.py`. La calcola il grafo (`assistant/reviewer.py` non importa `summarizer`, che importa già `reviewer`: niente import circolari).
- Istruzioni del revisore (`REVIEWER_INSTRUCTIONS`) e del router (`ROUTER_INSTRUCTIONS`) invariate.
- Senza riassunto e senza conversazione recente i messaggi inviati sono identici a oggi.

## Review Focus

1. Il riassunto non entra mai nella cronologia salvata (solo nelle chiamate).
2. La conversazione recente del revisore non contiene la domanda del turno, le bozze, le indicazioni del revisore né il traffico degli strumenti.

---

### Task 1: Router con il riassunto

**Files:** Modify `assistant/router.py`, `assistant/graph.py`; Test `tests/test_router.py`, `tests/test_graph.py`, `tests/test_stream_view.py` (firma dei router finti).

**Interfaces:** `router_prompt(scope: str, summary: str = "") -> str` aggiunge `\n\n{SUMMARY_HEADER}\n{summary}` se il riassunto non è vuoto. La funzione restituita da `build_router` diventa `route(messages, summary: str = "")`. In `build_graph` il tipo diventa `Callable[[list[AnyMessage], str], Route]` e il nodo chiama `router(state["messages"], state.get("summary", ""))`.

- [ ] **Step 1: Test che falliscono**: `router_prompt` con e senza riassunto; `build_router` con riassunto → primo messaggio di sistema esteso; il grafo con `summary` nello stato passa il riassunto al router (router finto che registra gli argomenti).
- [ ] **Step 2: Verificare che falliscano.**
- [ ] **Step 3: Implementare**; aggiornare i router finti dei test esistenti alla nuova firma.
- [ ] **Step 4: Suite verde.**
- [ ] **Step 5: Commit** — `feat(router): il router riceve il riassunto della conversazione`.

### Task 2: Revisore con riassunto e conversazione recente

**Files:** Modify `assistant/reviewer.py`, `assistant/graph.py`; Test `tests/test_reviewer.py`, `tests/test_graph.py`, `tests/test_stream_view.py`.

**Interfaces:** `review_request(question, answer, summary: str = "", recent: str = "") -> str` antepone, solo se non vuoti, `{SUMMARY_HEADER}\n{summary}\n\n` e `Conversazione recente:\n{recent}\n\n` (`reviewer.py` non può importare `summarizer`: definisce una propria costante con lo stesso testo e un test verifica che coincida con `SUMMARY_HEADER`). La funzione di `build_reviewer` diventa `review(question, answer, summary="", recent="")`. Nel grafo: `reviewer(question, answer, state.get("summary", ""), transcript(router_context(messages[:qi])))`.

- [ ] **Step 1: Test che falliscono**: `review_request` nei quattro casi (nessun contesto = testo di oggi; solo riassunto; solo recente; entrambi, nell'ordine riassunto → recente → domanda → risposta); `build_reviewer` inoltra riassunto e recente; il grafo passa al revisore riassunto e conversazione recente (turno precedente con uno strumento: nella recente solo `Utente:`/`Assistente:` di testo; dopo un rifiuto del revisore, al secondo giudizio la recente non contiene bozze né indicazioni).
- [ ] **Step 2: Verificare che falliscano.**
- [ ] **Step 3: Implementare**; aggiornare i revisori finti alla nuova firma.
- [ ] **Step 4: Suite verde.**
- [ ] **Step 5: Commit** — `feat(revisore): il revisore riceve riassunto e conversazione recente`.

### Task 2b: Risultati degli strumenti al revisore (specifica 5.8)

**Files:** Modify `assistant/reviewer.py`, `assistant/graph.py`; Test `tests/test_reviewer.py`, `tests/test_graph.py`, `tests/test_stream_view.py`.

**Interfaces:** `review_request(question, answer, summary="", recent="", tools="")`: se `tools` non è vuoto, dopo la conversazione recente aggiunge `Risultati degli strumenti in questo turno:\n{tools}\n\n`. La funzione di `build_reviewer` e il tipo in `build_graph` prendono il quinto argomento. Nel grafo `tools = "\n".join(f"{m.name}: {m.content}" for m in messages[index + 1:] if isinstance(m, ToolMessage))`.

- [ ] **Step 1: Test che falliscono**: `review_request` con i risultati (ordine riassunto → recente → strumenti → domanda → risposta; senza: identica a prima); il grafo passa al revisore i risultati del turno corrente e non quelli di un turno precedente nella cronologia.
- [ ] **Step 2: Verificare che falliscano.**
- [ ] **Step 3: Implementare**; aggiornare i revisori finti alla nuova firma.
- [ ] **Step 4: Suite verde.**
- [ ] **Step 5: Commit** — `fix(revisore): il revisore vede i risultati degli strumenti del turno`.

### Task 2c: «L'utente» nel riassunto (specifica 5.8)

**Files:** Modify `assistant/summarizer.py`; Test `tests/test_summarizer.py`.

- [ ] **Step 1: Test che fallisce**: `SUMMARIZER_INSTRUCTIONS` contiene «Riferisciti all'utente sempre come «l'utente»» prima di «Scrivi solo il riassunto».
- [ ] **Step 2: Verificare che fallisca.**
- [ ] **Step 3: Implementare.**
- [ ] **Step 4: Suite verde.**
- [ ] **Step 5: Commit** — `fix(riassunto): il riassunto chiama l'utente «l'utente» con nome e città`.

### Task 3: Documentazione e prova reale

- [ ] README (sezione del riassunto: che cosa ricevono router e revisore; limite «dove vivo?»), `CLAUDE.md` se cambia la descrizione dei moduli; commit `docs: ...`.
- [ ] Prova reale con soglia 900 (stesse domande del 2026-11-16), tempi; Docker via pipe; tabella «Prova reale del riassunto» nel README; commit `docs: ...`.
- [ ] Ok dell'utente per merge `--no-ff` in `developer`, push, eliminazione del branch.
