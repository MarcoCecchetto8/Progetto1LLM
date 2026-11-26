# Router dell'ambito (lezione 6, step 1) — specifica

Data: 2026-11-16 · Stato: approvata dall'utente il 2026-11-16

Riferimenti: lezione 6, slide 3–4 (step 1 · Router) e 19 (evidenza minima: «domanda fuori ambito rifiutata senza passare dall'agente»). Specifiche precedenti valide per tutto ciò che qui non cambia, in particolare `2026-11-16-streaming-design.md` (vista del turno) e `2026-11-09-note-fastapi-design.md` 5.4 (avviso sui falsi successi).

## 1. Intento

L'assistente ha un **ambito dichiarato**. Un nodo LLM messo prima dell'agente decide se la domanda rientra nell'ambito: se sì passa all'agente, che come oggi sceglie da solo gli strumenti; se no l'utente riceve un rifiuto e l'agente non viene eseguito. È il primo dei tre step «un secondo nodo LLM» della lezione 6: lo stesso modello usato con un prompt di sistema diverso.

## 2. Che cosa è stato verificato (2026-11-16, sonde nello scratchpad, `google/gemma-4-e2b` in LM Studio)

- **Output strutturato**: con `response_format` `json_schema` (campi `categoria` ∈ {`conversazione`, `fuori_ambito`} e `motivo`) il modello restituisce sempre un JSON valido. Anche `ChatOpenAI.with_structured_output(..., method="json_schema")` funziona.
- **Ragionamento spegnibile per una singola richiesta**: il parametro `reasoning_effort: "none"` (API diretta) porta i pezzi di ragionamento da 92 a 0; le altre varianti provate (`reasoning_effort: "low"`, `chat_template_kwargs`, `reasoning.effort`) sono ignorate. Da verificare al piano che `ChatOpenAI` lo invii davvero (in una sonda con LangChain i tempi non sono scesi).
- **Accuratezza su 9 domande** (Roma, carbonara, «ciao, chi sei?», «e a Tokyo?» dopo Roma, mondiale 2006, rete neurale, «Ricordami di comprare il latte», abitanti di Parigi, «Quali strumenti hai?»):
  - solo descrizione dell'ambito: **6/9** con e senza ragionamento; gli errori sono quasi tutti **rifiuti ingiusti** («Che ore sono a Roma?» rifiutata perché «non posso fornire l'ora in tempo reale», il promemoria del latte, la rete neurale con un motivo che la dice in ambito, una volta il saluto);
  - descrizione + regola «non devi saper rispondere tu» + **9 esempi**: **9/9** senza ragionamento.
- **Tempo**: circa **23 s di media per decisione** (da 6 a 30 s) su questo computer, anche senza ragionamento; buona parte va nella lettura delle istruzioni. Ogni domanda costa quindi un'attesa in più prima che l'agente parta. Limite dichiarato, non un obiettivo da risolvere qui.

## 3. Obiettivi

- L'**ambito** è descritto in un file di configurazione, non nel codice.
- Un **nodo router** prima dell'agente, con output strutturato `categoria` e `motivo`.
- Arco condizionale: `conversazione` → agente; `fuori_ambito` → nodo di rifiuto → fine.
- Il router **non** valuta gli strumenti: se servono lo decide l'agente, come prima.
- Evidenze (slide 4): log con categoria, motivo e passaggio all'agente; per le domande fuori ambito rifiuto e nessuna esecuzione del nodo agente nei log; test con risposte del router simulate per entrambi i percorsi.

## 4. Ambito (scelte dell'utente)

**In ambito (`conversazione`)**: strumenti del laboratorio (ora e data, conversioni, calcoli, date e giorni mancanti, festività), catalogo dei linguaggi, note e promemoria, informatica, programmazione, intelligenza artificiale; **saluti e cortesia**; **domande sull'assistente** (chi è, cosa sa fare, quali strumenti ha, come funziona); domande che continuano un discorso in ambito.

**Fuori ambito**: tutto il resto (cucina, sport, geografia, storia, attualità…).

## 5. Comportamento

### 5.1 Configurazione dell'ambito

- File di testo **`config/ambito.txt`** nel progetto (*scelta di Claude*), versionato: descrizione dell'ambito e **esempi** di domande con la categoria attesa, come nella sonda che ha dato 9/9. Modificandolo cambia il comportamento del router senza toccare il codice.
- Variabile **`SCOPE_FILE`** nel `.env` per usare un altro file (predefinito `config/ambito.txt`, relativo alla radice del progetto).
- File mancante o vuoto → errore di configurazione chiaro all'avvio, uscita con codice 1, come le altre variabili non valide.
- Il prompt del router è composto da una parte fissa nel codice (ruolo: «non rispondi alla domanda, decidi solo se rientra nell'ambito»; «non devi saper rispondere tu: anche se servono strumenti o dati in tempo reale, se l'argomento è in ambito la categoria è conversazione»; formato del motivo) più il contenuto del file. Testo esatto al piano.
- Docker: il file è copiato nell'immagine (o montato); nessuna differenza di comportamento.

### 5.2 Grafo

```
START → router ─ conversazione ─→ model ⇄ tools → (answer_check) → END
           └──── fuori_ambito ──→ refusal → END
```

