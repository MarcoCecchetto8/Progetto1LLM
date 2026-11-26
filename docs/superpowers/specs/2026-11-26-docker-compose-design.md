# Step 9 — Docker Compose a quattro container

## 1. Intento

Slide 16 della lezione 6: un solo comando (`docker compose up`) avvia l'intera applicazione, pronta all'uso dal browser. Front-end, back-end, agente e database hanno ciascuno il proprio container; LM Studio resta sull'host. Evidenze richieste (slide 19): `docker compose up` avvia i quattro servizi e `docker compose ps` li mostra attivi; chat dal browser con uno strumento, visibile nei log dell'agente; dopo `down` e `up` le chat sono ancora presenti.

## 2. Obiettivi, non obiettivi, anti-obiettivi

- **Obiettivi:** quattro servizi in `compose.yaml` (`frontend`, `backend`, `agent`, `db`), tre con il proprio Dockerfile e PostgreSQL con l'immagine ufficiale; il browser raggiunge il front-end e il back-end; l'agente non è esposto; volume per i dati di PostgreSQL; credenziali solo nel `.env` escluso da Git; back-end avviato a database pronto; l'agente raggiunge LM Studio con `host.docker.internal` e avvia nel suo container il server MCP (stdio) e il servizio delle note.
- **Non obiettivi:** proxy nel front-end, HTTPS, autenticazione, riavvio automatico dei container, immagini pubblicate su un registro, containerizzare LM Studio.
- **Anti-obiettivi:** cambiare il comportamento dell'applicazione o le API; un quinto container acceso da `docker compose up`; porte raggiungibili da altri computer.

## 3. Approcci considerati (scelte dell'utente)

- **Servizio delle note — A (scelto):** lo avvia l'agente dentro il proprio container, come in locale quando `NOTES_SERVICE_URL` è vuota (`LocalNotesService`, `127.0.0.1:8000` interno al container, database `/app/data/notes.db` sulla cartella montata `./data`). B, un quinto container `notes`, scartato: la slide vuole quattro container.
- **Browser → back-end — porta pubblicata (scelta):** front-end `127.0.0.1:8003`, back-end `127.0.0.1:8002`, CORS già presente. Il proxy nel front-end è scartato: più codice (anche per inoltrare lo streaming SSE), un salto in più, nessuna sicurezza in più perché il back-end non ha autenticazione in nessuno dei due casi.

## 4. Architettura

| Servizio | Dockerfile | Codice copiato | Porta sull'host | Note |
|---|---|---|---|---|
| `db` | immagine `postgres:18.6-alpine` | — | `127.0.0.1:5433` (per le prove locali e i test con PostgreSQL vero) | volume `pgdata`, healthcheck come oggi |
| `agent` | `agent_service/Dockerfile` | `assistant/`, `lab_server/`, `notes_service/`, `agent_service/`, `config/` | **nessuna** | `env_file: .env`; `LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1`; `NOTES_SERVICE_URL` non impostata (servizio delle note avviato dall'agente); monta `./data:/app/data` e `./config/preferenze.json` in sola lettura; `extra_hosts` come oggi |
| `backend` | `backend_service/Dockerfile` | `assistant/__init__.py`, `assistant/agent_http.py`, `backend_service/` | `127.0.0.1:8002` | niente `env_file`: `DATABASE_URL=postgresql://db:5432` con `PGUSER`, `PGPASSWORD`, `PGDATABASE` dalle `POSTGRES_*` del `.env` (libpq le legge dall'ambiente, la password non va codificata nell'URL; corretto dopo la revisione finale), `BACKEND_AGENT_URL=http://agent:8001`; `depends_on: db` con `condition: service_healthy` |
| `frontend` | `frontend_service/Dockerfile` | `frontend_service/` (con `static/`) | `127.0.0.1:8003` | `FRONTEND_BACKEND_URL` predefinita `http://127.0.0.1:8002` (indirizzo visto dal browser, non dal container) |
| `app` (CLI) | `agent_service/Dockerfile` | come l'agente | nessuna | `profiles: ["cli"]`: `docker compose up` non la avvia; `docker compose run --rm app` sì (`AGENT_SERVICE_URL=http://agent:8001`) |

- I tre servizi ascoltano su `0.0.0.0` dentro la rete di Compose (`--host 0.0.0.0`); l'agente è raggiungibile solo da `backend` e `app` con il nome `agent`.
- **Dipendenze per immagine:** `requirements.txt` resta l'elenco completo (agente e sviluppo locale). Due file nuovi con le sole dipendenze dirette, stesse versioni: `requirements-backend.txt` (fastapi, uvicorn, httpx, psycopg[binary], python-dotenv) e `requirements-frontend.txt` (fastapi, uvicorn, python-dotenv). Un test controlla che ogni versione coincida con `requirements.txt`.
- Ogni immagine: `python:3.14-slim`, `PYTHONUNBUFFERED=1`, `pip install --no-cache-dir -r <file>`, utente non root `appuser`, `CMD` del proprio servizio. Il `Dockerfile` nella radice si elimina (la CLI usa l'immagine dell'agente).
- `.dockerignore` invariato (esclude `.env`, `.venv`, `tests`, `docs`, `lezione-03`…).

## 5. Comportamento

- `docker compose up -d --build` (o `docker compose build` e poi `docker compose up -d`): partono `db`, poi `backend` quando `db` è sano; `agent` e `frontend` subito. `docker compose ps` mostra i quattro servizi; l'agente senza porte.
- Se LM Studio è spento l'agente parte lo stesso e resta acceso (comportamento di oggi: avviso `[modello] …`); il `/stato` del back-end risponde 503 e la pagina mostra l'errore del modello; basta accendere LM Studio. (Corretto dopo la revisione finale: la prima stesura diceva che l'agente esce.)
- Le chat stanno nel volume `pgdata` (sopravvivono a `down`/`up`, non a `down -v`); le note in `data/notes.db` sull'host, condivise con l'avvio locale.
- Avvio locale e Docker non vanno usati insieme: vogliono le stesse porte (8002, 8003; e 8000/8001 dell'avvio locale dentro e fuori). Il README lo dice.

## 6. Test e verifiche

- **Automatici (senza Docker):** test delle versioni di `requirements-backend.txt` e `requirements-frontend.txt` contro `requirements.txt`. Suite completa prima del merge.
- **Docker (Claude, senza modello):** `docker compose config` valido; `docker compose build`; `docker compose up -d`; `docker compose ps` con quattro servizi; `127.0.0.1:8003` risponde 200, `127.0.0.1:8002/stato` risponde, `127.0.0.1:8001` non risponde dall'host; dentro la rete il back-end raggiunge l'agente.
- **Prova reale (utente, con LM Studio):** chat dal browser con uno strumento e riga `[api] strumento …` in `docker compose logs agent`; `docker compose down` e `docker compose up -d`, chat ancora presenti; eliminazione di una nota con conferma. Esiti nel README.

## 7. Scelte fatte da Claude

- Dockerfile dentro la cartella di ogni servizio (contesto di build la radice del progetto).
- `requirements-backend.txt`/`requirements-frontend.txt` con test di coerenza, invece di installare tutto in ogni immagine (immagini più piccole, build più veloci).
- `DATABASE_URL` del back-end composta da Compose; il back-end non riceve il `.env`. L'agente continua a ricevere il `.env` intero (contiene anche la password del db, non la usa): limite accettato e scritto nel README.
- CLI `app` con il profilo `cli`, sull'immagine dell'agente; `Dockerfile` della radice eliminato.
- Porta del db sempre pubblicata su `127.0.0.1:5433`.
- Nessuna politica di riavvio.
