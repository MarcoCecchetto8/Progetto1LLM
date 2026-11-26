# Front-end di chat (step 8) — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pagina web di chat (HTML/CSS/JS senza framework) servita da `frontend_service` (porta 8003), che parla solo con `backend_service` (porta 8002) via fetch + CORS.

**Architecture:** `frontend_service/` FastAPI serve `index.html`, `/static/*` e `/config.js` (URL del back-end da `FRONTEND_BACKEND_URL`). Il back-end aggiunge `CORSMiddleware` con origini da `BACKEND_CORS_ORIGINS`. La pagina usa gli endpoint di `/openapi.json` del back-end, con streaming SSE letto da `fetch`.

**Tech Stack:** Python 3.14, FastAPI 0.162.2, uvicorn 0.54.0 (già in `requirements.txt`), JavaScript del browser senza dipendenze, pytest.

**Spec:** `docs/superpowers/specs/2026-11-25-frontend-chat-design.md`

## Global Constraints

- Nessuna dipendenza nuova (Python o JavaScript), nessun npm, nessuna build, nessun font o script esterno.
- Testi dell'interfaccia e messaggi in italiano; `lang="it"`.
- Porta del front-end 8003; `FRONTEND_BACKEND_URL` predefinito `http://127.0.0.1:8002`; `BACKEND_CORS_ORIGINS` predefinito `http://127.0.0.1:8003,http://localhost:8003`.
- Il front-end chiama solo il back-end; non toccare `agent_service`, `assistant` (salvo nulla), grafo, note.
- Il codice segue lo stile del progetto: moduli piccoli, sincrono lato Python, commenti in italiano.
- Commit Conventional Commits in italiano, staging selettivo, con riga `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Test: `python -m pytest` dalla radice con il venv; durante i task solo i file toccati, la suite intera prima del merge (con agente/back-end spenti: le porte 8000–8003 devono essere libere).

## Review Focus

1. URL del back-end con caratteri speciali (virgolette, `</script>`) → `/config.js` resta JavaScript valido e non esegue nulla (test in Task 2).
2. Origine non ammessa (es. `http://evil.example`) → nessun `access-control-allow-origin`; preflight `OPTIONS` per `POST` JSON dell'origine ammessa → 200 con intestazioni (test in Task 1).
3. Percorsi usati da `app.js` che non esistono nel back-end (errori di battitura, metodo sbagliato) → test di contratto contro `/openapi.json` (Task 2).
4. Testo del modello con HTML (`<img onerror=…>`) → mostrato come testo, mai interpretato (renderer in Task 3, verifica a mano nel browser con una risposta che contiene `<b>`).
5. Back-end spento all'apertura o durante una risposta → avviso comprensibile, pagina utilizzabile, domanda rimessa nella casella (Task 3, prova reale).

---

### Task 1: CORS nel back-end

**Files:**
- Modify: `backend_service/app.py` (firma di `create_app`, middleware)
- Modify: `backend_service/__main__.py` (lettura di `BACKEND_CORS_ORIGINS`)
- Test: `tests/test_backend_cors.py`

**Interfaces:**
- Produces: `create_app(store: ChatStore, agent: AgentHTTPClient, cors_origins: list[str] | None = None) -> FastAPI` (con `None` o lista vuota: nessun middleware CORS, comportamento attuale); `backend_service.__main__.parse_cors_origins(value: str) -> list[str]` (divide su virgole, toglie spazi, scarta vuoti e barre finali; stringa vuota → predefinito `["http://127.0.0.1:8003", "http://localhost:8003"]`).

- [ ] **Step 1: test che falliscono** in `tests/test_backend_cors.py` (fixture come `make_client` di `tests/test_backend_api.py`, con `cors_origins=["http://127.0.0.1:8003"]`):
  - `test_allowed_origin_gets_cors_header`: `GET /chats` con `Origin: http://127.0.0.1:8003` → `access-control-allow-origin == "http://127.0.0.1:8003"`.
  - `test_preflight_for_json_post`: `OPTIONS /chats/1/messaggi/stream` con `Origin` ammessa, `Access-Control-Request-Method: POST`, `Access-Control-Request-Headers: content-type` → 200, `POST` in `access-control-allow-methods`, `content-type` in `access-control-allow-headers` (minuscolo).
  - `test_preflight_for_delete`: come sopra con `DELETE` su `/chats/1` → 200.
  - `test_other_origin_gets_no_cors_header`: `Origin: http://evil.example` → nessuna `access-control-allow-origin`.
  - `test_no_origins_no_middleware`: `create_app(store, agent)` senza origini → nessuna intestazione CORS con origine ammessa.
  - `test_parse_cors_origins`: `"  http://a:1/ , ,http://b:2"` → `["http://a:1", "http://b:2"]`; `""` → i due predefiniti.
