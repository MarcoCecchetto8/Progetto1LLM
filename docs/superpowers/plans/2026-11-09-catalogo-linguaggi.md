# Catalogo dei linguaggi — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** aggiungere al server MCP un catalogo locale di 20 linguaggi di programmazione con due tool, `search_catalog` e `get_item`, usati dal modello in sequenza.

**Architecture:** dati in `lab_server/catalog.json` (pacchetto del server, letto con `importlib.resources` come `holidays.json`); logica in funzioni pure in `lab_server/catalog.py` che sollevano `ValueError`; `server.py` registra i due tool con l'helper `run()` esistente (che converte in `ToolError`). Assistente, client MCP e grafo non cambiano, tranne le istruzioni di sistema.

**Tech Stack:** invariato (Python 3.14, fastmcp 3.4.11, pydantic tramite fastmcp, pytest 9.1.1); nessuna dipendenza nuova.

**Spec:** `docs/superpowers/specs/2026-11-09-catalogo-linguaggi-design.md`

## Global Constraints

- Branch `feature/catalogo` da `developer` aggiornato; a fine lavoro, **dopo la prova reale e l'ok dell'utente**: `git checkout developer`, `git merge --no-ff feature/catalogo -m "chore: unisce feature/catalogo in developer"`, `git push origin developer`, `git branch -d feature/catalogo`. Il branch feature non si pusha.
- Pezzi piccoli, un commit per task (o meno); prima di ogni commit `git status`, diff, staging selettivo; controllare l'**exit code** di pytest, non solo l'ultima riga.
- Nessuna dipendenza nuova, nessuna nuova variabile d'ambiente.
- Nomi nel codice in inglese; dati, risultati, errori, log, README e commit in italiano (Conventional Commits).
- Ogni input non valido → `ValueError` nella logica → `ToolError` nel server; la ricerca senza risultati è un risultato normale.
- `max_results`: intero da 1 a 20, predefinito 5.
- **Il contenuto di `catalog.json` va mostrato all'utente e approvato prima del commit**; solo fatti verificabili.
- Comandi dalla radice con il venv attivo (`.\.venv\Scripts\Activate.ps1`); test: `python -m pytest`.
- Non leggere né modificare `lezione-03/`.

## Review Focus

1. **Il modello passa una frase intera come query** («chi ha creato Haskell?»): punteggiatura e parole vuote ignorate, Haskell primo nei risultati. Test nel Task 2.
2. **`max_results` fuori intervallo o come testo** (`0`, `21`, `"10"`): `0`/`21` → errore in italiano che dice il limite; `"10"` accettato. Test nel Task 3.
3. **Il modello passa a `get_item` un nome invece del codice** (`"Python"`, `"C++"`): errore che rimanda a `search_catalog`, nessun crash. Test nel Task 2.
4. **Maiuscole, accenti e simboli nella query** (`FUNZIONALE`, `c++`, `C#`): riconosciuti; `C` non trova tutti i linguaggi con una «c». Test nel Task 2.
5. **Query fatta solo di parole vuote o di punteggiatura** («linguaggi di programmazione», `"?"`): errore che chiede una parola chiave, non una lista di tutto il catalogo. Test nel Task 2.

---

### Task 1: Dati del catalogo

**Files:**
- Create: `lab_server/catalog.json`, `tests/test_server_catalog.py`

**Interfaces:**
- Produces: `catalog.json` = lista di oggetti `{"code", "name", "year", "authors", "paradigms", "typing", "description"}` (spec §4), ordinati per `code`.

