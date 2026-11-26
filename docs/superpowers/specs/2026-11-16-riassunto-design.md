# Riassunto della cronologia (lezione 6, step 3) — specifica

Data: 2026-11-16 · Stato: approvata dall'utente il 2026-11-16; revisione 5.7 approvata il 2026-11-17; revisione 5.8 approvata il 2026-11-17; revisione 5.9 decisa da Claude in autonomia e confermata dall'utente il 2026-11-17

Riferimenti: lezione 6, slide 3 (grafo dei tre step: «Riassunto» tra START e router) e 6 (step 3 · Riassunto della cronologia). Specifiche precedenti valide per tutto ciò che qui non cambia: `2026-11-16-revisore-design.md`, `2026-11-16-router-design.md`, `2026-11-16-streaming-design.md`, `2026-11-09-note-fastapi-design.md`.

## 1. Intento

Con un modello locale il contesto è limitato e ogni turno aggiunge messaggi. Un nodo LLM all'inizio del turno sostituisce i messaggi più vecchi con un riassunto e lascia intatti gli ultimi turni. Così la conversazione resta utilizzabile su molti turni senza il messaggio «Il contesto del modello è pieno: usa 'clear'» e senza perdere le informazioni importanti. È il terzo dei tre step «un secondo nodo LLM»: lo stesso modello con un prompt diverso, come router e revisore.

## 2. Che cosa è stato verificato (2026-11-16, LM Studio e sonde nello scratchpad, `google/gemma-4-e2b`)

- **Contesto caricato**: `GET /api/v0/models/google/gemma-4-e2b` → `loaded_context_length` **8192** (massimo del modello 131072).
- **Parte fissa del prompt** (stima caratteri ÷ 4): prompt di sistema 2722 caratteri ≈ **680 token**; schemi dei 12 strumenti (9 MCP + 3 note) 5462 caratteri ≈ **1365 token**. Quindi ≈ 2050 token sono occupati prima di qualsiasi messaggio.
- **Primo riassunto** (ragionamento spento, prompt in prosa che chiede di conservare nome, fuso orario o città, ID e testo delle note, argomenti principali; conversazione con nome, città, due note salvate, Python): **5/5** conservano tutto. Tempo 8–14 s.
- **Riassunto aggiornato** (riassunto precedente con un argomento, Rust, e la nota 3, più nuovi messaggi):
  - riassunto precedente passato a parte, prima della conversazione: perde nota 3 e Rust (2/2);
  - riassunto precedente **in cima alla conversazione** come «Riassunto delle parti precedenti», con la frase «riporta TUTTE le sue informazioni (nomi, note, argomenti) e aggiungi quelle nuove»: **nota 3 conservata 3/3, Rust perso 3/3**;
  - formato a quattro righe fisse (nome, città, note, argomenti): nota 3 2/3, Rust 0/3.
- **Limite accettato dall'utente**: con gemma, nome, città e ID delle note sopravvivono ai riassunti successivi; gli argomenti più vecchi tendono a sparire al secondo riassunto. Si registra come limite del modello nel README.

## 3. Obiettivi (slide 6)

- **Soglia configurabile**, in stima dei token, oltre la quale si riassume.
- **Nodo riassunto all'inizio del turno**: comprime i messaggi vecchi e conserva gli ultimi N turni.
- Il riassunto è **un campo dello stato** che viene sostituito a ogni nuovo riassunto, non accumulato.
- Il taglio **non separa mai** una chiamata a uno strumento dal relativo `ToolMessage`.
- Evidenze: log con numero di messaggi prima e dopo; un'informazione data al primo turno (il nome) usata dopo la compressione; sotto la soglia il nodo non chiama il modello.

## 4. Scelte dell'utente

- **Soglia in stima dei token**, non in numero di messaggi (il problema reale è il limite di 8192).
- **Cosa conservare**: nome dell'utente, fuso orario o città, ID delle note (con il testo), argomenti principali della chat.
- **Turni intatti**: gli ultimi **2**, configurabile.
- **Terminale**: una riga con messaggi e token prima e dopo, **più il testo del riassunto**.
- **Limite accettato**: perdita degli argomenti più vecchi ai riassunti successivi (sezione 2).

## 5. Comportamento

### 5.1 Grafo

```
START → summarizer → router → (model ⇄ tools → reviewer → …) come oggi
```