- [ ] **Step 2:** `python -m pytest tests/test_backend_cors.py -q` → FAIL (argomento `cors_origins` sconosciuto / funzione assente).
- [ ] **Step 3:** in `create_app` aggiungere `CORSMiddleware(allow_origins=cors_origins, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"], allow_credentials=False)` se la lista non è vuota; in `__main__.main` passare `parse_cors_origins(os.environ.get("BACKEND_CORS_ORIGINS", ""))`.
- [ ] **Step 4:** `python -m pytest tests/test_backend_cors.py tests/test_backend_api.py tests/test_backend_stream.py -q` → tutti PASS.
- [ ] **Step 5:** commit `feat(backend): CORS per le origini del front-end` (file del task).

### Task 2: servizio del front-end (Python) e contratto

**Files:**
- Create: `frontend_service/__init__.py`, `frontend_service/app.py`, `frontend_service/__main__.py`
- Create (segnaposto minimi, completati nel Task 3): `frontend_service/static/index.html` (carica `/config.js`, `/static/style.css`, `/static/app.js`), `frontend_service/static/style.css`, `frontend_service/static/app.js`
- Test: `tests/test_frontend_service.py`

**Interfaces:**
- Produces: `frontend_service.app.create_app(backend_url: str) -> FastAPI`; `frontend_service.app.config_script(backend_url: str) -> str` che restituisce esattamente `"window.APP_CONFIG = " + <json> + ";\n"` dove `<json>` è `json.dumps({"backendUrl": url})` con `<`, `>`, `&` sostituiti da `<`, `>`, `&`; `frontend_service.__main__.backend_url_from_env(value: str) -> str` (vuoto → `http://127.0.0.1:8002`; senza `http://`/`https://` → `ValueError` con testo «FRONTEND_BACKEND_URL non valida: …»; barra finale tolta).
- Produces per il Task 3: la pagina legge `window.APP_CONFIG.backendUrl`; i file statici stanno sotto `/static/`.
- Produces: costante `tests/test_frontend_service.py::FRONTEND_CALLS` = elenco di coppie (metodo, percorso OpenAPI) usate da `app.js`: `("get","/chats")`, `("post","/chats")`, `("get","/chats/{chat_id}")`, `("delete","/chats/{chat_id}")`, `("post","/chats/{chat_id}/messaggi/stream")`, `("post","/chats/{chat_id}/conferma/stream")`. Il Task 3 non usa altri endpoint.

- [ ] **Step 1: test che falliscono** in `tests/test_frontend_service.py`:
  - `test_index_served`: `GET /` → 200, `text/html`, contiene `/config.js` e `/static/app.js`.
  - `test_static_files_served`: `GET /static/app.js` → 200 (JavaScript), `GET /static/style.css` → 200 (CSS).
  - `test_config_js_contains_backend_url`: `create_app("http://127.0.0.1:8002")`, `GET /config.js` → 200, `content-type` inizia con `text/javascript`, `cache-control == "no-store"`, corpo `== 'window.APP_CONFIG = {"backendUrl": "http://127.0.0.1:8002"};\n'`.
  - `test_config_js_escapes_dangerous_url`: URL `'http://x/"</script><script>alert(1)//'` → il corpo non contiene `</script>` né `"</`, e `json.loads` della parte tra `= ` e `;\n` dopo aver rimesso gli escape restituisce l'URL originale.
  - `test_backend_url_from_env`: `""` → `"http://127.0.0.1:8002"`; `"http://host:9/"` → `"http://host:9"`; `"host:9"` → `ValueError` con `"FRONTEND_BACKEND_URL non valida"`.
  - `test_main_exits_on_invalid_url` (monkeypatch di `load_dotenv` come nel test di `backend_service.__main__` in `tests/test_backend_api.py`, `FRONTEND_BACKEND_URL=host:9`, `sys.argv`) → `SystemExit` con codice 1 e messaggio su stderr.
  - `test_frontend_calls_exist_in_backend_openapi`: per ogni coppia di `FRONTEND_CALLS`, è in `backend_service.app.create_app(MemoryChatStore(), agent).openapi()["paths"][path]` con quel metodo.
  - `test_app_js_uses_only_known_paths`: nel testo di `static/app.js` ogni `"/chats` o `` `/chats`` letterale corrisponde a uno dei percorsi di `FRONTEND_CALLS` (regex `/chats(/\$\{[^}]+\})?(/messaggi/stream|/conferma/stream)?`, segnaposto `${…}` → `{chat_id}`). Con il segnaposto del Task 2 l'insieme è vuoto e il test passa; diventa significativo nel Task 3.
- [ ] **Step 2:** `python -m pytest tests/test_frontend_service.py -q` → FAIL (modulo assente).
- [ ] **Step 3:** implementare `app.py` (FastAPI con `StaticFiles` su `/static`, `FileResponse` per `/`, `Response` per `/config.js` con `media_type="text/javascript; charset=utf-8"`) e `__main__.py` (argparse `--host` 127.0.0.1, `--port` 8003, `--quiet`; `load_dotenv()`; `ValueError` → stampa su stderr e `SystemExit(1)`; uvicorn come in `backend_service/__main__.py`).
- [ ] **Step 4:** `python -m pytest tests/test_frontend_service.py -q` → PASS; `python -m frontend_service` parte e `http://127.0.0.1:8003/config.js` risponde (poi Ctrl+C).
- [ ] **Step 5:** commit `feat(frontend): servizio che serve la pagina e config.js`.

