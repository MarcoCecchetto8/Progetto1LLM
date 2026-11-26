# Step 9 — Docker Compose a quattro container — piano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docker compose up` avvia `frontend`, `backend`, `agent` e `db`; l'agente non è esposto; la CLI resta disponibile con `docker compose run --rm app`.

**Architecture:** tre Dockerfile nelle cartelle dei servizi (contesto la radice), due file di dipendenze ridotte con test di coerenza, `compose.yaml` riscritto; nessun cambio al codice Python dei servizi.

**Tech Stack:** Docker Compose, `python:3.14-slim`, `postgres:18.6-alpine`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-26-docker-compose-design.md`

## Global Constraints

- Branch `feature/docker-compose` da `developer`. Conventional Commits in italiano, staging selettivo.
- Porte solo su `127.0.0.1`: `8003` front-end, `8002` back-end, `5433` db; agente senza `ports`.
- Nessuna nuova dipendenza; versioni identiche a `requirements.txt`.
- Credenziali solo nel `.env`; mai nei file versionati.
- Prima di `docker compose up` i servizi locali sulle porte 8000–8003 vanno spenti (chiedere all'utente).

## Review Focus

- `.env` dell'utente con password diversa da `cambiami`: `DATABASE_URL` del back-end deve venire dai suoi `POSTGRES_*` (controllo con `docker compose config`, Task 2).
- Agente acceso ma LM Studio spento: il back-end resta su e risponde con l'errore dell'agente (prova Task 2, `GET /stato` del back-end).
- Note dell'utente: il container dell'agente deve usare `data/notes.db` esistente, non un archivio nuovo (Task 2: `list_notes` restituisce le note 1…).
- `docker compose up` non deve avviare `app` (Task 2: `docker compose ps`).
- Back-end avviato prima che il db sia pronto: `depends_on` con `service_healthy` (Task 2: `docker compose config`).

---

### Task 1: dipendenze per immagine

**Files:**
- Create: `requirements-backend.txt`, `requirements-frontend.txt`, `tests/test_requirements.py`

- [ ] **Step 1: test che fallisce** `tests/test_requirements.py`: funzione `_pins(path) -> dict[str, str]` (nome normalizzato in minuscolo senza extra → riga intera, ignorando commenti e righe vuote); `test_image_requirements_match_full_list` parametrizzato su `requirements-backend.txt` e `requirements-frontend.txt`: ogni riga del file esiste identica in `requirements.txt`; `test_image_requirements_content`: backend = {fastapi, uvicorn, httpx, psycopg, python-dotenv}, frontend = {fastapi, uvicorn, python-dotenv}.
- [ ] **Step 2:** `python -m pytest tests/test_requirements.py -q` → FAIL (file mancanti).
- [ ] **Step 3:** creare i due file copiando le righe esatte da `requirements.txt` (`psycopg[binary]==3.3.9` con il commento).
- [ ] **Step 4:** stesso comando → PASS.
- [ ] **Step 5: commit** `build(docker): dipendenze ridotte per back-end e front-end`.

### Task 2: Dockerfile e compose

**Files:**
- Create: `agent_service/Dockerfile`, `backend_service/Dockerfile`, `frontend_service/Dockerfile`
- Modify: `compose.yaml`
- Delete: `Dockerfile`

- [ ] **Step 1: Dockerfile** come nella sez. 4 della spec: `FROM python:3.14-slim`, `ENV PYTHONUNBUFFERED=1`, `WORKDIR /app`, `COPY <requirements> .` + `pip install --no-cache-dir -r`, `COPY` del solo codice del servizio (back-end: `assistant/__init__.py` e `assistant/agent_http.py` in `./assistant/`), `useradd --create-home appuser`, `USER appuser`, `CMD ["python", "-m", "<servizio>", "--host", "0.0.0.0"]` (agente: `agent_service`; CLI sovrascrive con `command`).
- [ ] **Step 2: `compose.yaml`** secondo la tabella della spec: servizi `db` (invariato), `agent` (senza `ports`, senza `NOTES_SERVICE_URL`, `volumes` `./data:/app/data` e preferenze `:ro`, `extra_hosts`), `backend` (`environment` `DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}`, `BACKEND_AGENT_URL: http://agent:8001`; `depends_on: db: condition: service_healthy`; `127.0.0.1:8002:8002`), `frontend` (`127.0.0.1:8003:8003`), `app` (`build` con `dockerfile: agent_service/Dockerfile`, `profiles: ["cli"]`, `command: ["python", "-m", "assistant"]`, `AGENT_SERVICE_URL: http://agent:8001`, `depends_on: agent`, `stdin_open`, `tty`). Nessun servizio `notes`.
- [ ] **Step 3: verifica statica:** `docker compose config` → valido; nell'uscita `DATABASE_URL` con i valori del `.env`, `condition: service_healthy`, nessuna `ports` per `agent`; `docker compose config --services` → `agent backend db frontend` (senza `app`).
- [ ] **Step 4: build:** `docker compose build` → quattro immagini (agent, backend, frontend, app) senza errori.
- [ ] **Step 5: avvio (servizi locali spenti, LM Studio acceso):** `docker compose up -d`; `docker compose ps` → `db`, `agent`, `backend`, `frontend` in esecuzione, porte `127.0.0.1:8002`, `127.0.0.1:8003`, `127.0.0.1:5433`, agente senza porte; `curl http://127.0.0.1:8003/` → 200; `curl http://127.0.0.1:8002/stato` → risponde con agente raggiungibile; `curl -m 3 http://127.0.0.1:8001/` → nessuna risposta; `docker compose logs agent` → `[note] servizio: http://127.0.0.1:8000` e catalogo MCP.
- [ ] **Step 6: commit** `feat(docker): quattro container con agente non esposto`.

### Task 3: documentazione

**Files:**
- Modify: `README.md` (sezione «Avvio con Docker» riscritta: quattro servizi, comandi, porte, agente non esposto, CLI con `docker compose run --rm app`, LM Studio spento, `down -v` cancella le chat; righe della tabella di configurazione per `NOTES_SERVICE_URL`/`AGENT_SERVICE_URL`; limite: l'agente riceve il `.env` intero; sezione «Prova reale con Docker Compose» con le evidenze della slide, esiti «da fare»), `CLAUDE.md` (servizi di Compose, comandi Docker, struttura con i Dockerfile), `.env.example` (commento di `NOTES_SERVICE_URL`).

- [ ] **Step 1:** scrivere; solo comandi verificati nel Task 2.
- [ ] **Step 2: commit** `docs: avvio con Docker Compose a quattro container`.

### Task 4: verifica e chiusura

- [ ] **Step 1:** suite completa con le porte 8000–8003 libere (`docker compose down` prima): `python -m pytest` → exit 0.
- [ ] **Step 2: prova reale dell'utente** con `docker compose up -d`: chat dal browser con uno strumento e riga `[api] strumento …` in `docker compose logs agent`; eliminazione di una nota con conferma; `docker compose down`, `docker compose up -d`, chat ancora presenti. Esiti nel README, commit.
- [ ] **Step 3:** revisione finale dell'insieme, merge `--no-ff` in `developer`, push, eliminare il branch.
