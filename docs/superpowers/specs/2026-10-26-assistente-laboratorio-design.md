# Assistente del laboratorio — specifica

Data: 2026-10-26 · Stato: in attesa di approvazione

## 1. Intento

Applicazione Python da terminale che conversa con un modello locale servito da LM Studio, con un flusso organizzato in un grafo LangGraph esplicito. È la base del progetto del corso «Deep Learning e LLM: costruire chatbot e agenti» e verrà estesa nelle lezioni successive: deve quindi restare semplice, leggibile e con confini chiari tra le parti.

Il modello deve poter richiedere uno strumento orologio tramite tool calling; il programma lo esegue davvero e restituisce il risultato al modello, che produce la risposta finale.

## 2. Obiettivi

- Conversazione da terminale con cronologia in memoria per la durata della sessione (nessuna persistenza).
- Grafo LangGraph con stato, nodi e instradamento riconoscibili.
- Strumento orologio con fuso orario esplicito (formato IANA, es. `Europe/Rome`).
- Chiamate allo strumento visibili nei log; limite al numero di passaggi per domanda.
- Avvio sia in locale (PowerShell) sia con Docker Compose; LM Studio resta sull'host.
- Test automatici che non richiedono un modello attivo; istruzioni separate per la prova reale.

## 3. Non obiettivi (in questa consegna)