### Task 3: la pagina di chat (eseguito nella sessione principale, con la skill impeccable)

**Files:**
- Modify: `frontend_service/static/index.html`, `frontend_service/static/style.css`, `frontend_service/static/app.js`

**Interfaces:**
- Consumes: `window.APP_CONFIG.backendUrl` (Task 2); gli endpoint di `FRONTEND_CALLS` (Task 2); CORS (Task 1); eventi SSE del back-end: `strumento {nome, argomenti}`, `esito_strumento {nome, contenuto, errore}`, `risposta {testo}`, `riga {testo}`, `ragionamento {testo}` (ignorato), `fine {esito, domanda, risposta, righe, conferme}`, `errore {codice, messaggio}`; righe `: ` = keepalive.

- [ ] **Step 1:** caricare la skill impeccable e definire con essa aspetto, palette (chiaro/scuro con `prefers-color-scheme`), tipografia di sistema, stati vuoti e di attesa, secondo la sezione 5 della spec.
- [ ] **Step 2:** `app.js` (un modulo, funzioni piccole): `api(method, path, body)` per le chiamate JSON (errori → `{codice, messaggio}`; rete giù → messaggio «Il back-end non risponde all'indirizzo …: controlla che sia avviato (python -m backend_service).»); `readSse(response, onEvent, signal)` (parser: blocchi separati da riga vuota, `\r\n` accettati, righe `:` ignorate, `data:` multiple unite con `\n`); `renderText(text)` (escape totale, poi solo `**…**`, `` `…` ``, ```` ```…``` ````, a capo; costruzione con nodi DOM o stringa già ripulita); stato: chat aperta, turno in corso, `AbortController`.
- [ ] **Step 3:** comportamenti della sezione 5 della spec: elenco/apertura/creazione al primo invio/eliminazione con conferma, `localStorage` in `try/catch`, invio in streaming con «Sto pensando…», righe degli strumenti, revisore «non coerente» che svuota la bozza, `fine` che sostituisce con i messaggi salvati e aggiorna l'elenco, `errore` che rimette la domanda nella casella, «Interrompi», riquadro di conferma (anche alla riapertura), Invio/Maiuscolo+Invio, pannello su schermo stretto, `aria-live`.
- [ ] **Step 3b:** casi limite della spec (sezione 5, «Casi limite»): testo vuoto, errori senza `messaggio`, riuso della chat creata, 409/404 con ricarica, ricarica dopo «Interrompi», data di ripiego `creata`.
- [ ] **Step 4:** `python -m pytest tests/test_frontend_service.py -q` → PASS (contratto dei percorsi ora significativo).
- [ ] **Step 5:** prova di fumo nel browser con back-end acceso e agente spento: elenco, nuova chat, invio → avviso «L'agente non risponde…», domanda tornata nella casella, pagina utilizzabile; testo con `<b>` mai interpretato (con una risposta simulata o un messaggio salvato a mano tramite back-end in memoria).
- [ ] **Step 6:** commit `feat(frontend): pagina di chat con streaming, conferme ed errori`.

### Task 4: documentazione

**Files:**
- Modify: `README.md` (sezione «Front-end»: avvio a tre/quattro terminali, `FRONTEND_BACKEND_URL`, `BACKEND_CORS_ORIGINS`, limiti: nessun test automatico del JavaScript, testi dell'agente che nominano la CLI; tabella «Prova reale del front-end» con le prove della spec 6 «da fare»), `.env.example` (le due variabili commentate), `CLAUDE.md` (struttura `frontend_service/`, comando di avvio, confine «nessuna interfaccia grafica oltre al front-end web dello step 8»).

- [ ] **Step 1:** scrivere le modifiche riportando solo comandi verificati (`python -m frontend_service`, `python -m pytest`).
- [ ] **Step 2:** suite intera `python -m pytest -q` con le porte 8000–8003 libere → tutti PASS (salvo i saltati senza `TEST_DATABASE_URL`).
- [ ] **Step 3:** commit `docs(frontend): avvio, configurazione e prova reale del front-end`.

Dopo il Task 4: review finale dell'intero branch, poi prova reale dell'utente (spec, sezione 6), esiti nel README, merge `--no-ff` in `developer`, push, branch eliminato.
