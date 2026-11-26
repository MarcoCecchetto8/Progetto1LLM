# Revisore della risposta (lezione 6, step 2) — specifica

Data: 2026-11-16 · Stato: approvata dall'utente il 2026-11-16

Riferimenti: lezione 6, slide 5 (step 2 · Revisore), 18 (revisore con lo streaming: «scegliere se mostrare la bozza mentre viene scritta oppure solo la risposta approvata, e documentare la scelta») e 19 (evidenza minima: «risposta incompleta corretta dopo la revisione, entro il limite»). Specifiche precedenti valide per tutto ciò che qui non cambia: `2026-11-16-router-design.md`, `2026-11-16-streaming-design.md`, `2026-11-09-note-fastapi-design.md` 5.4.

## 1. Intento

Dopo la risposta dell'agente, un secondo LLM verifica che risponda davvero alla domanda dell'utente: tutte le parti richieste, nessuna deviazione dal tema. Una risposta incompleta o fuori tema torna all'agente con il motivo, finché non è coerente o si raggiunge il limite. È il secondo dei tre step «un secondo nodo LLM»: lo stesso modello con un prompt di sistema diverso, come il router.

## 2. Che cosa è stato verificato (2026-11-16, sonde nello scratchpad, `google/gemma-4-e2b`)

