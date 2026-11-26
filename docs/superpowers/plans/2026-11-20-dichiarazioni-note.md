# Dichiarazioni con l'ausiliare legate alla nota — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** le dichiarazioni con l'ausiliare («ho salvato», «è stato eliminato»…) fanno scattare l'avviso delle note solo se nella stessa frase compare «nota», «note» o «promemoria» (o se sono forme con il pronome «l'ho …»).

**Architecture:** solo `check_note_claims` in `assistant/notes.py`: il testo della risposta si divide in frasi e le espressioni `_SAVE_CLAIM`/`_DELETE_CLAIM` contano su una frase solo se la frase contiene una parola della nota oppure la forma con il pronome. Frasi brevi della 5.5, regola della richiesta esplicita, testi degli avvisi e conferme invariati.

**Tech Stack:** Python, `re`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-09-note-fastapi-design.md`, sezione 5.7 (revisione 2026-11-20).

## Global Constraints

- Branch `feature/dichiarazioni-note` da `developer`; Conventional Commits in italiano con la riga ESATTA `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; `git status`, controllo del diff, staging selettivo; nessun push. Non leggere né toccare `lezione-03/`.
- Test senza LM Studio; la suite completa la lancia il controller.
- Frase = testo fra `.`, `!`, `?` o a capo (sul testo normalizzato con `_normalize`). Parole della nota: `nota`, `note`, `promemoria` (parola intera). Forma con il pronome: `l'ho`/`l ho` (anche `l'ho già`) seguita dal participio.
- Testi degli avvisi, ordine salvataggio → eliminazione, un avviso per tipo, conferme e regola della richiesta: invariati.

## Review Focus

1. Risposte di programmazione con «ho salvato/eliminato/cancellato/rimosso», «è stato salvato», «sono state registrate» senza la parola nota → nessun avviso (test).
2. Dichiarazioni vere sulle note in tutte le forme raccolte → avviso invariato, comprese «Ho salvato la nuova nota e ho eliminato la vecchia» e le forme con il pronome (test).
3. Una risposta con più frasi, una sulla nota e una su un file («Ho salvato la nota. Il file è stato eliminato.») → solo l'avviso di salvataggio (test).
4. Frasi brevi della 5.5 («Nota salvata.», «Nota 6 eliminata.») e i negativi di `list_notes` invariati (test esistenti verdi).
5. Numeri decimali o abbreviazioni con il punto («n. 3», «3.14») che spezzano la frase: «La nota n. 3 è stata eliminata.» resta una dichiarazione (test).

---

### Task 1: Dichiarazioni con l'ausiliare solo nelle frasi che parlano della nota

**Files:**
- Modify: `assistant/notes.py` (`check_note_claims` e il commento sopra le espressioni)
- Modify: `README.md` (sezione del controllo dei falsi successi: nuova regola; il limite «Ho cancellato il file…» nelle risposte di programmazione è risolto)
- Test: `tests/test_notes_tools.py`

**Interfaces:**
- Produces: `check_note_claims(messages)` con la stessa firma e gli stessi risultati possibili.

- [ ] **Step 1: test che falliscono** (aiuto `turn(answer, *tools)` esistente):

```python
@pytest.mark.parametrize("answer", [
    "Ho cancellato il file temporaneo nell'esempio.",
    "Il file è stato salvato con open() in modalità 'w'.",
    "Le modifiche sono state salvate nel repository.",
    "Il record è stato eliminato dal database.",
    "Nel codice, ho eliminato la variabile inutile.",
    "Ho salvato il modello con torch.save().",
    "I dati sono stati registrati nel log.",
    "Ho rimosso il ciclo superfluo: ora la funzione è più veloce.",
    "La riga è stata cancellata con DELETE FROM utenti WHERE id = 3.",
    "Dopo git commit le modifiche sono state registrate.",
])
def test_programming_claims_never_warn(answer):
    assert check_note_claims(turn(answer)) == []

def test_note_sentence_and_file_sentence():
    assert check_note_claims(turn("Ho salvato la nota. Il file è stato eliminato.")) == [SAVE_WARNING]

def test_abbreviation_keeps_the_sentence():
    assert check_note_claims(turn("La nota n. 3 è stata eliminata.")) == [DELETE_WARNING]
```

  I test esistenti delle dichiarazioni (`test_claim_without_add_note_warns`, `test_claim_passive_and_accents_warn`, `test_claim_clitic_and_added_note_warn`, `test_delete_claim_without_tool_warns`, `test_delete_clitic_claim_warns`, `test_both_claims_warn_in_order`, frasi brevi, negativi) devono restare verdi senza modifiche; se uno di loro usa una dichiarazione senza la parola nota (per esempio `"Ho salvato un promemoria per te"` contiene «promemoria»: resta), segnalarlo nel report invece di cambiarlo.

- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_notes_tools.py -q` → i nuovi test FAIL.
- [ ] **Step 3:** in `check_note_claims`, sul testo normalizzato, dividere in frasi con `[.!?\n]+` dopo aver protetto i punti delle abbreviazioni e dei numeri (almeno `n.` seguito da cifra e il punto fra due cifre); per ogni frase le espressioni `_SAVE_CLAIM`/`_DELETE_CLAIM` contano solo se la frase contiene `\b(nota|note|promemoria)\b` oppure la forma con il pronome. Le frasi brevi della 5.5 contengono già la parola e restano riconosciute.
- [ ] **Step 4:** stessi test → PASS; `tests/test_notes_tools.py tests/test_graph.py` verdi.
- [ ] **Step 5:** README: nella sezione del controllo dei falsi successi, la regola della stessa frase e la misura senza modello del 2026-11-20 (112 risposte vere registrate: nessuna differenza; 10 risposte di programmazione: 10 avvisi sbagliati prima, 0 dopo; 10 dichiarazioni sulle note: 10/10 prima e dopo); togliere o aggiornare la riga dei limiti su «Ho cancellato il file…».
- [ ] **Step 6: commit** `fix(note): dichiarazioni con l'ausiliare solo nelle frasi sulla nota`
