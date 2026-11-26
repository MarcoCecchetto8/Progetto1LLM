# Streaming della risposta, del ragionamento e degli strumenti — specifica

Data: 2026-11-16 · Stato: approvata dall'utente il 2026-11-16 (letta da un revisore esterno: nessuna domanda aperta)

Riferimenti: specifica iniziale `2026-10-26-assistente-laboratorio-design.md` (dove lo streaming era un non obiettivo), `2026-11-09-note-fastapi-design.md` sezione 5.4 (avviso sui falsi successi). Valide per tutto ciò che qui non cambia.

## 1. Intento

Oggi, dopo una domanda, il terminale mostra «…sto pensando» e poi la risposta tutta insieme; le chiamate agli strumenti compaiono come righe di log a cose fatte. L'utente vuole **vedere l'agente mentre lavora**: il ragionamento del modello e la risposta token per token, e gli strumenti nel momento in cui il modello li chiede. Lo scopo è didattico (corso su chatbot e agenti): osservare come il modello ragiona, quando sceglie uno strumento e che cosa ne ottiene.

## 2. Che cosa è stato verificato (2026-11-16, sonde nello scratchpad)

- `google/gemma-4-e2b` servito da LM Studio **ragiona**: in streaming (`/v1/chat/completions`, `stream: true`) il ragionamento arriva nel campo `delta.reasoning_content`, separato da `delta.content`. È in **inglese** anche con domande in italiano («Thinking Process: 1. Analyze the Request…») ed è lungo (per «Quanto fa 17×23?» circa 440 pezzi di ragionamento e 450 di risposta).
- Con strumenti legati le chiamate arrivano a pezzi in `delta.tool_calls` (prima nome e id, poi gli argomenti a frammenti); in quel caso la risposta (`content`) è vuota. Ragionamento e chiamate arrivano **nella stessa risposta** (con «Che ore sono a Tokyo?»: 226 pezzi di ragionamento, poi 10 di `tool_calls`).
- **`ChatOpenAI` di `langchain-openai` 1.7.2 scarta `reasoning_content`**: con `.stream()` i pezzi contengono solo la risposta. Per mostrare il ragionamento serve un'estensione del collegamento al modello (sezione 5.1).

## 3. Obiettivi

- Durante ogni turno il terminale mostra, mentre accadono:
  1. il **ragionamento** del modello, token per token, in grigio attenuato sotto l'intestazione `[ragionamento]`, nella lingua in cui il modello lo scrive;
  2. ogni **strumento** chiesto, su una riga propria con nome e argomenti appena il modello ha finito di chiederlo, poi l'**esito** quando lo strumento risponde;
  3. la **risposta**, token per token, in colore normale.
- Se il controllo dei falsi successi aggiunge un avviso, l'avviso compare **in fondo**, dopo la risposta già scritta (scelta dell'utente).
- Il ragionamento si spegne con la variabile **`SHOW_REASONING`** (vero/falso, predefinito vero).
- **Ctrl+C mentre il modello lavora** ferma solo quel turno; Ctrl+C al prompt chiude l'assistente come oggi.
- Funziona in locale e con Docker Compose.

## 4. Non obiettivi e anti-obiettivi

**Non obiettivi:**
- Tradurre o riassumere il ragionamento (costerebbe un altro giro del modello).
- Interfacce grafiche, librerie per terminale nuove (colori con sequenze ANSI, senza nuove dipendenze), salvataggio del ragionamento su file.
- Cambiare quali strumenti esistono o come funzionano.

**Anti-obiettivi:**
- il ragionamento che entra nella **cronologia** e viene rimandato al modello nei turni successivi (riempirebbe il contesto);
- una risposta mostrata due volte (in streaming e poi di nuovo intera);
- la stessa chiamata a uno strumento mostrata due volte (dal flusso e dal log);
- dopo un Ctrl+C che ferma un turno, il servizio delle note o il server degli strumenti **morti** mentre l'assistente resta aperto;
- un falso successo che arriva senza avviso (vale la specifica delle note, 5.4);
- sequenze di colore scritte quando l'uscita non è un terminale (pipe, file, `docker compose run -T`).

## 5. Comportamento

### 5.1 Collegamento al modello