- **Giudizio del revisore**: con `json_schema` (`coerente` booleano, `motivo`), `reasoning_effort: "none"` e un prompt che chiede di controllare solo la copertura delle parti della domanda (non i fatti): **6/6** corretti su 3 risposte complete (domanda in due parti completa, saluto, conversione) e 3 incomplete o fuori tema (domanda in due parti a metà, «Chi ha creato Python?» con una risposta che parla d'altro, «salva la nota e dimmi che note ho» con solo il salvataggio). Motivi chiari, per esempio «La risposta non ha fornito il calcolo richiesto.».
- **Tempo**: circa **23 s** per giudizio su questo computer (da 19 a 26 s).
- **Correzione da parte dell'agente** dopo l'indicazione del revisore (grafo vero con gli strumenti MCP; cronologia: domanda in due parti, bozza «A Tokyo sono le 19:03.», indicazione come messaggio utente marcato `[Revisore] …`): **3/3** risposte completate («A Tokyo sono le 19:03. Il 15% di 80 è 12.»). In tutte e 3 il modello ha fatto il calcolo **senza chiamare `calculate`**, nonostante il prompt di sistema chieda di usare gli strumenti per i calcoli: limite del modello da registrare, il revisore controlla la coerenza e non come è stato ottenuto il dato.

## 3. Obiettivi

- Nodo **revisore** che riceve la domanda dell'utente e la risposta proposta dall'agente; output strutturato `coerente` (sì/no) e `motivo`.
- Se non coerente, il motivo entra nella conversazione come **indicazione per l'agente**, che risponde di nuovo.
- **Limite di revisioni** nello stato: al limite si restituisce l'ultima risposta e lo si segnala nei log.
- Evidenze (slide 5): domanda in due parti con risposta parziale → rifiuto motivato e nuova risposta completa; risposta coerente approvata al primo passaggio; limite rispettato con un revisore simulato che rifiuta sempre.

## 4. Scelte dell'utente

- **Streaming (slide 18)**: si **mostra tutto** mentre accade. Ogni risposta dell'agente, bozze comprese, scorre come oggi; sotto compare la riga del revisore. La scelta va documentata nel README.
- **Limite**: **3 revisioni** al massimo (quindi al massimo 4 risposte dell'agente), regolabile con **`MAX_REVIEWS`** nel `.env` (intero ≥ 0; con 0 il revisore giudica una volta ma non rimanda mai indietro, vedi 5.2).

## 5. Comportamento

### 5.1 Grafo

```
START → router ─ conversazione → model ⇄ tools
                                   │ (risposta senza chiamate)
                                   ▼
                               reviewer ─ coerente / limite / output non valido ─→ (answer_check) → END
                                   └─ non coerente, sotto il limite → feedback → model
```

- Il revisore è **facoltativo** in `build_graph` (come router e `answer_check`): senza, il grafo è quello di oggi.
- Il revisore interviene solo su una **risposta finale** del modello (senza chiamate, contenuto testuale non vuoto). Non interviene sul rifiuto del router, sul messaggio di limite di passaggi, né su una risposta vuota (che resta gestita da `EMPTY_ANSWER`).
- L'**avviso sui falsi successi** (`answer_check`) si applica alla risposta finale, **dopo** il revisore.
- Ogni nuovo tentativo dell'agente ha un proprio budget di `MAX_STEPS` (il contatore dei passaggi riparte dopo un'indicazione del revisore): il numero totale di tentativi è già limitato da `MAX_REVIEWS` (*scelta di Claude*, per evitare che una revisione faccia scattare il limite di passaggi e cancelli il turno).

### 5.2 Il revisore

- Riceve: la **domanda originale** dell'utente del turno e la **risposta proposta** (non i risultati degli strumenti: controlla la coerenza, non la correttezza dei dati) (*scelta di Claude*).
- Stesso modello dell'agente, **ragionamento spento** (`reasoning_effort: "none"`), output `json_schema` con `coerente: bool` e `motivo: str`. Testo esatto del prompt al piano, partendo da quello della sonda (6/6).
- Contatore delle revisioni nello stato del turno. Con `coerente = false` e contatore < `MAX_REVIEWS`: indicazione all'agente e nuovo tentativo; al limite: si tiene l'ultima risposta. Con `MAX_REVIEWS = 0` il revisore giudica e registra il verdetto ma non rimanda mai indietro.
- **Output non valido** del revisore (JSON non conforme): risposta approvata, `WARNING` nel log (*scelta di Claude*, come il router). Errori di collegamento con LM Studio: come oggi.

### 5.3 Indicazione all'agente

- Un messaggio nella conversazione con il motivo, per esempio `[Revisore] La risposta non è completa: <motivo>. Rispondi di nuovo alla domanda dell'utente, in modo completo, usando gli strumenti se servono.` (testo esatto al piano; tipo di messaggio al piano, verificato con il modello vero: un messaggio di sistema a metà conversazione è stato ignorato da gemma nella misura delle note, un messaggio utente no).
- **Vincolo**: il codice che oggi cerca «l'ultima domanda dell'utente» (pulizia del limite di passaggi in `graph.py`, inizio del turno in `check_note_claims`, domanda passata al revisore) deve continuare a trovare la **domanda vera**, non l'indicazione del revisore. Se l'indicazione è un messaggio utente, va marcata e quelle funzioni la saltano.

### 5.4 Cronologia

Alla fine del turno, nella cronologia **non restano** le bozze bocciate né le indicazioni del revisore: restano la domanda, le chiamate agli strumenti con i loro risultati (come oggi) e la risposta finale (*scelta di Claude*: il contesto del modello è limitato e le bozze non servono ai turni successivi).

### 5.5 Terminale e log

- Righe del revisore nel terminale, dopo la risposta a cui si riferiscono (testo esatto al piano):
  - `[revisore] coerente`
  - `[revisore] non coerente: <motivo> → nuova risposta`
  - `[revisore] limite raggiunto (<n> revisioni): resta l'ultima risposta`
- La nuova risposta scorre su una riga nuova sotto la riga del revisore. I pezzi generati dal revisore non compaiono.
- Log `INFO` per ogni verdetto (`[revisore] coerente=… motivo=… revisione n/MAX`), `INFO` al limite, `WARNING` per l'output non valido.

## 6. Test e verifiche

### Test automatici (senza LM Studio)
Con un revisore simulato (funzione che restituisce verdetti in sequenza) e il modello finto:
- risposta coerente al primo passaggio → un solo giudizio, risposta invariata, riga `[revisore] coerente`;
- domanda in due parti, prima risposta parziale bocciata, seconda completa → due giudizi, l'agente riceve l'indicazione con il motivo, la cronologia finale contiene solo la risposta completa (niente bozza, niente indicazione);
- revisore che rifiuta sempre → si ferma dopo `MAX_REVIEWS` revisioni, log del limite, resta l'ultima risposta;
- `MAX_REVIEWS = 0` → un giudizio, nessun nuovo tentativo;
- output non valido del revisore → approvata con `WARNING`;
- il revisore non interviene su rifiuto del router, limite di passaggi, risposta vuota;
- dopo un'indicazione il contatore dei passaggi riparte; il limite di passaggi dentro un tentativo continua a pulire il turno partendo dalla domanda vera;
- falso successo nella risposta finale dopo una revisione → avviso come oggi (e `add_note` riuscito in un tentativo precedente dello stesso turno vale come conferma);
- streaming: bozza, riga del revisore, nuova risposta, ciascuna una volta; pezzi del revisore assenti;
- configurazione: `MAX_REVIEWS` assente (3), valido, negativo o non intero (errore chiaro);
- grafo senza revisore → comportamento identico a oggi. Restano verdi tutti i test esistenti.

### Prova reale con LM Studio
- «Che ore sono a Tokyo e quanto fa il 15% di 80?» (domanda in due parti): se la prima risposta è parziale, rifiuto motivato e nuova risposta completa; se è completa al primo colpo, si registra e si ripete con un'altra domanda in due parti.
- Una domanda semplice: approvata al primo passaggio.
- Tempi del revisore; numero di revisioni usate.
- Docker via pipe: stesso comportamento.

Esiti nel README, insieme alla scelta di streaming (slide 18).

## 7. Ordine di lavoro e branch

Branch `feature/revisore` da `developer`; merge `--no-ff` dopo la prova reale e l'ok dell'utente, push, eliminazione del branch. README e `CLAUDE.md` aggiornati (nodo revisore, `MAX_REVIEWS`, scelta di streaming).

## 8. Scelte fatte da Claude (da rivedere)

- Revisore che vede solo domanda e risposta (coerenza, non correttezza).
- Revisore su ogni risposta finale, saluti compresi; non su rifiuto, limite di passaggi, risposta vuota.
- Ragionamento spento e `json_schema`, come il router; output non valido → approvata con `WARNING`.
- Budget di passaggi che riparte a ogni tentativo.
- Cronologia senza bozze né indicazioni.
- Avviso dei falsi successi dopo il revisore.

## 9. Lasciato al piano

- Testo esatto del prompt del revisore, dell'indicazione all'agente e delle righe di terminale e log.
- Tipo e marcatura del messaggio di indicazione; come le funzioni dell'«ultima domanda» lo saltano.
- Forma del revisore facoltativo in `build_graph`, dei campi di stato e della pulizia della cronologia a fine turno.