- Il router è **facoltativo** in `build_graph` (come `answer_check`): senza router il grafo è quello di oggi, quindi i test esistenti non cambiano. L'applicazione lo attiva sempre.
- Il router riceve la domanda e **gli ultimi messaggi della conversazione** (solo testo di utente e assistente, senza chiamate e risultati degli strumenti; numero esatto al piano), così «e a Tokyo?» dopo una domanda sull'ora resta in ambito (*scelta di Claude*).
- Il router usa lo stesso modello con **ragionamento spento** (`reasoning_effort: "none"`) e `json_schema`; non conta nel limite di passaggi (`MAX_STEPS`) dell'agente.
- Il router non aggiunge messaggi alla cronologia: la sua decisione sta nello stato del turno e nei log.

### 5.3 Rifiuto (scelta dell'utente: messaggio fisso con il motivo)

- Testo: `Posso aiutarti solo con gli strumenti del laboratorio, i linguaggi di programmazione, l'informatica e l'intelligenza artificiale. Motivo: <motivo del router>` (testo esatto al piano).
- La domanda e il rifiuto entrano nella cronologia come un turno normale (*scelta di Claude*): la conversazione resta coerente.
- Nessuna chiamata al nodo `model` e nessuno strumento per quel turno.

### 5.4 Log e terminale

- Ogni decisione: riga `INFO` `[router] categoria=<categoria> motivo=<motivo>` e, se in ambito, `→ agente`; se fuori ambito, `→ rifiuto` (testo esatto al piano). Visibile con il livello di log predefinito.
- In streaming i pezzi generati dal router **non** compaiono come risposta né come ragionamento; il rifiuto si stampa come riga finale del turno (come il messaggio di limite di passaggi).

### 5.5 Errori

- Risposta del router non valida (JSON non conforme, categoria sconosciuta): la domanda **passa all'agente** e il log registra un `WARNING` con il dettaglio (*scelta di Claude*: un guasto del router non deve bloccare l'assistente).
- LM Studio non raggiungibile o timeout durante il router: stessi messaggi d'errore di oggi (il turno non entra in cronologia).
- Ctrl+C durante il router: come durante il modello («Risposta interrotta.»).

## 6. Test e verifiche

### Test automatici (senza LM Studio)
- **Grafo** con router simulato (una funzione che restituisce categoria e motivo fissi) e modello finto:
  - `conversazione` → il nodo `model` viene eseguito, risposta dell'agente, log con categoria, motivo e `→ agente`;
  - `fuori_ambito` → rifiuto con il motivo, il modello finto **non** viene chiamato (nessun messaggio consumato), log con `→ rifiuto`, nessuna riga del nodo agente;
  - router che solleva un errore di output non valido → passa all'agente, `WARNING` nel log;
  - grafo senza router → comportamento identico a oggi.
- **Contesto**: il router riceve gli ultimi messaggi di testo, senza `ToolMessage` né chiamate.
- **Configurazione**: `SCOPE_FILE` assente (predefinito), file esistente, file mancante o vuoto (errore chiaro).
- **Streaming**: il rifiuto compare una volta come riga finale; i pezzi del router non compaiono.
- **Prompt del router**: contiene il testo del file dell'ambito e la parte fissa.
- Restano verdi tutti i test esistenti.

### Prova reale con LM Studio
- Le 9 domande della sonda più almeno 3 nuove (non presenti fra gli esempi del file), con l'esito di ciascuna e il tempo medio del router; i rifiuti ingiusti si registrano come limite del modello.
- Domanda in ambito: log con categoria, motivo e passaggio all'agente. Domanda fuori ambito: rifiuto, nessuna riga del nodo agente nei log.
- Modifica di `config/ambito.txt` (per esempio togliere «note») e nuova sessione: il comportamento cambia senza toccare il codice.
- Docker (`docker compose run --rm -T app` con input da pipe): stesso comportamento.

Esiti nel README.

## 7. Ordine di lavoro e branch

Branch `feature/router` da `developer`; merge `--no-ff` in `developer` dopo la prova reale e l'ok dell'utente, push di `developer`, eliminazione del branch. Pezzi piccoli con test e commit. README (configurazione, ambito, rifiuto, log, limiti con i numeri misurati) e `CLAUDE.md` (struttura: nodo router, `config/`) aggiornati.

## 8. Scelte fatte da Claude (da rivedere)

- File `config/ambito.txt` con descrizione ed esempi; variabile `SCOPE_FILE`.
- Router con gli ultimi messaggi di testo della conversazione.
- Router con ragionamento spento e `json_schema`; fuori dal conteggio di `MAX_STEPS`.
- Domanda e rifiuto in cronologia.
- Output non valido del router → passa all'agente con `WARNING`.
- Righe `[router]` a livello `INFO`.

## 9. Lasciato al piano

- Testo esatto della parte fissa del prompt, del rifiuto e delle righe di log; contenuto iniziale di `config/ambito.txt` (partendo da quello della sonda).
- Numero di messaggi passati al router.
- Come passare `reasoning_effort` attraverso `ChatOpenAI` e come verificarlo.
- Forma del router facoltativo in `build_graph` e dell'oggetto con categoria e motivo.