- Il nodo riassunto è **facoltativo** in `build_graph` (come router, revisore e `answer_check`): senza, il grafo è quello di oggi. Con il router assente, `summarizer → model`.
- Il nodo gira **una volta per turno**, all'inizio, prima del router. Non gira di nuovo durante i tentativi del revisore.

### 5.2 Quando si riassume

- **Stima dei token**: somma dei caratteri del contenuto testuale di tutti i messaggi dello stato (prompt di sistema compreso) più il riassunto in vigore, divisa per 4 (`len // 4`). Le chiamate agli strumenti contano con nome e argomenti serializzati. Nessuna nuova dipendenza (*scelta di Claude*).
- **Soglia**: `SUMMARY_THRESHOLD` nel `.env`, intero ≥ 1, default **4000** token stimati (*scelta di Claude*: con ≈ 1365 token di schemi degli strumenti, che non sono messaggi, restano più di 2500 token per ragionamento e risposta entro 8192).
- **Turni intatti**: `SUMMARY_KEEP_TURNS` nel `.env`, intero ≥ 1, default **2**.
- Un **turno** inizia con una domanda vera dell'utente (`HumanMessage` non marcato come indicazione del revisore; a fine turno le indicazioni sono comunque già tolte) e comprende tutto fino alla domanda successiva: risposta, chiamate e risultati degli strumenti.
- Si conservano intatti: il prompt di sistema (primo messaggio), gli ultimi `SUMMARY_KEEP_TURNS` turni completi **e la domanda del turno corrente**. Si comprime tutto ciò che sta tra il prompt di sistema e il primo turno conservato.
- Il taglio cade **sempre all'inizio di un turno**: così una chiamata a uno strumento e il suo `ToolMessage` restano dalla stessa parte.
- **Sotto la soglia**, o se non c'è niente da comprimere (turni precedenti ≤ `SUMMARY_KEEP_TURNS`), il nodo **non chiama il modello** e non cambia lo stato.

### 5.3 Il riassunto

- Stesso modello dell'agente, **ragionamento spento** (`reasoning_effort: "none"`), uscita testuale semplice (non strutturata).
- Istruzioni: quelle della sonda migliore (sezione 2). Il testo esatto è nel piano. Chiedono un riassunto in italiano di al massimo 120 parole che conservi nome, fuso orario o città, ID e testo delle note, argomenti principali. Se la conversazione inizia con un riassunto delle parti precedenti, il modello ne riporta tutte le informazioni e aggiunge quelle nuove. Il risultato contiene solo il riassunto, senza introduzioni.
- Ingresso: un unico messaggio utente con `Conversazione da riassumere:`, poi, se esiste, `Riassunto delle parti precedenti: <riassunto in vigore>`, poi i messaggi da comprimere trascritti una riga per messaggio:
  - `Utente: …`;
  - `Assistente: …`, solo quando il messaggio contiene testo;
  - `Strumento <nome>: …` per ogni `ToolMessage`.
- **Uscita**: il testo, ripulito degli spazi agli estremi, **sostituisce** il campo `summary` dello stato. I messaggi compressi si tolgono dalla cronologia con `RemoveMessage`.
- **Errore o testo vuoto**: la cronologia e il riassunto restano com'erano, si scrive un `WARNING` nel log e il turno prosegue normalmente (scelta concordata con l'utente). Gli errori da gestire sono quelli di LM Studio (`openai.APIError`, che comprende timeout e collegamento). Un Ctrl+C (`TurnCancelled`) interrompe il turno come oggi.

### 5.4 Come l'agente usa il riassunto

- `model_node`, quando nello stato c'è un riassunto, invia al modello la cronologia con il **primo messaggio di sistema esteso**: `<prompt di sistema>\n\nRiassunto della conversazione precedente:\n<riassunto>`. Il riassunto sta in cima, dove gemma lo considera. Un messaggio di sistema a metà conversazione era stato ignorato nelle misure delle note. L'estensione vale solo per la chiamata e non viene salvata nella cronologia (*scelta di Claude*).
- ~~Router e revisore restano invariati.~~ **Revisione del 2026-11-17** (vedi 5.7): anche router e revisore ricevono il riassunto.

### 5.7 Router e revisore con il riassunto (revisione del 2026-11-17)

