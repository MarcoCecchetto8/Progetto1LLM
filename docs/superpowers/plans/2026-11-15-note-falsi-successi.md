# Controllo dei falsi successi delle note — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** quando il modello dichiara di aver salvato o eliminato una nota senza la conferma dello strumento nello stesso turno, il programma aggiunge un avviso in fondo alla risposta (solo avviso, nessun nuovo tentativo).

**Architecture:** `build_graph` riceve un parametro facoltativo `answer_check`; se presente, la risposta finale del modello (senza chiamate) passa da un nodo `answer_check` che aggiunge gli avvisi al testo dello stesso messaggio (sostituito per `id`). La funzione che riconosce i falsi successi delle note, `check_note_claims`, sta in `assistant/notes.py` e viene passata da `assistant/__main__.py`. In più si corregge il prompt delle note come da specifica 5.2.

**Tech Stack:** Python 3.14, LangGraph, langchain-core (nessuna nuova dipendenza); `re` e `unicodedata` della libreria standard.

**Spec:** `docs/superpowers/specs/2026-11-09-note-fastapi-design.md` (sezioni 3, 5.2, 5.4, 8, revisioni 2026-11-11 e 2026-11-15)

## Global Constraints

- Branch `feature/note-fastapi` (già esistente); nessun push, nessun merge senza l'ok dell'utente.
- Pezzi piccoli, un commit per task; prima di ogni commit `git status`, diff, staging selettivo; controllare l'**exit code** di pytest (`python -m pytest`, dalla radice con il venv).
- Nomi nel codice in inglese; testi per l'utente, log e commit in italiano (Conventional Commits).
- Solo avviso: il controllo **non** chiama di nuovo il modello, **non** cambia `steps`, **non** aggiunge messaggi: modifica solo il testo dell'ultima risposta.
- Testi esatti degli avvisi:
  - `SAVE_WARNING = "⚠ Attenzione: nessuna nota è stata salvata (lo strumento non l'ha confermato)."`
  - `DELETE_WARNING = "⚠ Attenzione: nessuna nota è stata eliminata (lo strumento non l'ha confermato)."`
- Formato della risposta con avvisi: `testo originale + "\n\n" + "\n".join(avvisi)`; ordine: salvataggio, poi eliminazione.
- Log `INFO` nel logger `assistant.graph`: `[controllo] falso successo: avviso all'utente → <avvisi uniti da " | ">`.
- Non leggere né modificare `lezione-03/`.

## Review Focus

1. **«Non hai note salvate» dopo `list_notes`** (risposta frequente a «Che note ho?»): non è una dichiarazione di salvataggio, nessun avviso. Test nel Task 2.
2. **Eliminazione annullata dall'utente** («Eliminazione annullata», «non ho eliminato nulla» dopo un `delete_note` annullato): `delete_note` senza errore vale come conferma, nessun avviso. Test nel Task 2.
3. **Turno con più domande in cronologia**: un `add_note` riuscito in un turno precedente non conferma il turno attuale. Test nel Task 2.
4. **Risposta del modello con contenuto non stringa** (lista di blocchi): il nodo non deve rompersi; se il contenuto non è una stringa il controllo lo salta. Test nel Task 1.
5. **Messaggio di limite di passaggi**: non passa dal controllo, nessun avviso. Test nel Task 1.

---

### Task 1: Controllo facoltativo della risposta nel grafo

**Files:**
- Modify: `assistant/graph.py` (funzione `build_graph`)
- Test: `tests/test_graph.py`

**Interfaces:**
- Produces: `build_graph(model: BaseChatModel, tools: list[BaseTool], max_steps: int, answer_check: Callable[[list[AnyMessage]], list[str]] | None = None)`. `answer_check` riceve **tutti** i messaggi dello stato (ultima = risposta del modello senza chiamate) e restituisce la lista degli avvisi (vuota = nessun problema).

