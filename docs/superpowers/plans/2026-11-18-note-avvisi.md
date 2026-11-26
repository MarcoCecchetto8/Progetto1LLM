# Avvisi delle note: frasi brevi e richiesta esplicita — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** l'avviso dei falsi successi delle note scatta anche per le frasi brevi del modello («Nota salvata.») e quando l'utente chiede esplicitamente di salvare o eliminare una nota e lo strumento non conferma; mai quando l'utente parla d'altro.

**Architecture:** tutto dentro `check_note_claims` in `assistant/notes.py` (stessa funzione passata a `build_graph` come `answer_check`, stessi testi degli avvisi): si allargano le espressioni delle dichiarazioni e si aggiunge il riconoscimento della richiesta sulla domanda del turno (`last_question_index`). Grafo, agente, API e CLI non cambiano.

**Tech Stack:** Python, `re`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-09-note-fastapi-design.md`, sezione 5.4 e **5.5 (revisione 2026-11-18)**; test nella sezione 8.

## Global Constraints

- Branch `feature/note-avvisi` da `developer`; Conventional Commits in italiano con la riga `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; `git status`, controllo del diff, staging selettivo; nessun push. Non leggere né toccare `lezione-03/`.
- Test senza LM Studio; suite completa verde (`.venv/Scripts/python.exe -m pytest`, controllare l'exit code) prima di ogni commit.
- Testi degli avvisi invariati: `SAVE_WARNING` e `DELETE_WARNING` di `assistant/notes.py`. Ordine: salvataggio prima di eliminazione. Al massimo un avviso per tipo.
- Confronto in minuscolo e senza accenti (la `_normalize` esistente).
- Conferma = risultato **senza errore** dello strumento corrispondente dopo l'ultima domanda dell'utente (`delete_note` annullata vale come conferma), per entrambe le regole.
- Regola utente: **se l'utente parla d'altro non deve mai comparire un avviso sulle note**; nel dubbio una forma di richiesta resta fuori dall'elenco.
- Nessuna nuova dipendenza.

## Review Focus

1. Domande che parlano d'altro con le stesse parole («Ricordami come mi chiamo», «Come si cancella un file in Python?», «Salva il mondo dalla noia: …», «Cos'è una nota a piè di pagina?», «Qual è la nota più alta di un pianoforte?») → nessun avviso, qualunque sia la risposta. Test nel Task 2.
2. Risposte vere di `list_notes` con il participio come aggettivo («Nessuna nota salvata.», «Non hai note salvate.», «Hai 2 note salvate.») → nessun avviso anche con le nuove frasi brevi. Test nel Task 1.
3. Domanda del turno = l'ultima vera dell'utente: un'indicazione del revisore (`review_feedback`) dopo «Salva una nota: x» non cancella la richiesta, e una richiesta di un turno precedente non vale per il turno attuale. Test nel Task 2.
4. Risposta che è una domanda di chiarimento (termina con «?», anche seguita da spazi) → nessun avviso legato alla richiesta, ma una dichiarazione falsa nella stessa risposta («Ho salvato la tua nota. Vuoi una scadenza?») dà comunque l'avviso. Test nel Task 2.
5. Domanda dell'utente non testuale (contenuto a lista) o turno senza domanda → nessun errore, solo la regola delle dichiarazioni. Test nel Task 2.

---

### Task 1: Frasi brevi e passivi mancanti nelle dichiarazioni

**Files:**
- Modify: `assistant/notes.py` (`_SAVE_CLAIM`, `_DELETE_CLAIM` e il commento sopra)
- Test: `tests/test_notes_tools.py`

**Interfaces:**
- Produces: `check_note_claims(messages)` invariata nella firma; riconosce in più le dichiarazioni brevi.