**Perché.** Nella prova reale con soglia 900 il revisore ha bocciato due volte «di cosa abbiamo parlato?» («non c'è stato un argomento precedente»): riceve solo domanda e risposta, non vede né il riassunto né i turni precedenti. Il router dopo un riassunto non vede più la presentazione dell'utente.

**Misure** (sonde reali, `google/gemma-4-e2b`, 3 ripetizioni per caso):
- Revisore, 3 casi («di cosa abbiamo parlato?» con risposta corretta; «come mi chiamo e dove vivo?» con risposta corretta; una domanda in due parti con risposta incompleta, da bocciare):
  - solo domanda e risposta (oggi): **4/9** giudizi giusti;
  - con il riassunto: **6/9** (boccia «di cosa abbiamo parlato?» perché Rust, dei turni recenti, non è nel riassunto); un'intestazione che spiega che gli ultimi turni non sono riassunti non cambia nulla (6/9);
  - con il riassunto **e gli ultimi messaggi di testo**: **9/9**, 23–34 s per giudizio.
- Router, «dove vivo?»: 0/3 senza la presentazione nel contesto, anche con l'esempio «Dove vivo?» in `config/ambito.txt` (esempio poi tolto); 3/3 se «mi chiamo Marco e vivo a Roma» è fra gli ultimi messaggi. Con il riassunto in fondo al prompt di sistema: «dove vivo?» 0/3, «come mi chiamo e dove vivo?» 3/3 (senza riassunto 2/3), fuori ambito 9/9 rifiutati. Nessun beneficio misurato su «dove vivo?»: la modifica si fa per scelta dell'utente (contesto coerente con l'agente), e «dove vivo?» da sola dopo un riassunto resta un limite del modello.

**Comportamento.**
- **Router**: quando nello stato c'è un riassunto, il prompt di sistema del router diventa `<istruzioni e ambito>\n\nRiassunto della conversazione precedente:\n<riassunto>` (stessa intestazione dell'agente). I messaggi passati restano gli ultimi messaggi di testo come oggi. Senza riassunto il prompt è identico a oggi.
- **Revisore**: la richiesta al revisore diventa, con le parti presenti solo se non vuote:
  ```
  Riassunto della conversazione precedente:
  <riassunto>

  Conversazione recente:
  Utente: …
  Assistente: …

  Domanda dell'utente:
  <domanda>

  Risposta proposta:
  <risposta>
  ```
  La «conversazione recente» sono i messaggi prima della domanda del turno, filtrati con la stessa regola del router (solo domande e risposte di testo, senza traffico degli strumenti, ultimi 6) e scritti come nella trascrizione del riassunto (`Utente:` / `Assistente:`). Le istruzioni del revisore non cambiano (sono quelle usate nelle sonde). Senza riassunto e senza turni precedenti la richiesta è identica a oggi.
- I nodi `router` e `reviewer` del grafo passano il riassunto in vigore (`state["summary"]`, vuoto se assente). Il riassunto non entra nella cronologia, come per l'agente.

**Test** (senza LM Studio): prompt del router con e senza riassunto; richiesta del revisore con e senza riassunto e conversazione recente (strumenti esclusi, indicazioni del revisore escluse, limite di 6 messaggi); il grafo passa il riassunto a router e revisore e la conversazione recente al revisore. Restano verdi tutti i test esistenti.

**Prova reale**: ripetere la sessione con soglia 900 e verificare «di cosa abbiamo parlato?» approvata al primo giudizio; registrare i tempi del revisore.

### 5.8 Risultati degli strumenti al revisore e «l'utente» nel riassunto (revisione del 2026-11-17)

**Perché.** Prova reale dopo 5.7 (locale e Docker, soglia 900):
- «di cosa abbiamo parlato?» approvata al primo giudizio, ma in Docker «quali note ho?» con la risposta corretta di `list_notes` è stata **bocciata 3 volte fino al limite** («le note non sono presenti nella conversazione precedente»): con il contesto il revisore confronta la risposta con la conversazione e non vede i risultati degli strumenti.
- L'agente, con il riassunto «Marco, residente a Roma, ha chiesto…», ha risposto «Non mi hai detto il tuo nome» e «non ho accesso alle tue informazioni personali» (2 su 2).

**Misure** (sonde reali, 3 ripetizioni per caso):
- Revisore con riassunto e conversazione recente: note 0/3, ora di Tokyo 0/3 (anche senza contesto Tokyo 0/3: «non ho accesso a informazioni in tempo reale»). Una regola nelle istruzioni («il contesto serve solo a capire la domanda») non cambia nulla: note 0/3, Tokyo 0/3.
- Revisore con riassunto, conversazione recente **e risultati degli strumenti del turno**: **15/15** (note, Tokyo, «di cosa abbiamo parlato?», nome e città giusti; domanda in due parti incompleta bocciata), 19–31 s per giudizio.
- Agente (prompt di sistema reale, senza strumenti collegati) con «come mi chiamo?»: riassunto in terza persona («Marco, residente a Roma, …») 0/3; intestazione più esplicita 0/3; riassunto che inizia con «L'utente si chiama Marco e vive a Roma.» **3/3**. «dove vivo?» 3/3 in tutti i casi.
- Riassunto con la frase nuova nelle istruzioni: **6/6** iniziano con «L'utente si chiama Marco e vive a Roma» e conservano nota 6 e Python (primo riassunto e successivo), 5–9 s.

**Comportamento.**
- **Revisore**: fra la conversazione recente e la domanda, se nel turno ci sono risultati degli strumenti, la richiesta contiene
  ```
  Risultati degli strumenti in questo turno:
  <nome>: <contenuto>
  ```
  una riga per ogni `ToolMessage` dopo la domanda del turno (compresi quelli dei tentativi precedenti del revisore). Istruzioni del revisore invariate.
- **Riassunto**: nelle istruzioni, prima di «Scrivi solo il riassunto, senza introduzioni.», la frase «Riferisciti all'utente sempre come «l'utente»: se conosci nome o città, inizia con «L'utente si chiama … e vive a …».».

**Test** (senza LM Studio): richiesta del revisore con i risultati degli strumenti (e senza: identica a 5.7); il grafo passa al revisore i risultati del turno corrente e non quelli dei turni precedenti; istruzioni del riassunto con la frase nuova.

**Prova reale**: locale e Docker con soglia 900, con «come mi chiamo?» dopo il riassunto e «quali note ho?».

### 5.9 Intestazione esplicita del riassunto per l'agente (revisione del 2026-11-17, scelta di Claude in autonomia concessa dall'utente)

**Perché.** Prova reale dopo 5.8: note, «di cosa abbiamo parlato?» e ora di Tokyo approvate al primo giudizio in locale e in Docker; «come mi chiamo?» giusta in locale («Mi hai detto che ti chiami Marco.») ma sbagliata in Docker («Non mi hai detto il tuo nome.») con il riassunto «L'utente si chiama Marco e vive a Roma. …».

**Misure** (grafo vero con strumenti MCP e note, riassunto nello stato; le ripetizioni a temperatura uguale tornano identiche, quindi si variano le temperature 0.2/0.5/0.8):
- ultimi turni solo di testo: riassunto in fondo al prompt di sistema 3/3 (con risposte identiche), in testa 0/3;
- ultimi turni con chiamate agli strumenti (come in Docker), intestazione di oggi: **1/6** (due riassunti diversi);
- stessi casi con l'intestazione «Riassunto della conversazione precedente (fa parte di questa conversazione: usalo per rispondere alle domande sull'utente, come nome e città, e su ciò di cui si è parlato):»: **6/6**;
- con la nuova intestazione l'agente usa ancora gli strumenti giusti: ora di Tokyo, Rust, note 6/6; «di cosa abbiamo parlato?» risponde senza strumenti 2/2.