- Streaming della risposta (rimandato a un incremento successivo, decisione dell'utente).
- MCP, RAG, workflow, altri strumenti, interfacce web/grafiche, servizi cloud.
- Persistenza della cronologia; taglio automatico della cronologia lunga.
- Cambio di modello a runtime.

**Anti-obiettivi:** traceback mostrati all'utente per errori prevedibili; identificativo del modello inventato o scritto nel codice; un test con modello simulato presentato come prova che il modello locale sa usare lo strumento.

## 4. Comportamento per l'utente

### Avvio
All'avvio l'app valida la configurazione, interroga `GET /v1/models` e verifica che `LMSTUDIO_MODEL` sia tra i modelli restituiti. Poi mostra:

```
Assistente del laboratorio — modello: <id>
Scrivi la tua domanda. Comandi: help, clear. Per uscire: quit, exit o Ctrl+C.
```

### Conversazione
- L'utente scrive; mentre il modello lavora compare `…sto pensando`; poi la risposta completa.
- A un saluto il modello risponde normalmente presentandosi.
- Alla domanda "che ora è?" il modello chiama l'orologio con il fuso predefinito (`Europe/Rome`), risponde con l'ora e chiede se serviva l'ora di un altro fuso. Se l'utente nomina una città/fuso ("e a Tokyo?"), il modello richiama lo strumento con il fuso IANA corrispondente (`Asia/Tokyo`).
- Ogni domanda esegue lo strumento di nuovo: l'ora è sempre quella del momento.
- Le risposte sono in italiano.

### Comandi
| Input | Effetto |
|---|---|
| `help` | elenca comandi e modi di uscita |
| `clear` | svuota la cronologia, pulisce lo schermo del terminale (`cls` su Windows, sequenza ANSI altrove; nulla se l'output non è un terminale), ristampa l'intestazione e conferma |
| `quit`, `exit` | uscita pulita |
| Ctrl+C (anche durante l'attesa del modello) | uscita pulita |
| Ctrl+D (Linux/Docker), Ctrl+Z + Invio (Windows) | uscita pulita |
| riga vuota | ignorata |

I comandi sono riconosciuti senza distinzione maiuscole/minuscole e ignorando spazi ai bordi. Ogni uscita stampa un saluto, senza traceback.

## 5. Grafo LangGraph

### Stato
- `messages`: lista dei messaggi (con reducer `add_messages`), comprende il messaggio di sistema.
- `steps`: contatore dei passaggi del modello per la domanda corrente.

### Nodi
- `model`: invoca il modello (con lo strumento collegato) sulla cronologia; incrementa `steps`.
- `tools`: esegue le chiamate allo strumento richieste dall'ultimo messaggio del modello e aggiunge i risultati.
- `step_limit`: gestisce il raggiungimento del limite (vedi sotto).

### Instradamento
- `START → model`.
- Dopo `model`: se l'ultimo messaggio non contiene chiamate a strumenti → `END`; se le contiene e `steps < MAX_STEPS` → `tools`; se le contiene e `steps >= MAX_STEPS` → `step_limit`.
- `tools → model`.
- `step_limit → END`.

Un "passaggio" è un'invocazione del modello. Con `MAX_STEPS=5` il modello può essere invocato al massimo 5 volte per domanda. Il contatore riparte da zero a ogni nuova domanda dell'utente (l'interfaccia lo azzera nell'input passato al grafo).

### Limite raggiunto
Il nodo `step_limit` rimuove dalla cronologia tutti i messaggi interni di quel giro (messaggi del modello con chiamate a strumenti e risultati degli strumenti successivi all'ultima domanda dell'utente) e aggiunge un messaggio del modello:

> Limite di passaggi raggiunto: prova a riformulare la domanda o chiedimi altro.

Restano quindi in cronologia la domanda dell'utente e questo messaggio; il dettaglio del giro fallito resta solo nei log. La cronologia risultante è sempre valida per l'API (nessuna chiamata a strumento senza risultato).

### Cronologia nella sessione
L'interfaccia conserva lo stato tra un turno e l'altro in memoria (per esempio passando la lista dei messaggi o usando un checkpointer in memoria con un `thread_id` fisso; scelta lasciata al piano). `clear` riporta la cronologia al solo messaggio di sistema.

## 6. Strumento orologio

- Nome: `get_current_time`. Parametro: `timezone` (stringa IANA), con default il valore di `DEFAULT_TIMEZONE`.
- Calcolo: istante corrente in UTC convertito con `zoneinfo` nel fuso richiesto. L'ora locale della macchina non viene mai usata, quindi il risultato è identico su Windows, Docker o un server remoto (purché l'orologio di sistema sia sincronizzato).
- Risultato (testo per il modello): fuso, data e ora ISO 8601 con offset, es. `Europe/Rome: 2026-10-26T14:32:05+01:00`.
- Fuso inesistente: nessuna eccezione verso l'utente; lo strumento restituisce al modello un errore leggibile (`Fuso orario sconosciuto: "X". Usa un nome IANA, es. Europe/Rome.`) così il modello può correggersi o spiegarlo.
- Testabilità: la sorgente dell'istante è iniettabile (funzione che restituisce un `datetime` UTC), così i test usano un istante fisso.

## 7. Istruzioni di sistema (bozza)

> Sei l'assistente del laboratorio. Rispondi sempre in italiano, in modo chiaro e conciso. Quando l'utente ti saluta, presentati brevemente. Quando l'utente chiede l'ora o la data, usa sempre lo strumento `get_current_time`, non inventarla. Se l'utente non indica un fuso orario usa `Europe/Rome`; dopo aver risposto chiedi se gli serve l'ora di un altro fuso orario. Se indica una città o un paese, passa allo strumento il nome IANA corrispondente (per esempio Tokyo → Asia/Tokyo).

Il fuso nel testo è preso da `DEFAULT_TIMEZONE`.

## 8. Log

Modulo `logging` standard, livello da `LOG_LEVEL` (default `INFO`), output sul terminale (in Docker visibile anche con `docker compose logs`).

- `INFO`: una riga sobria per ogni chiamata allo strumento, es. `[strumento] get_current_time(timezone=Europe/Rome) → 2026-10-26T14:32:05+01:00`; avviso quando scatta il limite di passaggi.
- `DEBUG`: in più ogni passaggio del grafo (nodo eseguito, instradamento scelto, `steps`/`MAX_STEPS`) e i messaggi rimossi dalla pulizia.
- I log delle librerie (HTTP) restano a `WARNING` salvo `DEBUG`.

## 9. Configurazione

Solo variabili d'ambiente; `.env.example` versionato, `.env` reale ignorato da Git. In locale il file `.env` viene caricato con `python-dotenv`; in Docker tramite `env_file` di Compose.

| Variabile | Obbligatoria | Default | Note |
|---|---|---|---|
| `LMSTUDIO_BASE_URL` | sì | — | es. `http://localhost:1234/v1` (locale), `http://host.docker.internal:1234/v1` (Docker) |
| `LMSTUDIO_MODEL` | sì | — | id restituito da `GET /v1/models`, es. `google/gemma-4-e2b` |
| `LMSTUDIO_TIMEOUT` | no | `120` | secondi |
| `LMSTUDIO_TEMPERATURE` | no | `0.2` | bassa per un uso dello strumento più costante |
| `MAX_STEPS` | no | `5` | intero ≥ 1 |
| `DEFAULT_TIMEZONE` | no | `Europe/Rome` | validato all'avvio |
| `LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING`, … |

LM Studio non richiede chiave: il client usa una chiave fittizia non segreta (es. `lm-studio`).

## 10. Gestione degli errori

| Caso | Comportamento |
|---|---|
| Variabile obbligatoria mancante o valore non valido | messaggio che indica la variabile, uscita con codice ≠ 0 |
| LM Studio irraggiungibile all'avvio | messaggio con l'indirizzo provato, uscita con codice ≠ 0 |
| Modello non presente in `/v1/models` | messaggio con l'elenco dei modelli disponibili, uscita con codice ≠ 0 |
| LM Studio irraggiungibile durante la sessione | messaggio con l'indirizzo; la domanda non entra in cronologia; si può riprovare |
| Timeout | messaggio che spiega il timeout e suggerisce di riprovare; la sessione continua |
| Contesto del modello pieno / altri errori dell'API | messaggio leggibile (per il contesto pieno suggerisce `clear`); la sessione continua |
| Fuso inesistente nello strumento | errore restituito al modello (sez. 6) |
| Limite di passaggi | messaggio concordato e pulizia (sez. 5) |

In caso di errore durante un turno, la cronologia torna allo stato precedente alla domanda (nessun messaggio a metà).

## 11. Struttura del progetto

```
Progetto1LLM/
├── assistant/
│   ├── __init__.py
│   ├── __main__.py   # avvio: python -m assistant
│   ├── config.py     # lettura e validazione variabili d'ambiente
│   ├── llm.py        # client LM Studio, verifica /v1/models
│   ├── tools.py      # strumento orologio
│   ├── graph.py      # stato, nodi, instradamento, pulizia
│   └── cli.py        # ciclo da terminale, comandi, messaggi d'errore
├── tests/
├── docs/superpowers/ # specifica e piano
├── Dockerfile
├── compose.yaml
├── requirements.txt  # versioni fissate
├── .env.example
├── .gitignore
├── .dockerignore
└── README.md         # in italiano
```

Nomi nel codice in inglese; testi per l'utente, documentazione e commit in italiano.

## 12. Dipendenze

Python 3.14 in locale e nell'immagine Docker (`python:3.14-slim`). Versioni fissate in `requirements.txt` dopo verifica dell'installazione su 3.14 (al 2026-10-26 su PyPI: langgraph 1.2.17, langchain-openai 1.7.2, langchain-core 1.7.0, pytest 9.1.1, tzdata 2026.5, python-dotenv 1.2.4; tutte dichiarano supporto ≥ 3.10).

| Pacchetto | Motivo |
|---|---|
| `langgraph` | grafo esplicito |
| `langchain-openai` | client per l'API compatibile OpenAI di LM Studio, con tool calling |
| `langchain-core` | messaggi, strumenti, modello finto per i test |
| `tzdata` | database IANA dei fusi: indispensabile su Windows, dove `zoneinfo` non lo trova nel sistema |
| `python-dotenv` | caricare `.env` nell'esecuzione locale |
| `pytest` | test (dipendenza di sviluppo, `requirements-dev.txt`) |

## 13. Docker

- `Dockerfile` basato su `python:3.14-slim`, utente non root, installa `requirements.txt`, avvia `python -m assistant`.
- `compose.yaml` con un solo servizio `app`: `env_file: .env`, `stdin_open: true`, `tty: true`, `extra_hosts: ["host.docker.internal:host-gateway"]` (necessario su Linux, innocuo su Docker Desktop).
- Avvio interattivo: `docker compose run --rm app` (non `up`, che non collega il terminale all'input).
- LM Studio non è containerizzato. Da verificare nella prova reale se serve attivare in LM Studio l'opzione per servire sulla rete locale perché il container lo raggiunga; l'esito va scritto nel README.

## 14. Test e verifiche

### Test automatici (senza modello)
Eseguiti con `pytest`, usando un modello finto che restituisce messaggi predefiniti (anche con chiamate a strumenti):
- strumento: ora corretta per fuso con istante fisso (incluso cambio ora legale), fuso predefinito, fuso inesistente;
- grafo: risposta diretta senza strumento; un giro strumento → risposta; instradamento a `tools` ed `END`;
- limite: con un modello finto che chiede sempre lo strumento il grafo si ferma a `MAX_STEPS` invocazioni, pulisce la cronologia e aggiunge il messaggio concordato; il contatore riparte alla domanda successiva;
- cronologia: conservata tra due turni; svuotata da `clear`; invariata dopo un errore del modello;
- configurazione: variabili mancanti/non valide, default;
- interfaccia: comandi (`help`, `clear`, `quit`, `exit`, riga vuota) ed EOF/Ctrl+C senza traceback;
- log: la chiamata allo strumento produce la riga `INFO` attesa.

### Prova reale (manuale, attivata esplicitamente)
Procedura nel README, eseguita in locale (PowerShell) e con Docker Compose:
1. avvio con il modello reale (`google/gemma-4-e2b`);
2. "ciao" → presentazione;
3. "che ora è?" → riga di log con `Europe/Rome` e ora che coincide con quella di Windows;
4. "e a Tokyo?" → log con `Asia/Tokyo` e ora corretta;
5. memoria: domanda che fa riferimento a una precedente; poi `clear` e verifica che non la ricordi;
6. casi d'errore: LM Studio spento, modello inesistente in `.env`, uscite con Ctrl+C / `quit`.

Solo questa prova dimostra che il modello locale sa usare lo strumento. Il resoconto finale indica cosa è stato eseguito, con quale esito e cosa resta da provare.

## 15. Scelte lasciate al builder (o fatte da Claude)

Scelte fatte da Claude, da rivedere: controllo del modello su `/v1/models` all'avvio; errore di fuso restituito al modello; temperatura `0.2`; `python-dotenv`; comandi d'uscita `quit`/`exit`; avviso `…sto pensando`; nessun taglio della cronologia lunga; nome del pacchetto `assistant`; testo delle istruzioni di sistema.

Lasciate al piano: come conservare lo stato tra i turni (lista messaggi o checkpointer in memoria); modello finto specifico per i test; versioni esatte dopo verifica su 3.14.