- [ ] **Step 1:** `git checkout developer`, `git pull`, `git checkout -b feature/catalogo`.
- [ ] **Step 2: test della forma** in `tests/test_server_catalog.py` (`test_catalog_file_shape`), leggendo il file con `json.loads(files("lab_server").joinpath("catalog.json").read_text(encoding="utf-8"))`:
  - 20 elementi; insieme dei codici `== {"C", "CPP", "CS", "COBOL", "FORTRAN", "GO", "HS", "JAVA", "JS", "KT", "LISP", "PASCAL", "PHP", "PROLOG", "PY", "RB", "RS", "SQL", "SWIFT", "TS"}`;
  - ogni elemento ha esattamente le 7 chiavi; `code` maiuscolo; `name` e `description` testi non vuoti; `year` intero fra 1950 e 2020; `authors` lista non vuota di testi; `paradigms` lista non vuota ⊆ `{"imperativo", "procedurale", "a oggetti", "funzionale", "logico", "dichiarativo", "concorrente"}`; `typing in {"statica", "dinamica"}`.
- [ ] **Step 3:** `python -m pytest tests/test_server_catalog.py` → FAIL (file assente).
- [ ] **Step 4:** scrivi `catalog.json` (UTF-8, indentazione 2, `ensure_ascii` falso) con i 20 linguaggi della spec; descrizioni in italiano di una o due frasi, solo fatti noti; anno più comunemente citato.
- [ ] **Step 5:** test → PASS.
- [ ] **Step 6: approvazione dell'utente:** mostra il contenuto del file all'utente (tabella codice/nome/anno/autori/paradigmi/tipizzazione più le descrizioni) e applica le correzioni richieste. Non procedere senza ok.
- [ ] **Step 7:** commit `feat(catalogo): aggiunge il catalogo dei linguaggi di programmazione`.

### Task 2: Ricerca e dettaglio (funzioni pure)

**Files:**
- Create: `lab_server/catalog.py`
- Test: `tests/test_server_catalog.py`

**Interfaces:**
- Consumes: `catalog.json` (Task 1).
- Produces:
  - `MAX_RESULTS = 20`, `DEFAULT_RESULTS = 5`
  - `search(query: str, max_results: int = DEFAULT_RESULTS) -> str`
  - `get_item(code: str) -> str`

**Regole (spec §5, valori fissati qui):**
- Parole: `unicodedata.normalize("NFKD", …)`, tolti i caratteri combinanti, `casefold()`, poi `re.findall(r"[0-9a-z]+[+#]*", text)` (così `C++` → `c++`, `C#` → `c#`). Stessa funzione per query e campi.
- Campi cercati: `code`, `name`, `str(year)`, `authors`, `paradigms`, `description`.
- Parole vuote (tolte solo dalla query): `a, al, alla, che, chi, con, creato, da, dal, dei, del, della, delle, di, e, gli, ha, i, il, in, la, le, linguaggi, linguaggio, lo, nato, nati, nel, o, per, programmazione, quale, quali, sono, un, una`.
- Corrispondenza: almeno una parola distinta della query è uguale a una parola dei campi. Ordine: numero di parole distinte trovate (decrescente), poi `name.casefold()`.
- Testi:
  - intestazione `Trovati {n} linguaggi per "{q}":` (con `n == 1`: `Trovato 1 linguaggio per "{q}":`), e se troncata `Trovati {n} linguaggi per "{q}", mostrati {m}:`; `q` = query senza spazi ai bordi;
  - righe `- {code}: {name} ({year})`;
  - se troncata: `Ci sono altri {n - m} risultati: ripeti la ricerca con max_results più alto.`;
  - ultima riga `Usa get_item con il codice per i dettagli.`;
  - vuota: `Nessun linguaggio corrisponde a "{q}".`
  - dettaglio, righe: `{name} ({code})`, `Anno: {year}`, `Autori: {a, b}`, `Paradigmi: {p, q}`, `Tipizzazione: {typing}`, `Descrizione: {description}`.
- Errori (`ValueError`): query senza parole utili → `La ricerca richiede almeno una parola chiave (es. funzionale, Haskell).`; `max_results` fuori 1–20 → `max_results deve essere compreso fra 1 e 20.`; codice vuoto → `Il codice è vuoto: usa search_catalog per trovare il codice.`; codice inesistente → `Codice "{code}" non presente nel catalogo: usa search_catalog per trovare il codice.` (`code` senza spazi ai bordi, come scritto dal modello).

