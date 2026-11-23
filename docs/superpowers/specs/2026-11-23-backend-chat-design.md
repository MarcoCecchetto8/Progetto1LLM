# Back-end: API e salvataggio delle chat (lezione 6, step 7) — specifica

Data: 2026-11-23. Stato: approvata dall'utente il 2026-11-23.

## 1. Intento

Il front-end dello step 8 parlerà **solo con un back-end**. Il back-end gestisce le chat, le salva in PostgreSQL e inoltra le domande all'agente HTTP dello step 6 (`agent_service`, porta 8001). Le conversazioni restano disponibili dopo il riavvio e il front-end non conosce l'agente (né i suoi dettagli interni, come lo stato sospeso delle conferme).

## 2. Obiettivi (slide 14) ed evidenze

| Operazione | Comportamento atteso |
|---|---|
| Creare una chat | Restituisce l'identificativo della nuova chat |
| Elencare le chat | Titolo e data dell'ultimo messaggio |
| Leggere una chat | Messaggi in ordine cronologico |
| Inviare un messaggio | Salva la domanda, chiama l'agente, salva e restituisce la risposta |
| Eliminare una chat | Rimuove la chat e i suoi messaggi |

Evidenze richieste: documentazione OpenAPI generata e consultabile; agente non raggiungibile → errore chiaro e comportamento documentato; test con l'agente simulato; chat ancora presenti dopo il riavvio.

**Non obiettivi** (non anticipare): front-end (step 8); container del back-end e sistemazione a quattro container con agente non esposto (step 9); prompt MCP via back-end; autenticazione e più utenti; modifica del titolo; ricerca nelle chat; riconnessione automatica. La CLI **resta client dell'agente** e non usa il back-end (conversazione di sessione, senza salvataggio, come oggi).

**Anti-obiettivi**: duplicare nel back-end la logica del grafo; far conoscere al front-end lo stato sospeso dell'agente; salvare risposte a metà o domande senza risposta.

## 3. Scelte dell'utente (in chat, 2026-11-23)

1. **Conferma delle eliminazioni (A)**: lo stato sospeso resta nel back-end, legato alla chat; il front-end riceve solo le domande di conferma e risponde con un endpoint di conferma.
2. **Streaming (1)**: il back-end offre l'invio del messaggio sia in JSON sia in SSE (inoltro degli eventi dell'agente); salva il messaggio completo solo alla fine. Con il revisore attivo il back-end inoltra tutto com'è (anche le bozze); che cosa mostrare lo decide lo step 8.
3. **Accesso al database (1)**: SQL scritto a mano con **psycopg 3 sincrono** (`psycopg[binary]`, versione fissata nel piano), tabelle create all'avvio con `CREATE TABLE IF NOT EXISTS`, senza ORM né migrazioni. Test automatici con un archivio in memoria con la stessa interfaccia; test sul PostgreSQL vero separati e attivati esplicitamente.
4. **PostgreSQL in Docker già ora**: servizio `db` in `compose.yaml` (immagine ufficiale `postgres:18.6-alpine`, già presente), volume per i dati, credenziali nel `.env`. Il back-end si avvia in locale con `python -m backend_service` (porta 8002).

## 4. Approcci considerati

- **Accesso al database**: (1) psycopg con SQL a mano — scelto: una dipendenza, stesso stile di `notes_service/store.py`; (2) SQLAlchemy + Alembic — più librerie e codice di contorno per due tabelle; (3) SQLite — scartato, la slide chiede PostgreSQL.
- **Conferme**: (A) sospeso nel back-end — scelto; (B) sospeso passato al front-end — il front-end conoscerebbe un dettaglio dell'agente; (C) eliminazioni rifiutate dal web — perde una funzione.
- **Streaming**: (1) JSON + SSE subito — scelto; (2) solo JSON, streaming allo step 8 — riaprirebbe il back-end.

## 5. Architettura

Nuovo pacchetto `backend_service/` (stessa forma di `notes_service/` e `agent_service/`):