- [ ] **Step 1: test che falliscono** (con l'aiuto `turn(answer, *tools)` esistente):

```python
@pytest.mark.parametrize("answer", [
    "Nota salvata.", "Ok, nota salvata!", "Fatto: promemoria registrato.", "Nota 6 salvata: «x».",
    "Perfetto, la nota è stata aggiunta.", "Ho creato un promemoria per lunedì.", "La nota è stata creata.",
])
def test_short_and_passive_save_claims_warn(answer):
    assert check_note_claims(turn(answer)) == [SAVE_WARNING]

@pytest.mark.parametrize("answer", ["Nota 6 eliminata.", "Ok, nota cancellata.", "Promemoria 3 rimosso."])
def test_short_delete_claims_warn(answer):
    assert check_note_claims(turn(answer)) == [DELETE_WARNING]

def test_short_claim_confirmed_by_tool():
    assert check_note_claims(turn("Nota 6 salvata: «x».", tool_msg("Nota 6 salvata: «x»", "add_note"))) == []
```

  e aggiungere a `test_no_claim_no_warning`: `"Hai 2 note salvate."` e `"Ecco le note salvate finora: nessuna."`. (Limite accettato, da non testare come negativo: una frase che apre con «La nota salvata ieri…» darebbe avviso; nel dubbio un avviso di troppo, sezione 5.4.)

- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_notes_tools.py -q` → i nuovi test FAIL.

- [ ] **Step 3:** estendere le espressioni:
  - frase breve: participio senza ausiliare quando **apre la frase** (inizio del testo o dopo `.`, `!`, `?`, `:` e spazi), eventualmente preceduto da `ok|fatto|perfetto|bene` con `,`/`!`/`:`, poi `la`? + `nota|promemoria` + numero facoltativo (`6`, `n. 6`) + participio. Radici per il salvataggio `salvat|memorizzat|annotat|registrat|aggiunt|creat`; per l'eliminazione `eliminat|cancellat|rimoss`; desinenza `[aoie]`;
  - nelle forme esistenti `ho …` ed `è/sono stat…` aggiungere `creat` (salvataggio) e il passivo di `aggiunt` (`è stata aggiunta`), mantenendo per `ho aggiunt…` la regola attuale (solo se seguito da nota/note/promemoria, per non confondere `add_days`).
  Aggiornare il commento sopra le espressioni (perché la frase breve conta solo a inizio frase: «Nessuna nota salvata» resta un aggettivo).

- [ ] **Step 4:** stessi test → PASS; suite completa verde.

- [ ] **Step 5: commit** `feat(note): avviso anche per le frasi brevi come «Nota salvata.»`

---

### Task 2: Avviso legato alla richiesta esplicita

**Files:**
- Modify: `assistant/notes.py` (`check_note_claims`, nuove espressioni `_SAVE_REQUEST`, `_DELETE_REQUEST`)
- Modify: `README.md` (sezione del controllo dei falsi successi / note: nuova regola, misura, limiti), `docs/superpowers/specs/2026-11-09-note-fastapi-design.md` (nessuna modifica attesa salvo refusi)
- Test: `tests/test_notes_tools.py`

**Interfaces:**
- Consumes: `check_note_claims` del Task 1; `last_question_index` da `assistant.reviewer` (già usata).
- Produces: `check_note_claims(messages) -> list[str]` che restituisce `[SAVE_WARNING]`, `[DELETE_WARNING]`, entrambi in quest'ordine, o `[]`.

- [ ] **Step 1: test che falliscono.** Aggiungere ai test un aiuto `asked(question, answer, *tools, history=())` uguale a `turn` ma con `HumanMessage(question)`.

```python
SAVE_REQUESTS = ["Salva una nota: comprare il pane", "Annota che domani ho il dentista",
                 "Segnati che venerdì devo chiamare Luca", "Aggiungi una nota: pagare la bolletta",
                 "Ricordami di innaffiare le piante", "Crea un promemoria per la riunione di lunedì",
                 "Nota: comprare le uova", "Scrivi una nota: riportare il libro", "Per favore, salvami un promemoria: x"]
DELETE_REQUESTS = ["Elimina la nota 1", "Cancella la nota 2", "Rimuovi il promemoria 3", "elimina le note 4 e 5"]
OTHER_TOPICS = ["Ricordami come mi chiamo", "Ricordami cosa abbiamo detto", "Cos'è una nota a piè di pagina?",
                "Come si cancella un file in Python?", "Come elimino un elemento da una lista in Python?",
                "Come si salva un file in Python?", "Che differenza c'è tra annotazioni e commenti in Python?",
                "Salva il mondo dalla noia: spiegami cos'è il machine learning",
                "Qual è la nota più alta di un pianoforte?", "Che note ho?", "Mi ricordi di cosa parla la nota 3?"]

@pytest.mark.parametrize("question", SAVE_REQUESTS)
def test_save_request_without_tool_warns(question):
    assert check_note_claims(asked(question, "Ti ricordo di farlo.")) == [SAVE_WARNING]

@pytest.mark.parametrize("question", SAVE_REQUESTS)
def test_save_request_with_tool_no_warning(question):
    assert check_note_claims(asked(question, "Fatto.", tool_msg("Nota 1 salvata: «x»", "add_note"))) == []

@pytest.mark.parametrize("question", DELETE_REQUESTS)
def test_delete_request_without_tool_warns(question):
    assert check_note_claims(asked(question, "Dovrai prima confermare l'eliminazione.")) == [DELETE_WARNING]

@pytest.mark.parametrize("question", OTHER_TOPICS)
def test_other_topics_never_warn(question):
    assert check_note_claims(asked(question, "Ecco la risposta.")) == []
```

  e inoltre:
  - `test_request_and_claim_give_one_warning`: `asked("Salva una nota: x", "Nota salvata.")` → `[SAVE_WARNING]`;
  - `test_save_and_delete_request_both_warn`: `asked("Salva una nota: x ed elimina la nota 3", "Ok.")` → `[SAVE_WARNING, DELETE_WARNING]` (la seconda richiesta non è a inizio domanda: vedi Step 3, l'eliminazione si cerca anche dopo `e`/`ed`/`,`);
  - `test_clarifying_question_no_request_warning`: `asked("Salva una nota", "Che testo vuoi salvare?  ")` → `[]`;
  - `test_false_claim_with_question_still_warns`: `asked("Salva una nota: x", "Ho salvato la tua nota. Vuoi una scadenza?")` → `[SAVE_WARNING]`;
  - `test_failed_tool_warns`: `asked("Elimina la nota 99", "Non esiste.", tool_msg("Nessuna nota con ID 99…", "delete_note", "error"))` → `[DELETE_WARNING]`;
  - `test_review_feedback_keeps_request`: domanda «Salva una nota: x», risposta, indicazione del revisore (`feedback_message("…")` di `assistant.reviewer`), nuova risposta «Ok.» → `[SAVE_WARNING]`;
  - `test_previous_turn_request_not_counted`: `history=[HumanMessage("Salva una nota: x"), AIMessage("…")]`, domanda attuale «Che ore sono?» → `[]`;
  - `test_non_text_question_ignored`: `HumanMessage(content=[{"type": "text", "text": "Salva una nota: x"}])` → `[]` (nessun errore).

- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_notes_tools.py -q` → i nuovi test FAIL.

- [ ] **Step 3:** in `check_note_claims`:
  - domanda = `messages[last_question_index(messages)]` se l'indice è valido e il contenuto è una stringa; altrimenti nessuna richiesta;
  - `_SAVE_REQUEST` sulla domanda normalizzata, **solo all'inizio** (eventuale `per favore`/`ok`/`ehi` + virgola): `(salva|salvami|annota|annotami|segna|segnati|segnami|scrivi|scrivimi|aggiungi|crea)` + articolo facoltativo + `nota|note|promemoria`; `(annota|annotati|segna|segnati|scrivi|scriviti) che`; `ricordami di`; `(nota|promemoria)\s*:`. Il prototipo misurato è nella sezione «Misura» del README (11/11 richieste, 0/10 altri argomenti);
  - `_DELETE_REQUEST`: `(elimina|cancella|rimuovi)` + articolo facoltativo + `nota|note|promemoria`, all'inizio della domanda **o** dopo `e`/`ed`/`,`/`poi`;
  - avviso legato alla richiesta solo se lo strumento non conferma **e** la risposta, tolti gli spazi finali, non termina con `?`;
  - unione con le dichiarazioni del Task 1 senza duplicati, ordine salvataggio → eliminazione. La riga di log `INFO` del nodo `answer_check` resta quella attuale.

- [ ] **Step 4:** stessi test → PASS; suite completa verde.

- [ ] **Step 5:** README: nella parte sul controllo dei falsi successi descrivere le due regole (dichiarazioni, comprese le frasi brevi; richiesta esplicita con l'elenco), l'eccezione della domanda di chiarimento, i limiti (forme non previste passano; «Ricordami di…» con chiarimento non avvisa) e la misura del 2026-11-18 con `liquid/lfm2-24b-a2b`: 21 domande, richieste riconosciute 11/11, avvisi sulle domande d'altro 0/10, risposte senza strumento («Nota: comprare le uova» → dichiarazione falsa con avviso; «Ricordami di innaffiare…», «Segnati che venerdì…» → chiarimento senza avviso). Prova reale da fare: sezione con le righe da compilare (una richiesta salvata, «Nota salvata.» se ricapita, una domanda d'altro con «ricordami»).

- [ ] **Step 6: commit** `feat(note): avviso quando la richiesta esplicita non viene eseguita`
