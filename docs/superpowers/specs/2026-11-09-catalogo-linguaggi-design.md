# Catalogo dei linguaggi di programmazione — specifica

Data: 2026-11-09 · Stato: approvata dall'utente il 2026-11-09

Riferimenti: lezione 5 del corso, slide 25 e 28 («Catalogo locale: più tool sullo stesso dato») e slide 31 (evidenze); specifica `2026-11-02-strumenti-mcp-design.md`, che resta valida per tutto ciò che qui non cambia (server FastMCP in stdio, client, log, errori, Docker).

## 1. Intento

Aggiungere al server MCP un piccolo **catalogo locale** di linguaggi di programmazione, consultabile con **due strumenti sullo stesso dato**: una ricerca e un dettaglio. Lo scopo didattico (slide 28) è osservare se il modello sceglie lo strumento giusto in base alle descrizioni, se concatena due chiamate (prima la ricerca, poi il dettaglio) e se dichiara un risultato vuoto senza inventare elementi.

Contenuto (scelta dell'utente): cultura generale sulla programmazione, con **fatti veri e verificabili**. Niente dati del corso ITS, niente elementi inventati.

È la prima delle tre proposte della seconda parte (ordine concordato: catalogo, poi note persistenti, poi meteo, ciascuna con la sua specifica).

## 2. Obiettivi

- Un file JSON con circa 20 linguaggi, nel pacchetto del server.
- Due tool nel server MCP: `search_catalog(query, max_results)` e `get_item(code)`, scoperti dal catalogo MCP come gli altri.
- Ricerca senza risultati dichiarata come tale; codice inesistente come errore dello strumento.
- Istruzioni di sistema aggiornate per guidare la sequenza ricerca → dettaglio.
- Test senza modello, verifica diretta con `lab_server.check`, prova reale con LM Studio in locale e con Docker.
- README e `CLAUDE.md` aggiornati.

## 3. Non obiettivi e anti-obiettivi

**Non obiettivi:**
- **Resource MCP** con il catalogo completo (facoltativa nella slide): esclusa. Il modello non la può richiedere con il tool calling; servirebbero un comando nuovo e modifiche al client senza nulla di nuovo da osservare nella conversazione. Possibile estensione futura, insieme alle altre primitive MCP (slide 29).
- Filtri strutturati negli argomenti (paradigma, intervallo di anni): la ricerca è a testo libero e i filtri li applica il modello leggendo i risultati (scelta dell'utente).
- Ricerca «intelligente»: niente sinonimi, radici delle parole (plurali), errori di battitura, ricerca per somiglianza. Il recupero di passaggi pertinenti da documenti è un altro tema (RAG, lezioni successive).
- Modifica del catalogo da parte dell'assistente (è in sola lettura).
- Note persistenti e meteo: specifiche successive.

**Anti-obiettivi:**
- un linguaggio o un dato inventato, nel file o nelle risposte;
- una ricerca senza risultati presentata come errore, o un codice inesistente presentato come successo;
- un elenco troncato senza dirlo (il modello filtrerebbe su dati incompleti senza saperlo);
- schemi o descrizioni dei tool riscritti nel client.

## 4. Dati

File `lab_server/catalog.json`, versionato in Git (*scelta di Claude*: JSON e non CSV, perché autori e paradigmi sono elenchi). Struttura: una lista di oggetti con i campi:

| Campo | Tipo | Esempio |
|---|---|---|
| `code` | testo, maiuscolo, unico | `PY` |
| `name` | testo | `Python` |
| `year` | intero (anno della prima versione pubblica o della prima implementazione) | `1991` |
| `authors` | lista di testi | `["Guido van Rossum"]` |
| `paradigms` | lista di testi, da un vocabolario chiuso | `["imperativo", "a oggetti", "funzionale"]` |
| `typing` | `"statica"` o `"dinamica"` | `"dinamica"` |
| `description` | testo in italiano, una o due frasi | |

Vocabolario dei paradigmi (*scelta di Claude*): `imperativo`, `procedurale`, `a oggetti`, `funzionale`, `logico`, `dichiarativo`, `concorrente`.

Linguaggi (*scelta di Claude*, 20): C, C++, C#, COBOL, Fortran, Go, Haskell, Java, JavaScript, Kotlin, Lisp, Pascal, PHP, Prolog, Python, Ruby, Rust, SQL, Swift, TypeScript. Codici brevi e leggibili (`C`, `CPP`, `CS`, `COBOL`, `FORTRAN`, `GO`, `HS`, `JAVA`, `JS`, `KT`, `LISP`, `PASCAL`, `PHP`, `PROLOG`, `PY`, `RB`, `RS`, `SQL`, `SWIFT`, `TS`).

**Accuratezza (richiesta dell'utente):** solo fatti noti e verificabili (anno, autori, paradigmi, tipizzazione). Dove un dato ammette più letture (per esempio l'anno di un linguaggio con una lunga gestazione), si sceglie la data più comunemente citata e la descrizione può precisarla. **Il file completo viene mostrato all'utente e approvato prima del commit.**

Un test controlla la forma del file: campi presenti e del tipo giusto, codici unici e maiuscoli, paradigmi nel vocabolario, `typing` ammesso, anni plausibili.

## 5. Strumenti

Regole comuni della specifica precedente: testi in italiano; input non valido → errore dello strumento (`ToolError`), mai un successo con dentro un messaggio d'errore; logica in funzioni pure in un modulo proprio (`lab_server/catalog.py`, *scelta di Claude*) che sollevano `ValueError`, convertite in `ToolError` da `server.py`.

Le due descrizioni devono essere chiaramente distinguibili: la ricerca serve quando non si conosce il codice e restituisce un elenco breve; il dettaglio serve quando si conosce il codice e restituisce tutte le informazioni di un solo linguaggio.

### 5.1 Ricerca — `search_catalog(query, max_results=5)`

**Confronto (scelta di Claude):**
- `query` e i campi `code`, `name`, `year`, `authors`, `paradigms`, `description` vengono ridotti a parole: minuscole, accenti tolti, separazione sui caratteri non alfanumerici ma conservando `+` e `#` dentro le parole (così `C++` e `C#` restano riconoscibili).
- Dalla query si tolgono le **parole vuote** (un elenco breve: articoli, preposizioni e parole come «linguaggio», «linguaggi», «programmazione»). L'elenco esatto è lasciato al piano.
- Un linguaggio corrisponde se **almeno una** parola della query coincide con **una parola intera** di quei campi (non sottostringhe: altrimenti «c» troverebbe tutto). Nessuna gestione di plurali o radici: la descrizione del tool chiede al modello poche parole chiave al singolare (es. `funzionale`, `Haskell`, `Bell Labs`), come la calcolatrice chiede di riscrivere le equazioni.
- Ordine: per numero di parole distinte della query trovate (decrescente), a parità per nome.

**Limite (concordato con l'utente):** `max_results` intero da 1 a 20, predefinito 5, limiti visibili nello schema. Il risultato dichiara **sempre** il totale e quanti sono mostrati.

**Risultato:** una riga per linguaggio con codice, nome e anno. Esempio:
```
Trovati 8 linguaggi per "funzionale", mostrati 5:
- HS: Haskell (1990)
- ...
Usa get_item con il codice per i dettagli.
```
Testo esatto lasciato al piano. Se il totale supera quelli mostrati, il testo lo rende evidente (il modello può ripetere la ricerca con `max_results` più alto).

**Nessun risultato:** risultato normale, **non** un errore (slide 28: «lista vuota dichiarata»), per esempio `Nessun linguaggio corrisponde a "cobra".`

**Errori:**
- `query` vuota o fatta solo di parole vuote → indica di usare almeno una parola chiave;
- `max_results` fuori da 1–20 o non intero → errore di validazione (tradotto in italiano dal middleware esistente).

### 5.2 Dettaglio — `get_item(code)`

- `code` senza distinzione di maiuscole e con spazi ai bordi ignorati (`py` = `PY`, *scelta di Claude*).
- Risultato: tutti i campi in testo leggibile (nome e codice, anno, autori, paradigmi, tipizzazione, descrizione).
- **Errori:** codice vuoto; codice inesistente → `Codice "XYZ" non presente nel catalogo: usa search_catalog per trovare il codice.` (è un errore, a differenza della ricerca vuota: si chiede un elemento preciso che non esiste).

## 6. Istruzioni di sistema

Aggiunta alle istruzioni attuali (testo esatto al piano): per domande sui linguaggi di programmazione usare `search_catalog` con poche parole chiave al singolare quando non si conosce il codice, poi `get_item` con il codice trovato; rispondere solo con i dati restituiti dagli strumenti e dire quando un dato non è presente nel catalogo; se la ricerca dice che i risultati sono troncati e servono tutti, ripeterla con `max_results` più alto.

`MAX_STEPS` resta 5: la sequenza ricerca → dettaglio → risposta ne usa 3.

## 7. Log, Docker, dipendenze

- **Log**: nessuna novità. Le righe esistenti `[strumento] <tool> call_id=... argomenti=... esito=...` bastano a vedere quale tool sceglie il modello e in che ordine (slide 28).
- **Docker**: `catalog.json` sta nel pacchetto `lab_server/`, già copiato dal `Dockerfile` (come `holidays.json`). Va verificato con la prova reale.
- **Dipendenze**: nessuna nuova (`json`, `unicodedata`, `re` della libreria standard).
- **Configurazione**: nessuna nuova variabile d'ambiente.

## 8. Test e verifiche

### Test automatici (senza modello)
- **Dati**: forma del file (sez. 4).
- **Logica** (funzioni pure): ricerca per nome, per autore (`Ritchie`), per paradigma (`funzionale`), per codice (`C` trova C e non tutti i linguaggi con una «c»), con `C++`/`C#`; maiuscole e accenti ignorati; parole vuote ignorate; ordine; nessun risultato; troncamento con totale dichiarato; query vuota o di sole parole vuote → errore; `max_results` ai limiti. Dettaglio con codice maiuscolo, minuscolo, con spazi; codice inesistente e vuoto → errore.
- **Server MCP** (client FastMCP in memoria, come i test esistenti): il catalogo MCP contiene i 9 tool; lo schema di `search_catalog` mostra i limiti di `max_results`; invocazione diretta con input noto; `get_item` con codice inesistente → errore MCP; `max_results=0` → errore.
- **Grafo** con il modello finto: due turni del modello, prima `search_catalog` poi `get_item`, con i `ToolMessage` correlati per `tool_call_id` e la risposta finale; il limite di passaggi resta rispettato.
- **Istruzioni**: il prompt cita i due tool.

### Verifica diretta
`python -m lab_server.check search_catalog query=funzionale` e `python -m lab_server.check get_item code=PY`, più un caso d'errore (`get_item code=XYZ`), eseguiti in PowerShell e documentati nel README.

### Prova reale con LM Studio (dell'utente, in locale e con Docker)
- «Chi ha creato Haskell?» → nei log `search_catalog` poi `get_item` (oppure solo `get_item` se il modello indovina il codice: si registra cosa succede);
- «Quali linguaggi funzionali ci sono nel catalogo?» → solo la ricerca;
- «Quali linguaggi funzionali sono nati prima del 1980?» → ricerca e filtro del modello sugli anni;
- una ricerca senza risultati (per esempio «c'è Brainfuck nel catalogo?») → risposta che dichiara l'assenza, senza inventare;
- «Dimmi tutto sul linguaggio con codice XYZ» → errore spiegato all'utente;
- continuità: memoria fra due domande, `clear`.

Se il modello sceglie lo strumento sbagliato o inventa, si registra il punto esatto nel README e non si dichiara completata quella prova.

## 9. Ordine di lavoro e branch

Branch `feature/catalogo` da `developer`; a fine lavoro verificato, merge `--no-ff` in `developer`, push di `developer`, eliminazione del branch. Pezzi piccoli, ciascuno con test e commit (Conventional Commits in italiano). Ordine indicativo (dettaglio al piano):
1. file `catalog.json` (mostrato all'utente per l'approvazione) e test della sua forma;
2. funzioni pure di ricerca e dettaglio;
3. tool nel server e istruzioni di sistema;
4. documentazione (README, `CLAUDE.md`: struttura, comandi di verifica, confini aggiornati — catalogo fatto, note e meteo da fare) e prova reale.

## 10. Scelte fatte da Claude (da rivedere)

- JSON invece di CSV; file `lab_server/catalog.json` e modulo `lab_server/catalog.py`.
- I 20 linguaggi, i loro codici e il vocabolario dei paradigmi; `typing` solo `statica`/`dinamica`.
- Confronto per parole intere, minuscole e senza accenti, con `+` e `#` conservati; almeno una parola deve coincidere; ordine per parole trovate e poi per nome.
- Parole vuote tolte dalla query; plurali affidati al modello tramite la descrizione del tool.
- `get_item` insensibile a maiuscole e spazi.
- Testi in italiano.

## 11. Lasciato al piano

- Testi esatti di risultati, errori, descrizioni dei tool e istruzioni di sistema.
- Elenco delle parole vuote.
- Suddivisione esatta dei passi e dei commit.
