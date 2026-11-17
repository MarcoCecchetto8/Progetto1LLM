# Agente come servizio HTTP (lezione 6, step 6) — specifica

Data: 2026-11-17 · Stato: approvata dall'utente il 2026-11-17

Riferimenti: lezione 6, slide 12 (architettura finale: front-end, back-end, agente, database) e 13 (step 6 · l'agente come servizio HTTP). Specifiche precedenti valide per tutto ciò che qui non cambia: streaming (`2026-11-16-streaming-design.md`), note (`2026-11-09-note-fastapi-design.md`), router, revisore, riassunto, preferenze, prompt MCP.

## 1. Intento

Finora l'agente era un'applicazione da terminale: CLI e grafo nello stesso processo. Per servire più avanti un back-end e un'interfaccia web (step 7–8) l'agente diventa un **servizio HTTP**: riceve la conversazione e restituisce la risposta. La CLI diventa **un client di quell'API**. Lo stesso grafo risponde alla CLI e alle chiamate HTTP, senza duplicare la logica.

L'agente è **senza stato**: cronologia e riassunto arrivano dal chiamante a ogni richiesta e tornano aggiornati. A conservarli è il chiamante (oggi la CLI, domani il back-end).

## 2. Obiettivi (slide 13)

1. Separare l'agente dall'interfaccia: la CLI diventa un client dell'API.
2. Endpoint che riceve messaggio e cronologia e restituisce risposta e strumenti usati.
3. Endpoint di stato: agente, server MCP e modello raggiungibili.
4. Agente senza stato: cronologia e riassunto arrivano dal chiamante e tornano aggiornati.

Evidenze richieste: chiamata HTTP con una domanda che usa un tool (risposta e traccia nei log); modello o strumenti non disponibili → codice e messaggio d'errore comprensibili; test dell'API con il grafo simulato; documentazione OpenAPI consultabile.

**Non obiettivi**: back-end, database, front-end e container separati per tutto (step 7–9); persistenza delle chat; autenticazione; più utenti contemporanei serviti in parallelo (vedi 5.8); nuovi strumenti; modifiche al comportamento di router, revisore, riassunto o strumenti.

**Anti-obiettivi** (sarebbe un fallimento anche se «funziona»): la CLI che perde lo streaming o la conferma prima di eliminare una nota; logica del turno scritta due volte (una per la CLI, una per l'API); l'agente che si ricorda qualcosa tra due richieste.

## 3. Scelte dell'utente (in chat, 2026-11-17)

- **Lo streaming resta**: nel terminale ragionamento, righe `[strumento]`, `[revisore]`, riassunto e risposta compaiono man mano, come oggi.
- **La conferma prima di eliminare una nota resta** e passa dal client: l'agente si ferma e chiede conferma, il client la chiede all'utente e rimanda la decisione, l'agente prosegue. Così domani funziona anche dal browser.
- **La CLI avvia da sola l'agente**, come fa con il servizio delle note: con `AGENT_SERVICE_URL` vuota lo avvia in locale, con l'indirizzo usa quello.
- Quadro complessivo (sezioni 4–5 nella forma presentata in chat) approvato.

## 4. Architettura

```
CLI (assistant)  ──HTTP/SSE──►  Agente (agent_service: FastAPI + grafo)  ──►  LM Studio (host)
                                         │                               ──►  server MCP (stdio, processo figlio)
                                         └──────────────────────────────────►  servizio note (HTTP)
```

- **Nuovo pacchetto `agent_service/`** (FastAPI, come `notes_service/`): applicazione HTTP, schemi delle richieste e risposte, conversione degli eventi, avvio con uvicorn (`python -m agent_service`). Nessuna nuova dipendenza: FastAPI, uvicorn e httpx ci sono già; lo streaming usa una `StreamingResponse` con `text/event-stream` (SSE scritto a mano, formato semplice).
- **Il cuore dell'agente resta in `assistant/`** (`graph.py`, `llm.py`, `mcp_client.py`, `router.py`, `reviewer.py`, `summarizer.py`, `notes.py`, `preferences.py`): non si sposta, per non rompere 539 test e la storia. `agent_service` lo importa.
- **Avvio dell'agente spostato**: quello che oggi fa `assistant/__main__.py` (configurazione, controllo del modello, client MCP, preferenze, prompt, servizio note, costruzione del grafo) passa all'avvio di `agent_service` (lifespan di FastAPI o funzione equivalente).
- **La CLI** (`assistant/cli.py`, `assistant/__main__.py`) diventa un client: nuovo modulo `assistant/agent_client.py` (chiamate HTTP, lettura degli eventi SSE, avvio automatico del servizio come `LocalNotesService`).
- Il vecchio modo «tutto in un processo» sparisce: la CLI usa sempre l'API.

## 5. Comportamento

### 5.1 Formato dei messaggi

La cronologia viaggia in JSON con uno schema proprio, documentato in OpenAPI, vicino al formato chat di OpenAI:

- `ruolo`: `utente`, `assistente` o `strumento`;
- `contenuto`: testo;
- solo per `assistente`: `chiamate` (elenco di `{id, nome, argomenti}`), può essere vuoto;
- solo per `strumento`: `id_chiamata`, `nome`, `errore` (booleano).

Il **messaggio di sistema non viaggia**: lo costruisce l'agente (`system_prompt(preferences)`), perché le preferenze le legge lui. Il ragionamento non è mai in cronologia (come oggi). Conversione da e verso i messaggi LangChain in un modulo con funzioni pure e testate (andata e ritorno senza perdite per i campi elencati). Gli id dei messaggi LangChain non viaggiano: si rigenerano a ogni richiesta (servono solo dentro un turno).

### 5.2 Endpoint

| Metodo e percorso | Che cosa fa |
|---|---|
| `POST /chat` | Esegue un turno e restituisce tutto insieme in JSON. |
| `POST /chat/stream` | Stesso turno, con eventi SSE man mano (5.3). |
| `GET /stato` | Stato di agente, modello, server MCP e servizio note (5.5). |
| `GET /prompts` | Elenco dei prompt MCP con argomenti (come `list_prompts`). |
| `POST /prompts/{nome}` | Corpo `{argomenti: {...}}` → messaggi del prompt compilati dal server. |
| `GET /docs`, `GET /openapi.json` | Documentazione OpenAPI (automatica di FastAPI). |

**Richiesta del turno** (uguale per `/chat` e `/chat/stream`):

- `messaggi`: messaggi nuovi del turno, almeno uno, ruoli `utente` o `assistente` (una domanda normale è un solo messaggio `utente`; un prompt MCP può darne più di uno);
- `cronologia`: messaggi precedenti (può essere vuota);
- `riassunto`: testo del riassunto in vigore (può essere vuoto);
- `ripresa` (facoltativa, 5.4): stato sospeso restituito dall'agente e decisioni dell'utente sulle eliminazioni. Se c'è, `messaggi` e `cronologia` vanno omessi o vengono ignorati (da decidere nel piano, documentato in OpenAPI).

**Risposta di `/chat`** (e contenuto dell'evento finale di `/chat/stream`):

- `esito`: `completato` oppure `conferma_richiesta`;
- con `completato`: `risposta` (testo finale mostrato all'utente, avviso dei falsi successi compreso), `strumenti` (elenco delle chiamate del turno: nome, argomenti, esito breve, errore sì/no), `cronologia` aggiornata (senza messaggio di sistema, già riassunta se il nodo del riassunto è intervenuto), `riassunto` aggiornato, `righe` (le righe informative del turno: revisore, riassunto, rifiuto, limite di passaggi; per chi non usa lo streaming);
- con `conferma_richiesta`: `conferme` (elenco di `{id_nota, domanda}`, con la domanda già pronta da mostrare, come oggi «Elimino la nota 3 «…» · scade tra 2 giorni? [s/N] ») e `sospeso` (5.4).

Il chiamante, a turno completato, sostituisce la sua cronologia e il suo riassunto con quelli restituiti. Un turno interrotto, rifiutato da un errore o con risposta vuota non cambia la cronologia del chiamante.

### 5.3 Streaming (SSE)

Il turno in streaming produce eventi `text/event-stream`, ciascuno con `event:` e `data:` JSON:

| Evento | Dati | Corrisponde oggi a |
|---|---|---|
| `ragionamento` | `{testo}` | `TurnView.reasoning` |
| `risposta` | `{testo}` | `TurnView.answer` |
| `strumento` | `{nome, argomenti}` | `TurnView.tool_call` |
| `esito_strumento` | `{nome, contenuto, errore}` | `TurnView.tool_result` |
| `riga` | `{testo}` | `TurnView.extra` (revisore, riassunto, rifiuto, limite, avviso note) |
| `fine` | risposta completa come `/chat` | fine del turno |
| `errore` | `{codice, messaggio}` | messaggi d'errore della CLI |

- **Una sola logica**: la funzione che oggi traduce `graph.stream` in chiamate a `TurnView` (`stream_turn`) resta l'unico punto che interpreta il grafo. Lato agente un «osservatore» con la stessa interfaccia di `TurnView` produce eventi; `/chat` usa un osservatore che li scarta e prende il risultato finale. Lato CLI gli eventi tornano chiamate a `TurnView`. L'aspetto del terminale resta quello di oggi (colori, `[risposta]`, `…sto pensando` con `SHOW_REASONING=false`).
- `SHOW_REASONING` diventa un'impostazione **della CLI** (cosa mostrare); l'agente invia sempre il ragionamento.
- **Interruzione (Ctrl+C)**: la CLI chiude la connessione e stampa «Risposta interrotta.» come oggi; il turno non entra in cronologia. L'agente, accorgendosi che il client se n'è andato, ferma il modello al pezzo successivo (oggi lo fa `CancelOnInterrupt`) e non lascia thread appesi.
- Errori **dopo** l'inizio dello streaming: lo stato HTTP è già 200, quindi arrivano come evento `errore` (stessi codici e messaggi di 5.6).

### 5.4 Conferma prima di eliminare una nota

Oggi `delete_note` chiede conferma con `input()` dentro il tool. L'agente non ha più un terminale, quindi:

1. Quando il modello chiede uno o più `delete_note`, **prima di eseguire qualsiasi strumento** di quel messaggio, l'agente controlla se per ogni `delete_note` c'è una decisione dell'utente. Il controllo sta prima dell'esecuzione apposta: se il modello chiede insieme `add_note` e `delete_note`, rieseguire `add_note` alla ripresa creerebbe una nota doppia.
2. Se manca una decisione, l'agente legge la nota dal servizio (come oggi, per mostrarne testo e scadenza) e **sospende il turno**: risponde `conferma_richiesta` con le domande e lo **stato sospeso** (cronologia completa fino al messaggio con le chiamate, `steps`, `reviews`, riassunto, ciò che serve per proseguire). Una nota inesistente non chiede conferma: il tool darà l'errore di sempre.
3. Il client mostra ogni domanda, raccoglie `s`/`N` e rimanda la richiesta con `ripresa = {sospeso, decisioni: {id_nota: true/false}}`.
4. L'agente riparte **dall'esecuzione degli strumenti** di quel messaggio (il grafo, all'ingresso, va al nodo degli strumenti quando riceve una ripresa) con le decisioni disponibili ai tool tramite la configurazione della chiamata (non variabili globali); poi il turno prosegue normalmente (modello, revisore, controllo delle note).
5. Il testo restituito al modello resta quello di oggi: «Eliminazione della nota N annullata dall'utente.» o «Nota N eliminata: «…».»; i log `[note] eliminazione … confermata/annullata dall'utente` restano.

Lo stato sospeso è opaco per il client: lo restituisce così com'è. L'agente non conserva nulla nel frattempo (senza stato).

- **Durata delle decisioni**: valgono per tutto il resto del turno, anche dopo un nuovo tentativo del revisore. Se il modello chiede di nuovo `delete_note` per una nota già decisa non si richiede: un «no» resta un annullamento; un «sì» su una nota già eliminata dà l'errore di sempre «Nessuna nota con ID …». Se nello stesso turno serve una seconda sospensione (per un'altra nota), il nuovo `sospeso` porta con sé le decisioni precedenti.
- **Risposta finale dopo una ripresa**: `strumenti` e `righe` coprono **tutto il turno**, anche la parte prima della sospensione. Per questo il `sospeso` porta anche le chiamate agli strumenti e le righe già prodotte. In streaming, dopo la ripresa, arrivano solo gli eventi nuovi.

Nella CLI: Ctrl+C o fine dell'input alla domanda di conferma → si esce dall'assistente come oggi; risposta diversa da `s`/`si`/`sì` → annullata come oggi. `confirmation_pending`/`reset_confirmation` e `ask_in_terminal` lasciano `assistant/notes.py` (o restano solo lato CLI) perché i tool non leggono più dal terminale.

### 5.5 Stato

`GET /stato` → `{agente: "ok", modello: {...}, strumenti: {...}, note: {...}}` con per ciascuno `raggiungibile` (sì/no), un messaggio in italiano e i dati utili (identificativo del modello, numero di strumenti MCP, indirizzo del servizio note). Il modello si controlla con `GET /v1/models` (come `check_model`); il server MCP con una richiesta leggera alla sessione aperta; il servizio note con la sua risposta HTTP. Codice HTTP 200 se tutto è raggiungibile, 503 altrimenti (con lo stesso corpo).

**Avvio dell'agente con pezzi mancanti:**

- **Modello non raggiungibile** (LM Studio spento o modello non caricato): l'agente **parte lo stesso**. Il grafo si costruisce comunque, perché `ChatOpenAI` non contatta il server finché non si fa una chiamata. `/stato` risponde 503 e i turni danno l'errore della tabella 5.6. Così l'evidenza «modello non disponibile → codice e messaggio» si vede via HTTP, e l'agente torna utilizzabile appena LM Studio è acceso, senza riavvio.
- **Server MCP o servizio note non avviabili**: l'agente **non parte**. Senza catalogo, preferenze e prompt non si può costruire il grafo. Esce con codice 1 e un messaggio chiaro sul suo stderr.
- **La CLI**, se l'agente avviato in automatico termina durante l'attesa, mostra quel messaggio, ricavandolo dall'uscita dell'agente, ed esce con codice 1. Non aspetta fino al timeout.

**Collegamenti caduti durante il funzionamento** (sessione MCP o servizio note): **nessuna riconnessione automatica** in questo step. Il turno dà l'errore della tabella 5.6 e `/stato` lo segnala. Per tornare a funzionare **si riavvia l'agente**: in locale basta riavviare la CLI, che lo riavvia; in Docker serve `docker compose restart agent`. I messaggi lo dicono, e il limite va nel README.

### 5.6 Errori

Errori prima dello streaming (e di `/chat`) come codice HTTP + `{codice, messaggio}`; durante lo streaming come evento `errore`. Messaggi in italiano, gli stessi che la CLI stampa oggi (spostati nell'agente):

| Situazione | HTTP | `codice` | Messaggio (come oggi) |
|---|---|---|---|
| LM Studio non raggiungibile | 503 | `modello_non_raggiungibile` | «LM Studio non è raggiungibile all'indirizzo …» |
| Modello oltre il timeout | 504 | `modello_timeout` | «Il modello non ha risposto entro … secondi. Riprova.» |
| Contesto pieno | 422 | `contesto_pieno` | «Il contesto del modello è pieno: usa 'clear' …» |
| Altro errore dell'API del modello | 502 | `errore_modello` | «Errore dell'API del modello: …» |
| Server MCP non raggiungibile | 503 | `strumenti_non_raggiungibili` | «Il server degli strumenti non risponde …» |
| Servizio note non raggiungibile | 503 | `note_non_raggiungibili` | «Il servizio delle note non risponde …» |
| Risposta vuota del modello | 502 | `risposta_vuota` | «Il modello non ha dato una risposta: riprova.» |
| Richiesta non valida (schema) | 422 | (quello di FastAPI) | messaggio di validazione |
| Prompt rifiutato dal server | 422 | `prompt_rifiutato` | «Il server ha rifiutato il prompt: …» |
| Errore imprevisto | 500 | `errore_imprevisto` | «Errore imprevisto: …» |

I testi «esci e riavvia l'assistente» vanno adattati dove non hanno più senso (decide il piano; restano comprensibili per l'utente della CLI). La CLI stampa il `messaggio` e continua (come oggi), salvo l'agente irraggiungibile (5.7).

### 5.7 CLI

- **Avvio**: con `AGENT_SERVICE_URL` vuota la CLI avvia `python -m agent_service` su `127.0.0.1` (porta predefinita 8001, verificare che non collida con altro nel progetto) in un gruppo di processi separato, aspetta che risponda e lo chiude all'uscita, come `LocalNotesService` (codice dell'avvio condiviso dove possibile, senza forzare). Uscita dell'agente silenziosa salvo `LOG_LEVEL=DEBUG`. Con `AGENT_SERVICE_URL` valorizzata usa quell'indirizzo.
- Dopo l'avvio chiama `GET /stato`: se il modello o il server MCP non sono raggiungibili stampa il messaggio e esce con codice 1 (oggi fa così all'avvio); poi `GET /prompts` per `/prompts` e il controllo degli argomenti.
- **Intestazione** con l'identificativo del modello preso da `/stato`.
- **Turno**: `POST /chat/stream` con cronologia, riassunto e messaggi nuovi; eventi → `TurnView`; a `fine` con `completato` aggiorna cronologia e riassunto; con `conferma_richiesta` chiede e riprende (5.4).
- `clear`, `help`, `quit`/`exit`, Ctrl+C e i messaggi di uscita restano quelli di oggi; `/prompts` e `/prompt` restano identici per l'utente (analisi e controllo degli argomenti in `assistant/prompts.py`, testo dal server tramite `POST /prompts/{nome}`).
- **Agente irraggiungibile** durante la sessione (connessione rifiutata o caduta a metà): messaggio chiaro «L'agente non risponde: esci e riavvia l'assistente.» e la sessione continua (come oggi per le note).
- Il timeout di lettura dello streaming non deve tagliare un turno lungo (router + modello + revisore possono superare il timeout del singolo modello): il piano lo sceglie (per esempio nessun limite in lettura, timeout di connessione breve).

### 5.8 Log e concorrenza

- L'agente registra a INFO per ogni turno: inizio (endpoint, numero di messaggi), strumenti chiamati con argomenti ed esito, esito del turno e durata. È la «traccia nei log» dell'evidenza; si vede avviando `python -m agent_service` a parte o con `docker compose logs agent`. I log esistenti (`[router]`, `[mcp]`, `[note]`, `[controllo]`, `[revisore]`…) restano.
- Un turno alla volta: l'agente serializza i turni con un lock (il client MCP ha una sessione sola e LM Studio serve un modello). Una seconda richiesta aspetta. Limite documentato nel README; lo step 7 potrà rivederlo.

### 5.9 Configurazione e Docker

- Nuova variabile `AGENT_SERVICE_URL` in `.env.example` (vuota in locale, come `NOTES_SERVICE_URL`). Le variabili del modello, del grafo, del riassunto, delle preferenze e del servizio note valgono per l'agente; `SHOW_REASONING` per la CLI; `LOG_LEVEL` per entrambi.
- `compose.yaml`: nuovo servizio `agent` (`python -m agent_service --host 0.0.0.0 …`), con `env_file`, `LMSTUDIO_BASE_URL` verso l'host, `NOTES_SERVICE_URL: http://notes:8000`, preferenze montate, `extra_hosts`; porta esposta solo su `127.0.0.1` (per `/docs` e le chiamate a mano). `app` resta la CLI con `AGENT_SERVICE_URL: http://agent:8001` e `depends_on: agent`. `Dockerfile` copia anche `agent_service/`. Comando d'uso invariato: `docker compose run --rm app`.

## 6. Test e verifiche

### Test automatici (senza LM Studio)

- Conversione messaggi JSON ↔ LangChain (andata e ritorno, chiamate, errori dei tool).
- API con `TestClient` di FastAPI e grafo costruito sul **modello finto** di `tests/fakes.py` (client MCP e servizio note finti): `/chat` con e senza strumento; `/chat/stream` con sequenza degli eventi; cronologia e riassunto restituiti; rifiuto del router; ogni errore della tabella 5.6 con codice e messaggio; `/stato` 200 e 503; `/prompts` e `POST /prompts/{nome}` (anche rifiuto); `/openapi.json` disponibile.
- Conferma: sospensione con `delete_note` (anche insieme ad `add_note`: nessuna nota doppia), ripresa con sì e con no, nota inesistente senza conferma, due eliminazioni nello stesso messaggio.
- Agente senza stato: due richieste indipendenti non si influenzano.
- CLI con un agente finto (eventi registrati): stampa uguale a oggi per ragionamento, strumenti, revisore, riassunto, avvisi; aggiornamento della cronologia solo a turno completato; conferma s/N/Ctrl+C; errori dell'agente; agente irraggiungibile; `/prompts` e `/prompt`.
- Avvio automatico dell'agente (come `test_notes_launcher.py`).
- I test esistenti del grafo, degli strumenti e della vista restano verdi (adattati solo dove cambia l'interfaccia, es. conferma delle note).

### Prova reale (separata, attivata esplicitamente)

- Locale: `python -m assistant` con agente avviato in automatico; domanda con strumento (ora), domanda fuori ambito, nota salvata ed eliminata con conferma (s e N), Ctrl+C durante una risposta, `/prompt spiega …`.
- Agente da solo: `python -m agent_service`, `/docs` nel browser, chiamata a mano da PowerShell (`Invoke-RestMethod` su `/chat` con una domanda che usa uno strumento) con risposta e traccia nei log; `/stato` con LM Studio spento (503 e messaggio) e con il modello acceso.
- Docker: `docker compose build`, `docker compose run --rm app`, una domanda con strumento; `docker compose logs agent` mostra la traccia.
- Esiti nel README, come per gli step precedenti.

## 7. Ordine di lavoro e branch

Branch `feature/agente-servizio` da `developer`; incrementi piccoli verificati prima di ogni commit; merge `--no-ff` in `developer`, push, branch eliminato. README e `CLAUDE.md` (struttura, comandi) aggiornati.

## 8. Scelte fatte da Claude (da rivedere)

- FastAPI per l'agente, come il servizio delle note; SSE scritto a mano senza nuove dipendenze.
- Nuovo pacchetto `agent_service/`; il cuore dell'agente resta in `assistant/`.
- Due endpoint del turno (`/chat` JSON e `/chat/stream` SSE) sulla stessa funzione; `/chat` serve ai test, a OpenAPI e allo step 7.
- Schema dei messaggi proprio, in italiano, senza messaggio di sistema.
- Conferma con turno sospeso e ripresa dagli strumenti, controllo prima di eseguire qualsiasi strumento del messaggio.
- Codici HTTP della tabella 5.6.
- Endpoint dei prompt sull'agente (la CLI non parla più con il server MCP).
- Un turno alla volta (lock).
- Servizio `agent` separato in Docker Compose già in questo step.
- Porta predefinita 8001.
- Il vecchio modo «tutto in un processo» sparisce.
- Agente che parte anche con il modello spento, ma non senza server MCP o servizio note (5.5).
- Nessuna riconnessione automatica: con un collegamento caduto si riavvia l'agente (5.5).
- Decisioni sulle eliminazioni valide per tutto il turno; risposta finale che copre tutto il turno anche dopo una ripresa (5.4).

## 9. Lasciato al piano

- Nomi esatti dei campi e dei modelli Pydantic, forma della `ripresa` (con o senza `messaggi`).
- Come portare gli eventi dal thread del grafo alla risposta in streaming e come accorgersi della disconnessione.
- Dove stanno l'avvio condiviso (agente e note) e i testi d'errore.
- Ordine degli incrementi.