- [ ] **Step 1: Write the failing tests** in `tests/test_graph.py` (usano `fake`, `tool_call`, `clock`, `start` già presenti):
  - `test_answer_check_appends_warnings`: `check = lambda msgs: ["⚠ A", "⚠ B"]`; `build_graph(fake(AIMessage("Fatto.")), [clock], 5, answer_check=check).invoke(start("x"))` → ultimo messaggio `content == "Fatto.\n\n⚠ A\n⚠ B"`, è un `AIMessage`, `out["steps"] == 1`, numero di messaggi = 3 (System, Human, AI: il messaggio è sostituito, non aggiunto).
  - `test_answer_check_without_warnings_leaves_answer`: `check` restituisce `[]` → `content == "Fatto."`.
  - `test_answer_check_receives_turn_messages`: `check` registra i messaggi ricevuti; dopo `fake(tool_call({}, "a"), AIMessage("Sono le 14:32"))` riceve una lista che contiene il `ToolMessage` di `get_current_time` e termina con l'`AIMessage("Sono le 14:32")`.
  - `test_answer_check_skipped_on_step_limit`: modello con 10 `tool_call`, `check` che restituisce sempre `["⚠"]` e conta le chiamate → ultimo messaggio `== LIMIT_MESSAGE`, `check` mai chiamato.
  - `test_answer_check_skips_non_string_content`: `AIMessage(content=[{"type": "text", "text": "Fatto."}])` con `check` che restituisce `["⚠"]` → contenuto invariato (lista uguale), nessuna eccezione.
  - `test_answer_check_logged(caplog)`: con `check` → `["⚠ A", "⚠ B"]` e `caplog.at_level(logging.INFO, logger="assistant.graph")`, nel log c'è `[controllo] falso successo: avviso all'utente → ⚠ A | ⚠ B`.
  - I test esistenti senza `answer_check` restano invariati (comportamento identico).

- [ ] **Step 2: Run tests to verify they fail**
  Run: `python -m pytest tests/test_graph.py -q`
  Expected: i nuovi test falliscono (`TypeError: build_graph() got an unexpected keyword argument 'answer_check'`), gli altri passano.

- [ ] **Step 3: Implement** in `assistant/graph.py`:
  - parametro `answer_check` come da Interfaces;
  - in `route_after_model`, quando l'ultimo messaggio non ha chiamate: `"answer_check"` se `answer_check` è presente, altrimenti `END` (log di debug invariato nello stile);
  - nodo `answer_check_node(state)`: ultimo messaggio; se `content` non è `str` → `{}`; `warnings = answer_check(state["messages"])`; se vuota → `{}`; altrimenti log `INFO` (testo nei Global Constraints) e `{"messages": [AIMessage(content=..., id=last.id)]}` (stesso `id`: `add_messages` lo sostituisce);
  - il nodo e il suo arco verso `END` si aggiungono **solo** se `answer_check` è presente; `add_conditional_edges` elenca `"answer_check"` fra le destinazioni solo in quel caso.

- [ ] **Step 4: Run tests to verify they pass**
  Run: `python -m pytest -q` → tutti verdi (exit code 0).

- [ ] **Step 5: Commit**
  ```bash
  git add assistant/graph.py tests/test_graph.py
  git commit -m "feat(grafo): aggiunge un controllo facoltativo della risposta finale"
  ```

### Task 2: Riconoscimento dei falsi successi delle note

**Files:**
- Modify: `assistant/notes.py`
- Test: `tests/test_notes_tools.py`

**Interfaces:**
- Consumes: la forma di `answer_check` del Task 1 (`list[AnyMessage] -> list[str]`).
- Produces: `SAVE_WARNING`, `DELETE_WARNING` (testi nei Global Constraints) e `check_note_claims(messages: list[AnyMessage]) -> list[str]` in `assistant/notes.py`.

**Regole (dalla specifica 5.4, decise qui):**
- *Turno* = messaggi dopo l'ultimo `HumanMessage`; *risposta* = ultimo messaggio. Se la risposta non è una stringa → `[]`.
- Normalizzazione per il confronto: minuscolo e senza accenti (`unicodedata.normalize("NFD", …)` togliendo i caratteri combinanti; così «è» → «e»).
- **Dichiarazione** = forma verbale che afferma un'azione compiuta (non un aggettivo, così «Non hai note salvate» e «Nessuna nota salvata» non scattano):
  - salvataggio: `\bho\s+(?:gia\s+)?(salvato|memorizzato|annotato|registrato|aggiunto)\b` oppure `\b(?:e'?|sono)\s+stat[aoie]\s+(salvat|memorizzat|annotat|registrat|aggiunt)[aoie]\b` (l'apostrofo copre «e' stata» scritto senza accento);
  - eliminazione: le stesse due forme con `eliminato|cancellato|rimosso` e `eliminat|cancellat|rimoss`.
  - Le negative («non ho salvato», «non è stata eliminata») scattano anche loro: l'avviso è coerente con ciò che dicono (nel dubbio un avviso in più, come da specifica).
- **Conferma** nel turno: un `ToolMessage` con `name == "add_note"` (per il salvataggio) o `name == "delete_note"` (per l'eliminazione) e `status != "error"`. `delete_note` annullata dall'utente è senza errore, quindi conferma.
- Risultato: `[SAVE_WARNING]` se dichiara salvataggio senza conferma, `[DELETE_WARNING]` per l'eliminazione, entrambi in quest'ordine, oppure `[]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_notes_tools.py`, con un aiuto locale `turn(answer, *tools, history=())` che costruisce `[SystemMessage("s"), *history, HumanMessage("q"), *tools, AIMessage(answer)]` e `ToolMessage(content, tool_call_id="t", name=..., status=...)`:
  - `test_claim_without_add_note_warns` — parametrizzato sulle frasi reali della prova: `Ho salvato la nota: "comprare il latte".`, `Ho salvato un promemoria per te: "consegnare il report" venerdì.`, `Ho salvato il promemoria: "comprare il latte".` → `[SAVE_WARNING]`.
  - `test_claim_passive_and_accents_warn`: `La nota è stata salvata.` e `La nota e' stata memorizzata` → `[SAVE_WARNING]`.
  - `test_add_note_success_confirms`: `ToolMessage("Nota 1 salvata: …", name="add_note")` + `Ho salvato la nota.` → `[]`.
  - `test_add_note_error_does_not_confirm`: stesso `ToolMessage` con `status="error"` → `[SAVE_WARNING]`.
  - `test_previous_turn_does_not_confirm`: `add_note` riuscito in `history` (prima di un `HumanMessage` precedente), turno attuale senza strumenti, `Ho salvato la nota.` → `[SAVE_WARNING]`.
  - `test_other_tool_does_not_confirm`: `ToolMessage("2026-11-13", name="add_days")` + `Ho salvato un promemoria…` → `[SAVE_WARNING]` (caso «venerdì» della prova).
  - `test_delete_claim_without_tool_warns`: `Ho eliminato la nota 3.` e `La nota 3 è stata cancellata.` → `[DELETE_WARNING]`.
  - `test_delete_cancelled_confirms`: `ToolMessage("Eliminazione della nota 3 annullata dall'utente.", name="delete_note")` + `Va bene, non ho eliminato nulla.` → `[]`.
  - `test_both_claims_warn_in_order`: `Ho salvato la nuova nota e ho eliminato la vecchia.` senza strumenti → `[SAVE_WARNING, DELETE_WARNING]`.
  - `test_no_claim_no_warning` — parametrizzato: `Non hai note salvate.`, `Nessuna nota salvata.`, `Non è stata trovata alcuna nota con l'ID 99 da eliminare.`, `Dovrai prima confermare l'eliminazione della nota con ID 99.`, `Sono le 14:32.`, `Ti ricordo di consegnare il report venerdì.` → `[]`.
  - `test_non_string_answer_ignored`: `AIMessage(content=[{"type": "text", "text": "Ho salvato la nota."}])` → `[]`.
  - `test_graph_appends_save_warning`: grafo vero con `fake(AIMessage("Ho salvato la nota."))`, i tool delle note sul `client` di prova già usato nel file e `answer_check=check_note_claims` → ultimo messaggio `== "Ho salvato la nota.\n\n" + SAVE_WARNING`; con `fake(tool_call({"text": "latte"}, "a", name="add_note"), AIMessage("Ho salvato la nota."))` → nessun avviso e nota presente nel servizio.

- [ ] **Step 2: Run tests to verify they fail**
  Run: `python -m pytest tests/test_notes_tools.py -q`
  Expected: `ImportError` su `check_note_claims`.

- [ ] **Step 3: Implement** `SAVE_WARNING`, `DELETE_WARNING`, `check_note_claims` in `assistant/notes.py` secondo le Regole (espressioni compilate a livello di modulo; un breve commento che dice perché solo forme verbali).

- [ ] **Step 4: Run tests to verify they pass**
  Run: `python -m pytest -q` → tutti verdi (exit code 0).

- [ ] **Step 5: Commit**
  ```bash
  git add assistant/notes.py tests/test_notes_tools.py
  git commit -m "feat(note): riconosce i falsi successi e prepara gli avvisi"
  ```

### Task 3: Collegamento, prompt e documentazione

**Files:**
- Modify: `assistant/__main__.py`, `assistant/graph.py` (solo `system_prompt`), `tests/test_graph.py`, `README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `build_graph(..., answer_check=...)` (Task 1), `check_note_claims` (Task 2).

- [ ] **Step 1: Write the failing test** in `tests/test_graph.py`:
  - `test_system_prompt_notes_weekday_rule`: il prompt contiene `add_days`, `«venerdì»`, `non chiedergli la data` e `«Nota N salvata»`; **non** contiene `non chiedere tu conferma`.
  - `test_system_prompt_mentions_notes_tools` resta invariato (`ID esatto`, `chiederà conferma` presenti).

- [ ] **Step 2: Run to verify it fails**
  Run: `python -m pytest tests/test_graph.py -q` → fallisce su `non chiedere tu conferma` (la modifica non committata nel working tree contiene ancora quella frase).

- [ ] **Step 3: Implement**
  - `system_prompt`: il working tree contiene già la frase delle note rivista (non committata). Testo finale esatto della parte sulle note:
    `"Per salvare una nota DEVI chiamare `add_note`, una sola volta per richiesta: la nota esiste solo se lo strumento risponde «Nota N salvata», quindi non scrivere mai di averla salvata senza quella risposta. La scadenza va nel formato AAAA-MM-GG; se l'utente indica un giorno della settimana (es. «venerdì») o «domani», non chiedergli la data: ricavala tu con `get_current_time` e `add_days`, poi chiama `add_note`. Per vedere le note usa `list_notes`. Per eliminare una nota usa `delete_note` con l'ID esatto preso da `list_notes`; se non è chiaro quale nota intende l'utente, chiediglielo; prima di eliminare il programma chiederà conferma all'utente. Non dire mai che una nota è stata eliminata se lo strumento non lo conferma. "`
    (cioè: salvataggio come nel working tree; eliminazione tornata alla formulazione originale, senza «chiama subito» e senza «non chiedere tu conferma»).
  - `assistant/__main__.py`: importare `check_note_claims` e passarlo: `build_graph(build_chat_model(settings), tools, settings.max_steps, answer_check=check_note_claims)`.
  - `README.md`, sezione delle note: un paragrafo breve sull'avviso (quando compare, testo, che resta in cronologia, che è un controllo del programma per un limite del modello). Niente risultati della prova reale: li aggiunge il controller dopo la misura.
  - `CLAUDE.md`: nella descrizione di `notes.py` aggiungere «controllo dei falsi successi (avviso)»; in quella di `graph.py` «controllo facoltativo della risposta».

- [ ] **Step 4: Run tests**
  Run: `python -m pytest -q` → tutti verdi (exit code 0). Poi avvio di prova: `"quit" | python -m assistant` (con LM Studio acceso) esce con codice 0 senza traceback.

- [ ] **Step 5: Commit**
  ```bash
  git add assistant/__main__.py assistant/graph.py tests/test_graph.py README.md CLAUDE.md
  git commit -m "feat(note): mostra l'avviso sui falsi successi e corregge il prompt"
  ```

### Dopo i task (controller, non subagent)

- Rimisurare con la sonda end-to-end (passando `answer_check=check_note_claims`), 5 conversazioni per «Ricordami di comprare il latte», «Ricordami di consegnare il report venerdì», «Elimina la nota 99»; contare salvataggi riusciti, avvisi mostrati e falsi successi arrivati all'utente **senza** avviso (atteso: zero).
- Riportare all'utente il confronto prima/dopo; poi riprendere la prova reale delle note (n/s, «elimina le note 1 e 2», riavvio, Docker) e scrivere gli esiti nel README.
