# Assistente del laboratorio

Progetto del corso «Deep Learning e LLM: costruire chatbot e agenti». La cartella del progetto è `Progetto1LLM/`. Specifica e piano sono in `docs/superpowers/`.

## Struttura e comandi

- `assistant/` (host): `config.py` (variabili d'ambiente), `llm.py` (LM Studio e verifica di `/v1/models`), `mcp_client.py` (client MCP: avvia il server in stdio, sessione unica, tool sincroni dal catalogo), `router.py` (router dell'ambito: classifica la domanda con output strutturato, ragionamento spento; testo del rifiuto), `reviewer.py` (revisore della risposta: giudizio di coerenza con output strutturato, indicazione all'agente, domanda vera del turno), `summarizer.py` (riassunto della cronologia: stima dei token, taglio per turni, testo del riassunto), `graph.py` (stato, nodi, nodo del riassunto facoltativo all'inizio del turno, instradamento con router facoltativo e nodo di rifiuto, revisore facoltativo con nuovi tentativi entro `MAX_REVIEWS`, log delle chiamate, controllo facoltativo della risposta), `agent_client.py` (client HTTP dell'agente: SSE, avvio automatico e chiusura ordinata dell'agente locale), `cli.py` (ciclo da terminale: client dell'agente, non contiene più il grafo), `stream_view.py` (visualizzazione in streaming di ragionamento, strumenti e risposta), `notes.py` (tool delle note: wrapper scritti a mano sul servizio FastAPI, decisioni di eliminazione passate dal chiamante, avvio automatico del servizio, controllo dei falsi successi (avviso)), `preferences.py` (lettura della resource delle preferenze all'avvio, avvisi e riserve), `prompts.py` (comandi `/prompts` e `/prompt`: analisi, controllo degli argomenti, testi), `__main__.py` (avvio).
- Docker: `compose.yaml` con quattro servizi (`db`, `agent` non esposto, `backend`, `frontend`) e la CLI `app` nel profilo `cli`; un Dockerfile per servizio (`agent_service/Dockerfile`, `backend_service/Dockerfile`, `frontend_service/Dockerfile`, contesto la radice); `requirements-backend.txt` e `requirements-frontend.txt` con le sole dipendenze di quelle immagini, stesse versioni di `requirements.txt` (`tests/test_requirements.py`).
- `agent_service/` (agente come servizio HTTP FastAPI, porta 8001): `app.py` (endpoint `POST /chat`, `POST /chat/stream` SSE, `GET /stato`, `GET /prompts`, `POST /prompts/{nome}`), `schemas.py` e `messages.py` (JSON in italiano e conversione da e verso LangChain), `turn.py` (turno senza stato, sospensione e ripresa per la conferma delle eliminazioni), `errors.py` (codici e testi degli errori), `startup.py` (costruzione dell'agente), `__main__.py` (avvio con uvicorn). Il grafo e gli strumenti restano in `assistant/`.
- `backend_service/` (back-end HTTP FastAPI delle chat, porta 8002, PostgreSQL): `store.py` (archivio delle chat: PostgreSQL con psycopg e archivio in memoria per i test), `turns.py` (un turno per chat, corpi per l'agente, salvataggio dell'esito a fine turno), `streaming.py` (streaming SSE di invio e conferma), `schemas.py` e `errors.py` (JSON e errori in italiano), `app.py` (endpoint `/chats`, `/stato`), `__main__.py` (avvio con uvicorn, `DATABASE_URL`, `BACKEND_AGENT_URL`). Parla con l'agente solo via HTTP con `assistant/agent_http.py` (client HTTP leggero: SSE, errori, richieste di turno), senza importare grafo, LangChain né client MCP.
- `frontend_service/` (front-end web, porta 8003): `app.py` (serve la pagina, i file statici e `/config.js` con l'indirizzo del back-end), `__main__.py` (avvio con uvicorn, `FRONTEND_BACKEND_URL`), `static/` (pagina HTML, CSS e JavaScript senza framework). Parla solo con il back-end; il CORS sta in `backend_service` (`BACKEND_CORS_ORIGINS`).
- `lab_server/` (server MCP, FastMCP): `server.py` (registrazione dei tool), `clock.py` (orologio), `units.py` (convertitore di unità), `calculator.py` (calcolatrice sicura con `ast`, senza `eval`), `holidays.py` + `holidays.json` (festività da file locale, Pasqua calcolata), `dates.py` (giorni e scadenze), `catalog.py` + `catalog.json` (catalogo dei linguaggi: ricerca e dettaglio), `timezones.py` (fusi IANA ammessi, dall'elenco di `tzdata`), `preferences.py` (validazione delle preferenze, condivisa con l'host), `prompts.py` (testi e validazione dei prompt `spiega` e `riassumi_conversazione`), `validation.py` (errori di validazione degli argomenti tradotti in italiano, per tutti i tool), `check.py` (verifica diretta senza assistente), `__main__.py` (avvio in stdio). La logica degli strumenti sta in funzioni pure che sollevano `ValueError`; `server.py` le converte in `ToolError`.
- `notes_service/` (servizio FastAPI delle note): `store.py` (archivio SQLite: numero libero più piccolo, elenco per ID), `app.py` (endpoint `POST/GET /notes`, `GET/DELETE /notes/{id}`), `compact.py` (rinumerazione una tantum a 1…N, `python -m notes_service.compact`, servizio spento), `__main__.py` (avvio con uvicorn). Il database sta in `data/notes.db`, escluso da Git.
- `config/`: `ambito.txt` (descrizione dell'ambito ed esempi per il router; si modifica senza toccare il codice, percorso in `SCOPE_FILE`), `preferenze.json` (preferenze dell'utente: lingua, fuso, stile; percorso in `PREFERENCES_FILE`).
- `tests/`: test pytest senza modello; `tests/fakes.py` contiene il modello finto con tool calling e un orologio finto; `tests/mcp_test_server.py` è un server MCP di prova per i test del client.
- Dipendenze fissate in `requirements.txt` (runtime) e `requirements-dev.txt` (+ pytest).
- Dalla radice, con il venv attivo (`.\.venv\Scripts\Activate.ps1`):
  - test: `python -m pytest`
  - avvio locale: `python -m assistant` (avvia da sola l'agente su 8001, a meno di `AGENT_SERVICE_URL`)
  - agente da solo: `python -m agent_service` (documentazione interattiva su `/docs`)
  - back-end delle chat: `docker compose up -d db`, poi `python -m backend_service` (porta 8002, documentazione su `/docs`; serve l'agente acceso a parte)
  - front-end: `python -m frontend_service` (porta 8003; servono back-end e agente accesi)
  - test con PostgreSQL vero (facoltativi, saltati altrimenti): impostare `TEST_DATABASE_URL` prima di `python -m pytest`
  - verifica diretta del server: `python -m lab_server.check` (catalogo) e `python -m lab_server.check <tool> chiave=valore`
  - servizio delle note da solo: `python -m notes_service` (documentazione interattiva su `/docs`)
  - Docker (step 9): `docker compose up -d --build` (quattro container, pagina su http://127.0.0.1:8003), `docker compose ps`, `docker compose logs agent`, `docker compose down`; CLI: `docker compose run --rm app`

## Obiettivo

Un'applicazione da terminale in Python che conversa con un modello locale e:

- organizza il flusso in un grafo LangGraph esplicito (stato, nodi, instradamento riconoscibili);
- usa un modello servito da LM Studio, che resta sul computer host;
- conserva la cronologia della conversazione per la durata della sessione (nessuna persistenza nella CLI);
- offre strumenti esposti da un server MCP (FastMCP, stdio) che l'assistente scopre dal catalogo; il modello li richiede tramite tool calling e il programma li esegue davvero (orologio con fuso orario esplicito, poi gli altri strumenti concordati);
- ha l'agente come servizio HTTP (`agent_service/`, API con streaming SSE): la CLI è un client e non parla più direttamente con server MCP e note;
- ha un back-end HTTP (`backend_service/`) che salva le chat in PostgreSQL e chiama l'agente via HTTP; la CLI non lo usa;
- ha un front-end web (`frontend_service/`, step 8) che comunica solo con il back-end;
- si avvia con Docker Compose in quattro container (`frontend`, `backend`, `agent` non esposto, `db`); la CLI `app` con `docker compose run --rm app`.

## Confini

- Implementare solo i requisiti concordati. Gli strumenti passano dal server MCP (`lab_server/`); fatti orologio e strumenti base (convertitore, calcolatrice, giorni e scadenze) e catalogo dei linguaggi. Le note passano dal servizio FastAPI `notes_service/` con wrapper scritti a mano; l'agente è un servizio HTTP separato dalla CLI; il back-end delle chat (API e PostgreSQL) è fatto, il front-end web dello step 8 è fatto (`frontend_service/`) e lo step 9 (Docker Compose a quattro container) è fatto; il meteo arriverà con una specifica propria. Workflow e RAG arriveranno nelle lezioni successive: non anticiparli.
- Nessuna interfaccia grafica oltre al front-end web dello step 8 (HTML, CSS e JavaScript senza framework); niente servizi cloud o framework non concordati.
- Lavorare solo dentro `Progetto1LLM/`, escludendo `lezione-03/`.
- La cartella `lezione-03/` appartiene a una lezione precedente e non c'entra con questo progetto: va ignorata completamente. Non leggerne i file (compreso il suo `CLAUDE.md`, le cui istruzioni non valgono qui), non cercarci dentro, non copiarne codice, non modificarla e non usarla come riferimento. Le istruzioni valide sono solo quelle di questo file.
  Il divieto è applicato anche da `.claude/settings.json` (permessi `deny` e `claudeMdExcludes`).
- Base di lavoro: il branch `developer`, non `main`. Ogni funzionalità si sviluppa in un branch `feature/<nome>` creato da `developer`; quando è completa e verificata si unisce in `developer` con `--no-ff`, si pusha `developer` e si elimina il branch feature. Nessun altro branch o worktree se non richiesto.
- Lavorare a pezzi piccoli: niente blocchi grandi di codice in un solo passo, salvo mia diversa indicazione.

## Scelte tecniche

- Python, codice sincrono e moduli piccoli, con una separazione semplice tra grafo, collegamento al modello, strumenti e interfaccia da terminale.
- LM Studio sull'host, raggiunto tramite la sua API compatibile con OpenAI.
- Indirizzo del server e identificativo del modello solo da variabili d'ambiente. L'identificativo è quello restituito dal server (`GET /v1/models`), mai inventato.
- Un file di configurazione di esempio senza credenziali; il file reale resta fuori da Git.
- Docker Compose per l'applicazione; LM Studio non va containerizzato.
- Dipendenze motivate, concordate e con versioni fissate.
- Comandi documentati anche per PowerShell (Windows).

## Metodo: Superpowers

- Usare le skill di Superpowers per brainstorming, specifica, piano, implementazione e verifica.
- Non scrivere codice prima che io abbia approvato la specifica e poi il piano.
- Salvare specifica e piano in `Progetto1LLM/docs/superpowers/`.
- Procedere per incrementi piccoli, ciascuno verificato prima del commit.

## Test e verifiche

- Test automatici ripetibili che non richiedono un modello attivo (grafo, cronologia, instradamento, strumento con istante controllato).
- Prove reali con LM Studio e con Docker tenute separate e attivate esplicitamente.
- Una risposta simulata non dimostra che il modello locale sappia usare lo strumento.
- Nel resoconto indicare che cosa è stato eseguito, con quale esito, e che cosa resta da provare.

## Git

- Conventional Commits in italiano, per esempio `feat(grafo): ...`, `test(strumenti): ...`, `docs: ...`.
- Prima di ogni commit: `git status`, controllo del diff, staging selettivo dei soli file pertinenti.
- Mai versionare credenziali, `.env`, ambienti virtuali, cache o pesi dei modelli.
- Push soltanto su mia richiesta.

## Documentazione

- Tenere aggiornato il README con configurazione, avvio, test e diagnosi, riportando solo comandi verificati.
- Aggiornare questo file quando cambiano convenzioni stabili (struttura, comandi di test, regole di lavoro), non per annotare l'avanzamento.