- `store.py`: archivio delle chat. Un'interfaccia (classe) con implementazione PostgreSQL (psycopg, query parametrizzate, una connessione per operazione come lo store delle note, o un pool se il piano lo motiva) e un archivio in memoria per i test (in `tests/` o nel pacchetto: decide il piano).
- `schemas.py`: schemi JSON in italiano per OpenAPI.
- `app.py`: endpoint FastAPI (`create_app(store, agent)`).
- `__main__.py`: avvio con uvicorn (`--host`, `--port 8002`, `--quiet`), lettura di `DATABASE_URL` e dell'indirizzo dell'agente.
- Client dell'agente: si **riusa** il client HTTP della CLI senza copiarlo. Oggi `assistant/agent_client.py` importa `assistant.mcp_client` (e quindi LangChain e MCP) per i tipi dei prompt. Per questo la parte HTTP (`parse_sse`, lettura delle righe SSE, `AgentUnavailable`, `AgentRequestError`, richieste di turno in JSON e in streaming, `/stato`) si **sposta in un modulo leggero** che importa solo `httpx` (es. `assistant/agent_http.py`). `agent_client.py` lo importa e tiene la traduzione dei prompt (`MCPPromptError`, `PromptInfo`) e `LocalAgentService`. Il comportamento della CLI non cambia e i suoi test restano verdi; si possono aggiornare solo gli import nei test. È una scelta di Claude: l'alternativa, accettare l'import indiretto, porterebbe tutto lo stack LLM nel back-end.

Il back-end non importa il grafo, LangChain o il client MCP, nemmeno indirettamente (con un test che lo controlla): parla con l'agente solo via HTTP. La cronologia dell'agente la conserva in JSON così come la riceve (formato `Message` dello step 6), senza interpretarla.

## 6. Dati

Tabella `chat`:

| Colonna | Tipo | Note |
|---|---|---|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY` primary key | identificativo intero |
| `titolo` | `TEXT NOT NULL` | vedi sotto |
| `creata` | `TIMESTAMPTZ NOT NULL` | |
| `ultimo_messaggio` | `TIMESTAMPTZ` | null finché non c'è un messaggio |
| `cronologia` | `JSONB NOT NULL DEFAULT '[]'` | cronologia dell'agente (formato `Message`) |
| `riassunto` | `TEXT NOT NULL DEFAULT ''` | riassunto in vigore |
| `in_sospeso` | `JSONB` | null, oppure `{sospeso, domanda, conferme}` (6.2) |

Tabella `messaggio`:

| Colonna | Tipo | Note |
|---|---|---|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY` primary key | ordina i messaggi |
| `chat_id` | `BIGINT NOT NULL REFERENCES chat(id) ON DELETE CASCADE` | eliminare la chat elimina i messaggi |
| `ruolo` | `TEXT NOT NULL` | `utente` o `assistente` |
| `contenuto` | `TEXT NOT NULL` | testo mostrato |
| `strumenti` | `JSONB NOT NULL DEFAULT '[]'` | solo per l'assistente: strumenti del turno (nome, argomenti, esito, errore) come li restituisce l'agente |
| `righe` | `JSONB NOT NULL DEFAULT '[]'` | solo per l'assistente: righe informative del turno (revisore, riassunto, rifiuto, limite), salvate perché lo schema non ha migrazioni e lo step 8 potrebbe volerle mostrare |
| `creato` | `TIMESTAMPTZ NOT NULL` | |

Indice su `messaggio(chat_id, id)`.

### 6.1 Messaggi mostrati e cronologia dell'agente

Sono due cose distinte:

- i **messaggi** sono quelli da mostrare: la domanda dell'utente e la risposta finale dell'agente (con l'avviso dei falsi successi, se c'è) e gli strumenti usati;
- la **cronologia** e il **riassunto** sono quelli che l'agente restituisce a turno completato; il back-end li sostituisce interamente e li rimanda al turno successivo. La cronologia può essere già riassunta, quindi non coincide con i messaggi mostrati.

### 6.2 Titolo

Alla creazione `titolo` è «Nuova chat» (o il titolo facoltativo passato nella richiesta, ripulito dagli spazi, massimo 100 caratteri). Al primo turno completato, se il titolo è ancora quello predefinito, diventa la prima domanda ridotta a una riga e troncata a 60 caratteri con «…».

## 7. Endpoint

