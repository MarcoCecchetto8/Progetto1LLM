# Bozza visibile e numeri delle note — piano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** risposta in streaming nel browser come bozza «in revisione», note numerate dal più piccolo ID libero ed elencate per ID, indicazione `list_notes` quando si chiede l'elenco.

**Architecture:** tre modifiche indipendenti: `notes_service/store.py` (+ nuovo `notes_service/compact.py`), `assistant/graph.py` (`tool_hints`), `frontend_service/static/app.js` + `style.css`. Nessun cambio di API.

**Tech Stack:** Python 3, SQLite (`sqlite3`), pytest; JavaScript senza framework.

**Spec:** `docs/superpowers/specs/2026-11-09-note-fastapi-design.md` sez. 5.8; `docs/superpowers/specs/2026-11-25-frontend-chat-design.md` sez. 5, revisione 2026-11-26.

## Global Constraints

- Branch `feature/frontend` (contiene già il riscaldamento). Conventional Commits in italiano, staging selettivo.
- Testi per l'utente in italiano. Nessuna nuova dipendenza.
- Test senza modello; la suite completa solo prima del merge, con le porte 8000–8003 libere.
- Indicazione esatta: `per l'elenco delle note chiama `list_notes`` dentro «(indicazione del programma: …)».

## Review Focus

- Due `add` in sequenza dopo un'eliminazione nel mezzo: la prima prende il buco, la seconda N+1 (test in Task 1).
- Compattazione su archivio già compatto o vuoto: nessun cambiamento, nessun errore (test in Task 1).
- «Elimina la nota 5» / «aggiungi una nota: …» non ricevono l'indicazione `list_notes` (test in Task 2).
- Revisore che boccia: la prima bozza sparisce, la seconda arriva in streaming (prova nel browser, Task 3).
- `MAX_REVIEWS=0`: a fine turno nessun timbro «in revisione…» rimasto appeso (prova nel browser, Task 3).

---

### Task 1: numeri delle note (archivio e compattazione)

**Files:**
- Modify: `notes_service/store.py` (`_ORDER`, `NoteStore.add`, nuovo `NoteStore.compact`)
- Create: `notes_service/compact.py`
- Test: `tests/test_notes_store.py`

**Interfaces:**
- Produces: `NoteStore.compact() -> list[tuple[int, int]]` (coppie `(vecchio, nuovo)` solo per le note cambiate, in ordine); `python -m notes_service.compact [--db PERCORSO]`.

- [ ] **Step 1: test che falliscono** in `tests/test_notes_store.py`:
  - `test_ordering` riscritto: stesse cinque note → `[1, 2, 3, 4, 5]`.
  - `test_add_reuses_smallest_free_id`: aggiunge 4 note, elimina 2 e 3, poi `add` → id 2, `add` → id 3, `add` → id 5.
  - `test_add_on_empty_store_starts_from_one`: archivio nuovo, poi aggiungi ed elimina la 1, poi `add` → id 1.
  - `test_compact_renumbers_in_id_order`: note 1…5, elimina 1 e 3 → `compact()` restituisce `[(2, 1), (4, 2), (5, 3)]`; `list_notes` dà id `[1, 2, 3]` con i testi di prima nello stesso ordine; il `add` successivo → id 4.
  - `test_compact_noop`: archivio vuoto e archivio già 1…3 → `compact()` restituisce `[]`.
  - `test_compact_command(tmp_path, capsys)`: crea un db con note 2 e 5 (aggiungi 5, elimina 1, 3, 4), lancia `compact.main(["--db", str(db)])`, l'uscita contiene «2 → 1» e «5 → 2»; con archivio già compatto stampa «Nessuna nota da rinumerare.».
- [ ] **Step 2:** `python -m pytest tests/test_notes_store.py -q` → falliscono i nuovi.
- [ ] **Step 3: implementare.**
  - `_ORDER = "ORDER BY id"`; commento aggiornato.
  - `add`: un'unica istruzione `INSERT INTO notes (id, text, due_date, created_at) SELECT COALESCE(MIN(n.id + 1), 1), ?, ?, ? FROM (SELECT 0 AS id UNION ALL SELECT id FROM notes) n WHERE n.id + 1 NOT IN (SELECT id FROM notes)`; `lastrowid` come oggi.
  - `compact`: in una transazione, per ogni nota in ordine di id con posizione `k` (da 1) e `id != k`, `UPDATE notes SET id = k WHERE id = old` (in ordine crescente il posto `k` è sempre libero); restituisce le coppie cambiate.
  - `compact.py`: `main(argv: list[str] | None = None) -> None` con argparse (`prog="python -m notes_service.compact"`, `--db` predefinito `DEFAULT_DB` di `notes_service.__main__`), stampa una riga «vecchio → nuovo» per coppia o «Nessuna nota da rinumerare.»; `if __name__ == "__main__": main()`.
- [ ] **Step 4:** `python -m pytest tests/test_notes_store.py tests/test_notes_service.py tests/test_notes_tools.py -q` → tutti passano.
- [ ] **Step 5: commit** `feat(note): numero libero più piccolo, elenco per ID e comando di compattazione`.