- [ ] **Step 1: test** in `tests/test_server_catalog.py`:
  - `search("Haskell")` contiene `"- HS: Haskell ("` e `'Trovato 1 linguaggio per "Haskell":'`;
  - `search("Ritchie")` contiene `"- C: C ("`; `search("funzionale", 20)` contiene `HS` e `LISP` e non `"- COBOL:"`;
  - `search("C")`: prima riga di risultato `- C: C (`, e non contiene `"- COBOL:"` né `"- PY:"`; `search("c++")` contiene `"- CPP:"`; `search("C#")` contiene `"- CS:"`;
  - `search("FUNZIONALE")` uguale a `search("funzionale")`; `search("logico")` contiene `"- PROLOG:"`;
  - Review Focus 1: in `search("chi ha creato Haskell?")` la prima riga di risultato è `- HS: Haskell (`;
  - ordine: in `search("funzionale Haskell", 20)` la prima riga di risultato è `HS`;
  - troncamento: con `n = conteggio di "funzionale"` maggiore di 2, `search("funzionale", 2)` contiene `f"mostrati 2:"`, esattamente 2 righe `"- "` e `"ripeti la ricerca con max_results più alto"`; con `max_results=20` nessuna di queste frasi;
  - `search("cobra")` == `'Nessun linguaggio corrisponde a "cobra".'`;
  - Review Focus 5: `search("")`, `search("linguaggi di programmazione")`, `search("?")` → `ValueError` con `"parola chiave"`;
  - `search("python", 0)` e `search("python", 21)` → `ValueError` con `"fra 1 e 20"`; `search("python", 1)` e `search("python", 20)` validi;
  - `get_item("PY")`, `get_item("py")`, `get_item(" Py ")` uguali e iniziano con `"Python (PY)\nAnno: 1991\n"`; contengono `"Autori: Guido van Rossum"`, `"Tipizzazione: dinamica"`;
  - `get_item("XYZ")` → `ValueError` == `'Codice "XYZ" non presente nel catalogo: usa search_catalog per trovare il codice.'`; `get_item("  ")` → `ValueError` con `"vuoto"`;
  - Review Focus 3: `get_item("Python")` e `get_item("C++")` → `ValueError` con `"usa search_catalog"`.
- [ ] **Step 2:** FAIL → implementa in `lab_server/catalog.py` (lettura del file con `@cache` come in `holidays.py`) → PASS.
- [ ] **Step 3:** `python -m pytest` tutto verde (exit code 0); commit `feat(catalogo): aggiunge ricerca e dettaglio sul catalogo`.

### Task 3: Tool MCP, errori di intervallo e istruzioni di sistema

**Files:**
- Modify: `lab_server/server.py`, `lab_server/validation.py`, `assistant/graph.py`
- Test: `tests/test_server.py`, `tests/test_graph.py`