Prefisso `/chats`. Corpi e risposte JSON con `charset=utf-8` (come l'agente, per PowerShell 5.1). Errori come `{codice, messaggio}` in italiano.

| Metodo e percorso | Che cosa fa | Risposta |
|---|---|---|
| `POST /chats` | Crea una chat (corpo facoltativo `{titolo}`) | 201 `{id, titolo, creata, ultimo_messaggio}` |
| `GET /chats` | Elenca le chat, prima quella con l'attività più recente (`ultimo_messaggio`, altrimenti `creata`) | 200 lista di `{id, titolo, creata, ultimo_messaggio}` |
| `GET /chats/{id}` | Legge una chat | 200 `{id, titolo, creata, ultimo_messaggio, messaggi: [...], conferme: [...]}`; `conferme` non vuoto se c'è una conferma in attesa |
| `DELETE /chats/{id}` | Elimina chat e messaggi | 204 |
| `POST /chats/{id}/messaggi` | Invia una domanda `{testo}`; risposta tutta insieme | 200 (7.1) |
| `POST /chats/{id}/messaggi/stream` | Stessa cosa, eventi SSE | 200 `text/event-stream` (7.2) |
| `POST /chats/{id}/conferma` | Decisioni sulle eliminazioni `{decisioni: {id_nota: bool}}` | 200 come l'invio (7.3) |
| `POST /chats/{id}/conferma/stream` | Stessa cosa, eventi SSE | 200 `text/event-stream` |
| `GET /stato` | Database e agente raggiungibili | 200 o 503 (7.5) |
| `GET /docs`, `GET /openapi.json` | Documentazione OpenAPI | automatica |

Ogni messaggio in uscita: `{id, ruolo, contenuto, strumenti, righe, creato}`.

### 7.1 Invio di un messaggio

1. Chat inesistente → 404 `chat_non_trovata`. Testo vuoto (dopo `strip`) → 422. Turno già in corso sulla stessa chat → 409 `turno_in_corso`. Conferma in attesa → 409 `conferma_in_attesa` («Rispondi prima alla conferma in attesa.»).
2. Il back-end chiama l'agente con `messaggi = [{ruolo: utente, contenuto: testo}]`, la `cronologia` e il `riassunto` salvati.
3. Esito `completato`: in **una sola transazione** salva il messaggio dell'utente e quello dell'assistente (con gli strumenti), sostituisce cronologia e riassunto, aggiorna `ultimo_messaggio` ed eventualmente il titolo. Risposta: `{esito: "completato", domanda: <messaggio salvato>, risposta: <messaggio salvato>, righe}`.
4. Esito `conferma_richiesta`: salva in `in_sospeso` lo stato sospeso dell'agente, la domanda e le conferme; **nessun messaggio salvato** ancora. Risposta: `{esito: "conferma_richiesta", conferme: [{id_nota, domanda}]}` — **senza** lo stato sospeso.
5. Errore dell'agente o agente non raggiungibile: **nulla viene salvato** (né domanda né risposta), la chat resta com'era e la risposta è l'errore (7.4). È il «comportamento documentato»: il front-end può mostrare l'errore e far riprovare.

Scostamento consapevole dall'ordine della slide («salva la domanda, chiama l'agente…»): domanda e risposta si salvano insieme alla fine, così una domanda non resta mai senza risposta e la cronologia dell'agente resta coerente con i messaggi. Va scritto nel README.

### 7.2 Streaming

`POST /chats/{id}/messaggi/stream` fa gli stessi controlli di 7.1 **prima** di aprire lo stream (quindi 404/409/422 sono normali risposte HTTP). Poi inoltra gli eventi dell'agente così come arrivano (`ragionamento`, `risposta`, `strumento`, `esito_strumento`, `riga`), con queste eccezioni:

- l'evento `fine` dell'agente **non** viene inoltrato così com'è: il back-end salva (7.1 punti 3–4) e manda il proprio `fine` con lo stesso corpo di `POST /chats/{id}/messaggi` (quindi senza cronologia né stato sospeso);
- l'evento `errore` dell'agente viene inoltrato (`{codice, messaggio}`) e non si salva nulla;
- agente non raggiungibile o connessione caduta a metà → evento `errore` `agente_non_raggiungibile` e nulla salvato;
- keepalive (commento SSE) se l'agente tace a lungo, come fa l'agente (il piano decide se basta inoltrare i suoi).

**Interruzione**: se il client chiude la connessione **prima** che arrivi il `fine` dell'agente, il back-end chiude lo stream verso l'agente (che ferma il turno, come per la CLI) e non salva nulla. Se il `fine` dell'agente è **già arrivato**, il back-end **salva comunque**: le azioni del turno (una nota creata o eliminata) sono già avvenute, e scartarle porterebbe a ripeterle. Per questo il salvataggio non deve dipendere dal generatore dello stream, che dopo una disconnessione può non riprendere: si esegue nel punto che riceve il `fine` (es. il thread che legge dall'agente) prima di inoltrarlo, con un test dedicato. Il segno «turno in corso» si toglie in ogni caso.