- Il modello continua a essere `ChatOpenAI` verso LM Studio, ma con una **sottoclasse** (nell'assistente, modulo del collegamento al modello) che conserva `delta.reasoning_content` nei pezzi dello streaming (per esempio in `additional_kwargs`); forma esatta al piano, verificata contro la versione installata di `langchain-openai`.
- Il ragionamento accumulato **non** deve restare nel messaggio salvato in cronologia: viene tolto prima che il messaggio entri nello stato, oppure non viene mai rimandato al modello. Un test lo verifica.
- Se un altro modello non manda `reasoning_content`, semplicemente non c'è ragionamento da mostrare: nessun errore.

### 5.2 Visualizzazione di un turno

Esempio (il grigio è indicato a parole):

```
> Che ore sono a Tokyo?
[ragionamento]                                   ← grigio
Thinking Process: 1. Analyze the Request ...     ← grigio, token per token
[strumento] get_current_time {"timezone": "Asia/Tokyo"}
[strumento] get_current_time → Asia/Tokyo: 2026-11-16T22:32:05+09:00
[ragionamento]
The tool returned ...
A Tokyo sono le 22:32 di lunedì 16 novembre.     ← token per token
>
```

- Ogni passaggio del modello (prima e dopo gli strumenti) può avere il suo ragionamento: l'intestazione `[ragionamento]` compare quando ne inizia uno.
- Gli esiti con errore dello strumento sono distinguibili (per esempio `[strumento] … errore → …`); testo esatto al piano. Esiti lunghi (per esempio un elenco di note) si mostrano interi.
- La riga «…sto pensando» resta **solo** quando il ragionamento è spento, fino al primo token della risposta o al primo strumento.
- L'avviso dei falsi successi, se c'è, va a capo dopo la risposta, separato da una riga vuota come oggi.
- Le righe di log `[strumento] … call_id=… esito=…` del nodo strumenti passano dal livello `INFO` a `DEBUG` (scelta dell'utente): restano per la diagnosi con `LOG_LEVEL=DEBUG`.
- La cronologia salvata alla fine del turno è la stessa di oggi (risposta completa, con l'eventuale avviso), senza ragionamento.

### 5.3 Uscita non su terminale

Se lo standard output non è un terminale (pipe, file, `docker compose run -T`): niente sequenze di colore; ragionamento, strumenti e risposta si scrivono comunque in streaming, con le stesse intestazioni. *Scelta di Claude.* Su Windows le sequenze ANSI devono funzionare in PowerShell e nel terminale di VS Code; se servono per attivarle, solo mezzi della libreria standard.

### 5.4 Ctrl+C

- **Mentre il modello ragiona, risponde o mentre uno strumento è in esecuzione**: il turno si ferma, compare `Risposta interrotta.` (testo esatto al piano), la domanda e i messaggi del turno **non** entrano nella cronologia, si torna al prompt `>`. *Limite dichiarato*: uno strumento già eseguito non viene annullato (una nota già salvata resta salvata).
- **Al prompt `>`**: chiude l'assistente come oggi («Arrivederci!»).
- **Alla domanda di conferma `[s/N]`** di un'eliminazione: comportamento attuale, già provato (nulla eliminato, l'assistente si chiude).
- **Vincolo**: su Windows Ctrl+C viene inviato a tutti i processi collegati alla console, quindi anche al servizio delle note avviato in automatico e al server MCP. Dopo un «Risposta interrotta.» la domanda successiva deve funzionare con strumenti e note: i processi figli non devono ricevere il Ctrl+C (o non devono morirne). Da risolvere al piano e da verificare nella prova reale su Windows; in Docker (Linux) da verificare allo stesso modo.

### 5.5 Errori durante lo streaming

Se a metà dello streaming arriva un errore (LM Studio non raggiungibile, timeout, collegamento con il server MCP o con il servizio delle note perso), si va a capo dopo il testo già scritto e si mostra lo stesso messaggio d'errore di oggi; la cronologia resta come prima della domanda (come oggi). Una risposta vuota mantiene il messaggio `EMPTY_ANSWER` di oggi.

## 6. Configurazione

- `SHOW_REASONING` nel `.env` e in `.env.example`: valori accettati come gli altri booleani del progetto se esistono, altrimenti `true`/`false` (senza distinzione di maiuscole); valore non valido → errore di configurazione chiaro all'avvio, come per le altre variabili. Predefinito: `true`.
- Docker Compose passa la variabile all'assistente come le altre.

## 7. Test e verifiche

### Test automatici (senza modello e senza LM Studio)
- **Collegamento**: la sottoclasse conserva `reasoning_content` da pezzi di streaming finti (formato OpenAI) e non lo inserisce nei messaggi rimandati al modello.
- **Visualizzazione**, con un modello finto che emette pezzi di ragionamento, risposta e chiamate: ordine e intestazioni corretti; risposta scritta una sola volta; con `SHOW_REASONING=false` nessun ragionamento e «…sto pensando» presente; senza terminale nessuna sequenza di colore; con terminale il ragionamento è attenuato.
- **Strumenti**: riga della chiamata e riga dell'esito (anche con errore), una sola volta ciascuna.
- **Avviso**: risposta con falso successo → testo in streaming, poi l'avviso in fondo; cronologia con l'avviso come oggi.
- **Cronologia**: nessun ragionamento nei messaggi salvati; turno interrotto (Ctrl+C simulato con `KeyboardInterrupt` durante lo streaming) → `Risposta interrotta.`, cronologia invariata, il ciclo continua; Ctrl+C al prompt → uscita come oggi.
- **Errori a metà streaming**: messaggio d'errore dopo il testo parziale, cronologia invariata.
- **Log**: la riga `[strumento]` del nodo strumenti è a livello `DEBUG`.
- **Configurazione**: `SHOW_REASONING` assente, vero, falso, non valido.
- Restano verdi tutti i test esistenti (adattati dove cambia il modo in cui il ciclo legge i risultati del grafo).

### Prova reale con LM Studio (locale su Windows e con Docker)
- «Quanto fa 17*23?»: ragionamento attenuato che scorre, poi risposta che scorre.
- «Che ore sono a Tokyo?»: ragionamento, riga dello strumento con argomenti, esito, risposta.
- `SHOW_REASONING=false`: solo «…sto pensando», strumenti e risposta.
- Ctrl+C durante un ragionamento lungo → «Risposta interrotta.», poi una domanda che usa **uno strumento MCP e una nota** funziona (processi figli vivi); poi Ctrl+C al prompt chiude.
- Una richiesta che produce un falso successo (per esempio «Ricordami di consegnare il report venerdì») → avviso in fondo.
- Docker (`docker compose run --rm app`, con terminale): colori e streaming; con `-T` e input da pipe: niente colori, stesso contenuto.

Esiti nel README, con gli eventuali limiti trovati.

## 8. Ordine di lavoro e branch

Branch `feature/streaming` da `developer`; merge `--no-ff` in `developer` dopo la prova reale e l'ok dell'utente, push di `developer`, eliminazione del branch. Pezzi piccoli, ciascuno con test e commit. Aggiornare README (configurazione, cosa si vede, Ctrl+C, diagnosi) e `CLAUDE.md` (struttura e confini: lo streaming non è più un non obiettivo).

## 9. Scelte fatte da Claude (da rivedere)

- Ragionamento in grigio con le sequenze ANSI standard, intestazione `[ragionamento]` per ogni passaggio del modello.
- Riga dello strumento quando la chiamata è completa (non argomento per argomento mentre arriva).
- Nome della variabile `SHOW_REASONING`, predefinito vero.
- Senza terminale: niente colori, streaming invariato.
- «…sto pensando» solo con il ragionamento spento.
- Turno interrotto: tutto il turno fuori dalla cronologia, anche se uno strumento ha già agito (limite dichiarato). Con Ctrl+C durante uno strumento il risultato viene scartato, non si tenta di annullare lo strumento.
- Il messaggio di limite di passaggi (`LIMIT_MESSAGE`) non è generato dal modello: si stampa intero alla fine del turno, come oggi.
- L'avviso dei falsi successi non è generato dal modello: il terminale stampa solo il testo aggiunto dopo la risposta già scritta in streaming.

## 10. Lasciato al piano

- Forma della sottoclasse di `ChatOpenAI` e punto in cui il ragionamento viene tolto dal messaggio salvato.
- Come il ciclo da terminale riceve i pezzi dal grafo LangGraph (per esempio `graph.stream` con le modalità adatte) e come il controllo della risposta (nodo `answer_check`) fa arrivare l'avviso in fondo.
- Testi esatti delle righe degli strumenti, di «Risposta interrotta.» e dell'intestazione.
- Meccanismo per proteggere i processi figli dal Ctrl+C su Windows e su Linux.
- Attivazione delle sequenze ANSI su Windows, se necessaria.
