# Router e revisore con il riassunto — piano

Specifica: `docs/superpowers/specs/2026-11-16-riassunto-design.md`, sezione 5.7 (revisione del 2026-11-17). Branch: `feature/riassunto` (lo stesso dello step 3). Esecuzione: in linea, a pezzi piccoli, TDD; suite verde e commit dopo ogni task.

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

### Task 3: Documentazione e prova reale

- [ ] README (sezione del riassunto: che cosa ricevono router e revisore; limite «dove vivo?»), `CLAUDE.md` se cambia la descrizione dei moduli; commit `docs: ...`.
- [ ] Prova reale con soglia 900 (stesse domande del 2026-11-16), tempi; Docker via pipe; tabella «Prova reale del riassunto» nel README; commit `docs: ...`.
- [ ] Ok dell'utente per merge `--no-ff` in `developer`, push, eliminazione del branch.