**Interfaces:**
- Consumes: `catalog.search`, `catalog.get_item`, `MAX_RESULTS`, `DEFAULT_RESULTS` (Task 2).
- Produces (in `create_server`, con l'helper `run()` esistente):
  - `search_catalog(query: str, max_results: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = DEFAULT_RESULTS) -> str` — docstring: cerca linguaggi di programmazione nel catalogo per parole chiave (nome, autore, paradigma, anno, parole della descrizione); passare poche parole al singolare (es. funzionale, Haskell, Bell Labs); restituisce un elenco breve con codice, nome e anno e il numero totale trovato; usarlo quando non si conosce il codice.
  - `get_item(code: str) -> str` — docstring: tutte le informazioni di un solo linguaggio dato il suo codice (es. PY, HS), ottenuto da search_catalog.
  - In `validation._describe`: tipo `greater_than_equal` → `f'{field}: "{value}" troppo piccolo (minimo {ge})'`; `less_than_equal` → `f'{field}: "{value}" troppo grande (massimo {le})'` (valori da `error["ctx"]`).

- [ ] **Step 1: test** in `tests/test_server.py`:
  - il test del catalogo MCP (oggi con 7 nomi) elenca 9 tool, con `search_catalog` e `get_item`;
  - schema: `inputSchema["properties"]["max_results"]` ha `minimum == 1`, `maximum == 20`, `default == 5`;
  - `call_tool("search_catalog", {"query": "Haskell"})` contiene `"HS: Haskell"`; `call_tool("get_item", {"code": "hs"})` inizia con `"Haskell (HS)"`;
  - `get_item {"code": "XYZ"}` → `is_error` e testo con `"non presente nel catalogo"`;
  - Review Focus 2: `search_catalog {"query": "python", "max_results": 0}` → `is_error`, testo `'Argomenti non validi per search_catalog: max_results: "0" troppo piccolo (minimo 1).'`; con `21` → `"troppo grande (massimo 20)"`; con `"10"` → successo;
  - `search_catalog {"query": "cobra"}` → **non** `is_error`, testo `'Nessun linguaggio corrisponde a "cobra".'`.
- [ ] **Step 2: test** in `tests/test_graph.py`:
  - `test_system_prompt_mentions_catalog`: il prompt contiene `search_catalog`, `get_item` e `max_results`;
  - `test_graph_catalog_search_then_detail`: con `MCPClient([sys.executable, "-m", "lab_server"], os.environ)` e modello finto `tool_call({"query": "Haskell"}, "s1", name="search_catalog")`, `tool_call({"code": "HS"}, "g1", name="get_item")`, `AIMessage("Haskell è del 1990.")`: i `ToolMessage` sono `[("s1", success), ("g1", success)]`, il secondo inizia con `"Haskell (HS)"`, l'ultimo messaggio è la risposta finale, `steps == 3`.
- [ ] **Step 3:** FAIL → implementa tool, messaggi di intervallo e istruzioni → PASS. Frase per `system_prompt` (prima di quella sugli errori): «Per domande sui linguaggi di programmazione usa `search_catalog` con poche parole chiave al singolare quando non conosci il codice, poi `get_item` con il codice trovato; rispondi solo con i dati restituiti dagli strumenti e di' chiaramente quando un dato non è nel catalogo; se la ricerca dice che ci sono altri risultati e ti servono tutti, ripetila con `max_results` più alto.»
- [ ] **Step 4:** `python -m pytest` tutto verde (exit code 0); commit `feat(catalogo): espone ricerca e dettaglio del catalogo nel server MCP`.

### Task 4: Verifica diretta, documentazione e prova reale

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: verifica diretta** in PowerShell, annotando l'output reale: `python -m lab_server.check` (9 tool), `python -m lab_server.check search_catalog query=funzionale`, `python -m lab_server.check get_item code=PY`, `python -m lab_server.check get_item code=XYZ` (`ERRORE: Codice "XYZ" ...`, codice d'uscita 1).
- [ ] **Step 2: documentazione:** README — comandi della verifica diretta con l'output osservato; nuova sezione «Prova reale del catalogo» (descrizione, tabella con le domande della spec §8 ed esito «da provare»); numero di test aggiornato. `CLAUDE.md` — struttura (`catalog.py` + `catalog.json`), confini (catalogo fatto; note e meteo con specifica propria). Commit `docs: documenta il catalogo dei linguaggi e la sua verifica diretta`.
- [ ] **Step 3: prova reale (utente, LM Studio acceso)**, in locale e con Docker (`docker compose build`, `docker compose run --rm app`): «chi ha creato Haskell?», «quali linguaggi funzionali ci sono nel catalogo?», «quali linguaggi funzionali sono nati prima del 1980?», «c'è Brainfuck nel catalogo?», «dimmi tutto sul linguaggio con codice XYZ»; memoria e `clear`. Registrare nel README, per ogni domanda, i tool chiamati nell'ordine visto nei log e l'esito; se il modello sceglie male o inventa, annotare il punto esatto senza dichiarare superata la prova. Commit `docs: registra nel README la prova reale del catalogo`.
- [ ] **Step 4:** con l'ok dell'utente: merge `--no-ff` in `developer`, push di `developer`, eliminazione del branch; aggiornare la memoria di progetto.