### 7.3 Conferma

`POST /chats/{id}/conferma` (e `/conferma/stream`): senza conferma in attesa → 409 `nessuna_conferma`. Le decisioni devono coprire esattamente gli `id_nota` delle conferme in attesa, altrimenti 422 `decisioni_non_valide`. Il back-end chiama l'agente con `ripresa = {sospeso, decisioni}`. Poi come 7.1:

- `completato`: salva la domanda tenuta in `in_sospeso` e la risposta, svuota `in_sospeso`, aggiorna cronologia e riassunto;
- nuova `conferma_richiesta` (seconda eliminazione nello stesso turno): sostituisce `in_sospeso` (stessa domanda, nuovo sospeso e nuove conferme);
- errore o interruzione: `in_sospeso` **resta** com'era, così la conferma si può ripetere.

`GET /chats/{id}` mostra le conferme in attesa (per il front-end che si riapre a metà). La domanda in attesa non compare tra i messaggi finché il turno non è completato (scelta di Claude: il front-end può mostrarla dalle conferme; da rivedere allo step 8 se serve).

### 7.4 Errori

| Situazione | HTTP | `codice` | Messaggio |
|---|---|---|---|
| Chat inesistente | 404 | `chat_non_trovata` | «La chat N non esiste.» |
| Turno già in corso sulla chat | 409 | `turno_in_corso` | «C'è già una risposta in corso in questa chat: attendi che finisca.» |
| Conferma in attesa | 409 | `conferma_in_attesa` | «Rispondi prima alla conferma in attesa.» |
| Nessuna conferma in attesa | 409 | `nessuna_conferma` | «Non c'è nessuna conferma in attesa in questa chat.» |
| Decisioni incomplete o in più | 422 | `decisioni_non_valide` | elenco degli id attesi |
| Richiesta non valida (schema) | 422 | quello di FastAPI | messaggio di validazione |
| Agente non raggiungibile | 503 | `agente_non_raggiungibile` | «L'agente non risponde: controlla che sia avviato (python -m agent_service) e riprova.» |
| Errore restituito dall'agente | stesso HTTP dell'agente | stesso `codice` | stesso `messaggio` (es. `modello_non_raggiungibile`, `modello_timeout`) |
| Risposta dell'agente non comprensibile | 502 | `risposta_agente_non_valida` | messaggio breve |
| Database non raggiungibile durante il funzionamento | 503 | `database_non_raggiungibile` | «Il database non risponde: controlla che PostgreSQL sia avviato.» |
| Errore imprevisto | 500 | `errore_imprevisto` | con traceback nei log |

Alcuni messaggi dell'agente nominano la CLI («usa 'clear'», «riavvia l'assistente»): si inoltrano così come sono in questo step; adattarli è lasciato allo step 8 (annotato nel README).

### 7.5 Stato

`GET /stato` → `{backend: "ok", database: {raggiungibile, messaggio}, agente: {raggiungibile, messaggio, dettagli}}`; `dettagli` è il corpo di `GET /stato` dell'agente se risponde. 200 se database e agente rispondono e l'agente dice 200, altrimenti 503 con lo stesso corpo.

## 8. Avvio, configurazione e Docker