### Task 2: indicazione `list_notes`

**Files:**
- Modify: `assistant/graph.py` (`tool_hints`, nuova regex accanto a `_HOLIDAY_QUESTION`)
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `tool_hints(text: str) -> str` esistente (stessa forma dell'indicazione).

- [ ] **Step 1: test che falliscono:** aggiungere a `test_tool_hints` i casi, tutti con hint ``per l'elenco delle note chiama `list_notes` ``: «che note ci sono?», «Mostrami le note», «quali promemoria ho?», «elenca le mie note», «Quante note ho?», «fammi vedere la lista delle note». Aggiungere a `test_tool_hints_leave_other_questions`: «elimina la nota cinque», «Aggiungi una nota: comprare il latte», «cancella tutte le note», «salva queste note sul Python», «Che ore sono a Tokyo?».
- [ ] **Step 2:** `python -m pytest tests/test_graph.py -q -k tool_hints` → falliscono i nuovi.
- [ ] **Step 3: implementare:** `_NOTES_LIST` = parola intera `note|promemoria` e una parola di elenco (`che|quali|quante|elenc\w*|mostr\w*|vedere|lista|mie`); `_NOTES_ACTION` = `aggiung|crea|salva|elimin|cancell` (radici, senza distinzione di maiuscole). Se `_NOTES_LIST` trova e `_NOTES_ACTION` no, aggiungere l'indicazione in fondo alla lista `hints`.
- [ ] **Step 4:** `python -m pytest tests/test_graph.py -q` → passano.
- [ ] **Step 5: commit** `feat(grafo): indicazione list_notes quando si chiede l'elenco delle note`.

### Task 3: bozza visibile in streaming

**Files:**
- Modify: `frontend_service/static/app.js` (`setPending`, `reveal`, ramo `risposta` di `runTurn`, fine turno), `frontend_service/static/style.css`

**Interfaces:**
- Consumes: `STAMP_TEXT.pending` («in revisione…») e `setStamp` esistenti.

- [ ] **Step 1: implementare** secondo la spec (revisione 2026-11-26):
  - nuova `showDraft(view)`: `answer` con classe `answer-draft` (non `answer-pending`), `renderText(view.draft)` e `setStamp(answer, "pending")`; chiamata a ogni pezzo di `risposta` al posto di `setPending(view, "Pico scrive la risposta")`.
  - il timer di 1,5 s cambia solo `updateTrace(view, "in revisione…")` e `setTurnState("review")`, non il testo.
  - `reveal(view)` toglie `answer-draft` (e `answer-pending`); con verdetto mette il timbro, senza verdetto lo toglie.
  - a `fine` senza verdetto (revisore spento) chiamare `reveal(view)` se la bozza è visibile.
  - bocciatura (`REVIEW_RETRY`): invariata (`setPending` «Il revisore ha chiesto una nuova risposta»), poi la nuova bozza riparte con `showDraft`.
  - CSS: `.answer-draft { color: var(--mute); }`; `.stamp[data-verdict="pending"] { color: var(--mute); }`.
- [ ] **Step 2:** `python -m pytest tests/test_frontend_service.py -q` → passano (percorsi invariati).
- [ ] **Step 3: prova nel browser (Claude, se possibile, altrimenti l'utente):** domanda semplice → testo che cresce attenuato con «in revisione…», poi normale con «✓ revisionata»; con `MAX_REVIEWS=0` nessun timbro a fine turno; ricarica pagina → risposte salvate come prima.
- [ ] **Step 4: commit** `feat(frontend): bozza visibile in streaming durante la revisione`.

### Task 4: documentazione, compattazione dei dati, verifica

**Files:**
- Modify: `README.md` (scelta dello streaming con il revisore e motivo, slide 18; numeri delle note e comando `python -m notes_service.compact`; esiti «Prova reale del front-end»), `CLAUDE.md` (comando di compattazione nella struttura di `notes_service/`)

- [ ] **Step 1:** README e CLAUDE.md; commit `docs: bozza in revisione, numeri delle note e compattazione`.
- [ ] **Step 2: compattazione delle note dell'utente** (servizi spenti): copia `data/notes.db` → `data/notes.db.bak`, poi `python -m notes_service.compact`; atteso 5→1, 11→2, 12→3, 14→4, 24→5, 25→6, 26→7, 27→8, 28→9 (da ricontrollare con `GET /notes` prima, l'utente può averne aggiunte).
- [ ] **Step 3: suite completa** con porte 8000–8003 libere: `python -m pytest` → tutti passano (exit 0).
- [ ] **Step 4: prova reale dell'utente nel browser**: bozza in streaming, «che note ci sono?» con `list_notes` nel menù e numeri 1…9 in ordine, nuova nota → 10, elimina una nota e aggiungine un'altra → riprende il buco. Esiti nel README.
- [ ] **Step 5:** merge `--no-ff` di `feature/frontend` in `developer`, push di `developer`, eliminare il branch e `.superpowers/sdd/2026-11-25-frontend-chat/`.