**Comportamento.** Solo l'agente usa la nuova intestazione (`AGENT_SUMMARY_HEADER` in `assistant/summarizer.py`), sempre in fondo al primo messaggio di sistema. Router e revisore restano con «Riassunto della conversazione precedente:», l'intestazione con cui sono stati misurati.

**Test**: `with_summary` e il grafo usano la nuova intestazione; la cronologia salvata resta invariata.

### 5.5 Stato e terminale da un turno all'altro

- Nuovo campo di stato `summary: NotRequired[str]`.
- Il ciclo da terminale (`cli.run`) passa il riassunto in vigore a ogni turno e, a turno riuscito, conserva sia la cronologia sia il riassunto restituiti. Se il turno finisce con un errore o con la risposta vuota, restano entrambi come prima, così come oggi resta la cronologia.
- **`clear`** svuota anche il riassunto.

### 5.6 Terminale e log

- Quando avviene un riassunto, nel terminale prima del router (testo esatto al piano):
  ```
  [riassunto] 24 → 5 messaggi (circa 5200 → 1400 token)
  <testo del riassunto>
  ```
  I conteggi sono quelli dello stato prima e dopo la compressione (messaggi, prompt di sistema compreso; token stimati come in 5.2, riassunto compreso).
- Il testo del riassunto non scorre token per token come risposta dell'assistente: i pezzi generati dal nodo riassunto vanno filtrati come quelli di router e revisore. Si mostra dall'aggiornamento del nodo.
- Log `DEBUG` con gli stessi numeri: lo streaming li mostra già all'utente, come per il revisore. `WARNING` per il riassunto non riuscito. All'avvio, una riga `INFO` con soglia e turni conservati, come `[revisore] limite: …`.