- `python -m backend_service [--host 127.0.0.1] [--port 8002] [--quiet]`. All'avvio si collega al database e crea le tabelle; **se il database non risponde esce con codice 1** e un messaggio chiaro su stderr. L'agente invece **non serve all'avvio**: senza agente il back-end parte, elenca e legge le chat; l'invio dà `agente_non_raggiungibile` (è l'evidenza richiesta).
- Il back-end **non avvia** l'agente da solo (diversamente dalla CLI): si avvia a parte con `python -m agent_service`.
- Variabili nuove in `.env.example` (senza credenziali vere):
  - `DATABASE_URL=postgresql://lab:cambiami@127.0.0.1:5432/lab` (per il back-end in locale);
  - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (per il container `db`);
  - `BACKEND_AGENT_URL` (indirizzo dell'agente per il back-end, predefinito `http://127.0.0.1:8001`). Variabile distinta da `AGENT_SERVICE_URL`, che per la CLI vuota significa «avvia l'agente da solo».
- `compose.yaml`: nuovo servizio `db` (`postgres:18.6-alpine`, `env_file: .env`, volume con nome per `/var/lib/postgresql`, porta `127.0.0.1:5432:5432` per il back-end in locale, healthcheck con `pg_isready`). Niente servizio del back-end né modifiche ad `agent`/`app` (step 9).
- Dipendenza nuova: `psycopg[binary]` con versione fissata in `requirements.txt` (motivo: driver PostgreSQL per Python, sincrono, senza compilazione su Windows).
- `Dockerfile`: copiare anche `backend_service/` solo se serve al build già oggi; altrimenti allo step 9 (decide il piano, senza anticipare).

## 9. Log e concorrenza

- Log a INFO: `[backend] invio chat N: …` (inizio, esito, durata), `[backend] conferma chat N`, `[backend] chat N creata/eliminata`, errori dell'agente con codice. Accessi di uvicorn come gli altri servizi (`--quiet` li toglie).
- Un turno per chat alla volta: insieme in memoria delle chat con un turno in corso (protetto da un lock); una seconda richiesta sulla stessa chat → 409. Chat diverse possono inviare insieme: l'agente le serializza già (limite documentato). Il back-end è un solo processo, quindi l'insieme in memoria basta (limite nel README).
- Chat eliminata mentre un suo turno è in corso: l'eliminazione riesce; a fine turno il salvataggio trova la chat assente, non salva nulla e lo registra nei log (la risposta al client resta l'esito dell'agente, oppure `chat_non_trovata`: decide il piano, con test).

## 10. Test e verifiche

### Test automatici (senza modello, senza agente, senza database)

- Archivio in memoria: creazione, elenco ordinato, lettura, eliminazione a cascata, turno completato salvato in blocco, `in_sospeso`, titolo dalla prima domanda.
- API con archivio in memoria e agente simulato (`httpx.MockTransport` passato all'`AgentClient`): ogni endpoint e ogni riga della tabella degli errori; agente non raggiungibile → 503 e nulla salvato; errore dell'agente inoltrato; conferma (sospeso mai esposto, ripresa, seconda sospensione, errore che lascia `in_sospeso`); 409 per turno in corso; streaming con inoltro degli eventi, `fine` del back-end, errore a metà, interruzione senza salvataggio.
- OpenAPI: `/openapi.json` contiene i percorsi.

### Test con PostgreSQL vero (attivati esplicitamente)

- Marcati (es. `@pytest.mark.postgres`) e saltati se non è impostata `TEST_DATABASE_URL`; stessa batteria dell'archivio in memoria contro PostgreSQL, compresa la persistenza dopo aver ricreato l'oggetto archivio (riavvio simulato).

### Prova reale (separata, con LM Studio)

`docker compose up -d db`, `python -m agent_service`, `python -m backend_service`, poi da PowerShell (`Invoke-RestMethod`) o da `/docs`: creare una chat, domanda con uno strumento (ora o calcolo), lettura della chat, riavvio del back-end e chat ancora presente, `docker compose down`/`up -d db` e chat ancora presente, eliminazione di una nota con conferma, agente spento → errore chiaro, streaming con `curl.exe -N`. Esiti nel README.

## 11. Documentazione

- README: sezione del back-end (avvio, variabili, endpoint, comportamento con agente spento, salvataggio a fine turno, limiti).
- CLAUDE.md: struttura con `backend_service/`, comandi, e l'obiettivo «nessuna persistenza» aggiornato (la CLI resta di sessione; le chat del back-end sono salvate in PostgreSQL).

## 12. Scelte fatte da Claude (da rivedere)

- Pacchetto `backend_service/`, porta 8002, `BACKEND_AGENT_URL` distinta da `AGENT_SERVICE_URL`.
- Domanda e risposta salvate insieme a fine turno; nulla salvato in caso di errore o interruzione.
- Nuovo messaggio con conferma in attesa → 409 (non annulla la conferma).
- Identificativi interi; titolo dalla prima domanda (60 caratteri); elenco ordinato per attività più recente.
- Il back-end non avvia l'agente; senza database non parte, senza agente sì.
- Messaggi d'errore dell'agente inoltrati invariati.
- CLI invariata, client dell'agente.
- Parte HTTP del client dell'agente spostata in un modulo leggero, condiviso da CLI e back-end (5).
- Righe informative del turno salvate con la risposta (colonna `righe`).
- Disconnessione del client dopo il `fine` dell'agente: si salva comunque (7.2).

## 13. Lasciato al piano

Pool di connessioni o connessione per operazione; dove sta l'archivio in memoria; versione esatta di psycopg; forma del keepalive; registrazione del marcatore pytest; esito per chat eliminata durante un turno; eventuale metodo JSON aggiunto ad `AgentClient`.