## 6. Test e verifiche

### Test automatici (senza LM Studio)
Con una funzione di riassunto simulata e il modello finto:
- sotto la soglia: la funzione di riassunto **non viene chiamata**, stato invariato;
- sopra la soglia: chiamata una volta; restano prompt di sistema, ultimi `SUMMARY_KEEP_TURNS` turni e domanda corrente; i messaggi compressi sono tolti; `summary` contiene il nuovo testo;
- riassunto già presente: la funzione riceve il riassunto in vigore e il nuovo testo lo **sostituisce**, non si accoda;
- un turno con chiamate e risultati degli strumenti al confine: nessun `ToolMessage` resta senza la sua chiamata e viceversa;
- turni precedenti ≤ `SUMMARY_KEEP_TURNS`: nessuna chiamata anche sopra la soglia;
- trascrizione: righe `Utente:`, `Assistente:`, `Strumento <nome>:`; assistente senza testo saltato;
- errore della funzione (`openai.APIError`) o testo vuoto: cronologia e riassunto invariati, `WARNING`, il turno arriva comunque alla risposta;
- `model_node` riceve il prompt di sistema esteso con il riassunto; la cronologia salvata no;
- stima dei token: caso numerico semplice (caratteri ÷ 4, riassunto compreso);
- `cli.run`: il riassunto passa da un turno al successivo; `clear` lo svuota; turno fallito non lo cambia;
- streaming: riga `[riassunto] …` e testo una volta, prima della risposta; pezzi del nodo riassunto assenti dalla risposta;
- configurazione: `SUMMARY_THRESHOLD` e `SUMMARY_KEEP_TURNS` assenti (default), validi, 0 o negativi, non interi (errore chiaro);
- grafo senza nodo riassunto → comportamento identico a oggi. Restano verdi tutti i test esistenti.

### Prova reale con LM Studio
- Con una soglia bassa nel `.env` (per esempio `SUMMARY_THRESHOLD=1500`): al primo turno «ciao, mi chiamo Marco», poi alcune domande con strumenti e una nota; dopo il riassunto (riga e testo visibili) chiedere «come mi chiamo?» → risposta con il nome.
- Sotto la soglia: nessuna riga `[riassunto]` (il nodo non chiama il modello).
- Tempo del riassunto; secondo riassunto della stessa sessione (registrare che cosa resta).
- Docker via pipe: stesso comportamento.

Esiti nel README, insieme al limite accettato (sezione 2).

## 7. Ordine di lavoro e branch

Branch `feature/riassunto` da `developer`; merge `--no-ff` dopo la prova reale e l'ok dell'utente, push, eliminazione del branch. README (configurazione, nodo riassunto, diagnosi, esiti), `.env.example` e `CLAUDE.md` (struttura) aggiornati.

## 8. Scelte fatte da Claude (da rivedere)

- Stima caratteri ÷ 4 su tutti i messaggi più il riassunto; schemi degli strumenti esclusi dalla stima e coperti dal margine della soglia.
- Soglia di default 4000 token stimati.
- Taglio solo all'inizio di un turno; la domanda corrente non viene mai riassunta.
- Riassunto aggiunto al prompt di sistema solo al momento della chiamata, non salvato in cronologia.
- Nodo una volta per turno, prima del router; non durante i tentativi del revisore.
- Riassunto non riuscito → cronologia invariata con `WARNING` (concordato), solo per gli errori di LM Studio.
- Riga e testo nel terminale; log dei numeri a `DEBUG`.
- (5.7) Conversazione recente del revisore con la regola del router (ultimi 6 messaggi di testo) e formato `Utente:` / `Assistente:`; istruzioni del revisore invariate.

## 9. Lasciato al piano

- Testo esatto delle istruzioni del riassunto, della riga di terminale e dei log.
- Nome e firma del modulo (per esempio `assistant/summarizer.py`) e della funzione di riassunto facoltativa in `build_graph`.
- Come il nodo calcola i confini dei turni e come lo streaming filtra i pezzi del nodo riassunto.
