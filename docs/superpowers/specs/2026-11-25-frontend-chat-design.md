# Step 8 — Front-end: interfaccia di chat

Data: 2026-11-25. Stato: bozza da approvare insieme al piano (scelta dell'utente per arrivare a venerdì 2026-11-27).

## 1. Intento

Le slide della lezione 6 chiedono un'interfaccia di chat **utilizzabile da chi non conosce il progetto**, che comunica **solo con il back-end** (`backend_service`, porta 8002, step 7). La tecnologia è libera. Il documento OpenAPI del back-end (`/openapi.json`) fa da contratto: le chiamate seguono quella descrizione e non si indovinano gli endpoint.

**Cosa realizzare** (dalle slide):
1. elenco delle chat, creazione di una nuova chat ed eliminazione;
2. vista dei messaggi della chat e invio di una nuova domanda;
3. stato di attesa durante la risposta ed errori mostrati in modo comprensibile;
4. indirizzo del back-end da configurazione, non scritto nel codice.

**Evidenze richieste**: conversazione completa dal browser con uso di uno strumento; una chat creata dall'interfaccia è ancora presente dopo il riavvio; con l'agente spento l'interfaccia mostra l'errore senza bloccarsi.

## 2. Obiettivi, non obiettivi, anti-obiettivi

**Obiettivi**: i quattro punti e le tre evidenze; risposta in streaming (le parole compaiono man mano, come nel terminale); conferma delle eliminazioni delle note dal browser; design curato con la skill **impeccable** (scelta dell'utente).

**Non obiettivi** (non anticipare): container del front-end e sistemazione a quattro container (step 9); autenticazione e più utenti; modifica del titolo; ricerca; prompt MCP; riconnessione automatica a metà risposta; modifiche al grafo o all'agente.

**Anti-obiettivi**: il front-end che chiama l'agente o il servizio delle note; logica del turno duplicata nel browser (ciò che resta è quello che salva il back-end); dipendenze o build JavaScript (npm, framework); una pagina che si blocca o perde la domanda scritta quando qualcosa non risponde.

## 3. Approcci considerati

1. **Scelto (dall'utente)**: HTML, CSS e JavaScript senza framework né build, serviti da un piccolo servizio FastAPI `frontend_service/` (porta 8003) che espone anche `/config.js` con l'indirizzo del back-end preso da variabile d'ambiente; il back-end abilita CORS solo per le origini del front-end, anch'esse da variabile. Nessuna dipendenza nuova; allo step 9 basta un container in più con la stessa immagine.
2. Front-end che inoltra (proxy) le chiamate al back-end: niente CORS, ma va inoltrato anche lo streaming SSE → più codice e test. Scartato.
3. React + Vite: Node, npm, build e un Dockerfile in più; troppo per la scadenza. Scartato.

## 4. Architettura

```
browser ──HTTP──► frontend_service (8003): index.html, app.js, style.css, config.js
   │
   └──HTTP (fetch, CORS)──► backend_service (8002) ──► agent_service (8001) …
```

- `frontend_service/` (nuovo pacchetto Python):
  - `app.py`: `create_app(backend_url)` FastAPI; `GET /` → `index.html`; `GET /static/...` → file statici (`StaticFiles`); `GET /config.js` → `window.APP_CONFIG = {"backendUrl": "<url>"};` generato con `json.dumps` (niente iniezione), `Cache-Control: no-store`, tipo `text/javascript; charset=utf-8`.
  - `__main__.py`: avvio con uvicorn, `--host` (predefinito 127.0.0.1), `--port` (8003), `--quiet`; legge `.env` con `load_dotenv`; `FRONTEND_BACKEND_URL` (predefinito `http://127.0.0.1:8002`), validata: deve iniziare con `http://` o `https://`, altrimenti codice 1 e messaggio su stderr. La barra finale si toglie.
  - `static/index.html`, `static/app.js`, `static/style.css`: la pagina. Testi in italiano, `lang="it"`.
- `backend_service`: aggiunta di `CORSMiddleware` in `create_app(..., cors_origins=...)`; `__main__.py` legge `BACKEND_CORS_ORIGINS` (elenco separato da virgole, predefinito `http://127.0.0.1:8003,http://localhost:8003`). Metodi `GET, POST, DELETE`, intestazione `Content-Type`, nessuna credenziale. Nessun altro cambiamento al back-end.
- `.env.example`, README, CLAUDE.md aggiornati (il vincolo «niente interfacce grafiche» diventa «nessuna interfaccia grafica oltre al front-end web dello step 8»).

## 5. Comportamento della pagina

**Disposizione**: colonna sinistra con il pulsante «Nuova chat» e l'elenco delle chat (titolo e data dell'ultimo messaggio, la più recente in alto, come restituito da `GET /chats`); area principale con i messaggi della chat aperta e, in basso, la casella della domanda con il pulsante «Invia» (Invio invia, Maiuscolo+Invio va a capo). Su schermo stretto l'elenco diventa un pannello che si apre con un pulsante.

```
┌──────────────┬─────────────────────────────────────────┐
│ + Nuova chat │  Che ore sono?                      (tu)│
│──────────────│  ⚙ get_current_time · Europe/Rome       │
│ Che ore sono?│  Sono le 13:12 del 25 novembre 2026.    │
│  oggi 13:12  │                                         │
│ Elimina…   🗑 │                                         │
│              │ ┌─────────────────────────────┐ [Invia] │
│              │ │ Scrivi una domanda…         │         │
└──────────────┴─┴─────────────────────────────┴─────────┘
```

**Chat**:
- All'apertura: `GET /chats`. Si apre l'ultima chat aperta (ricordata in `localStorage`, in un `try/catch`) se esiste ancora, altrimenti la vista vuota «nuova chat».
- «Nuova chat» non crea subito nulla: mostra la vista vuota; la chat si crea con `POST /chats` (senza titolo) al primo invio, così niente chat vuote. Il titolo lo assegna il back-end dalla prima domanda (già così nello step 7).
- Eliminazione: icona per ogni chat, conferma nativa del browser «Eliminare la chat "…"? I messaggi non si possono recuperare.», poi `DELETE /chats/{id}`; se era aperta si torna alla vista vuota.
- Apertura di una chat: `GET /chats/{id}`; mostra i messaggi e, se `conferme` non è vuoto, il riquadro di conferma (vedi sotto).

**Messaggi**: utente a destra, assistente a sinistra. Per l'assistente, sopra il testo, una riga discreta per ogni strumento usato (nome e argomenti principali; errore evidenziato) e, sotto, le `righe` informative (es. `[revisore] coerente`) in piccolo. Il testo dell'assistente passa da un renderer minimo e sicuro: si fa l'escape di tutto l'HTML, poi si riconoscono soltanto `**grassetto**`, `` `codice` ``, blocchi ```` ``` ```` e gli a capo (lfm2 usa il markdown). Nessun `innerHTML` con testo non ripulito.

**Invio (streaming)**: `POST /chats/{id}/messaggi/stream` con `fetch` e lettura del corpo (`ReadableStream` + `TextDecoder`), perché `EventSource` non permette `POST`. Parser SSE: blocchi separati da riga vuota; le righe `:` (keepalive) si ignorano; `event:` e `data:` (JSON).
- Durante l'attesa: la domanda compare subito; casella e pulsante disattivati; indicatore «Sto pensando…» finché non arriva il primo evento, poi gli eventi: `strumento` → riga «⚙ nome…» in corso; `esito_strumento` → la riga diventa completata o in errore; `risposta` → testo aggiunto man mano; `riga` → riga informativa; se la riga inizia con `[revisore] non coerente` la bozza mostrata si svuota e compare «Il revisore ha chiesto di rivedere la risposta…»; `ragionamento` → ignorato (lfm2 non lo invia; scelta per non confondere chi non conosce il progetto).
- `fine`: il messaggio provvisorio si sostituisce con `domanda` e `risposta` salvate (testo definitivo, compreso l'eventuale avviso dei falsi successi) e si aggiorna l'elenco delle chat; se `esito` è `conferma_richiesta` si mostra il riquadro di conferma.
- `errore` (o risposta HTTP non 2xx, o rete giù): la domanda provvisoria si toglie (il back-end non ha salvato nulla), il testo torna nella casella e compare un avviso con il `messaggio` del back-end (già in italiano), chiudibile; la pagina resta utilizzabile. Rete giù: «Il back-end non risponde all'indirizzo …: controlla che sia avviato (python -m backend_service).»
- Un pulsante «Interrompi» durante la risposta annulla la `fetch` (`AbortController`): come per Ctrl+C non si salva nulla e la domanda torna nella casella.

**Conferma delle eliminazioni delle note**: con `esito = conferma_richiesta` compare, al posto della casella, un riquadro con una riga per ogni conferma (`domanda`, già formulata dal back-end, senza il «[s/N]» finale) e i pulsanti «Elimina» / «Non eliminare» per ciascuna; «Conferma» invia `POST /chats/{id}/conferma/stream` con `{"decisioni": {"<id_nota>": true|false}}` e si procede come per un invio. Lo stesso riquadro compare riaprendo una chat con `conferme` in attesa.

**Errori comprensibili**: si mostra sempre il `messaggio` del back-end; i testi che nominano la CLI («usa 'clear'», «riavvia l'assistente») si mostrano così come sono (limite annotato nel README, come allo step 7). Errori di caricamento dell'elenco o di una chat: avviso con pulsante «Riprova».

**Casi limite** (scelte di Claude dopo la rilettura del costruttore):
- Testo vuoto o di soli spazi: «Invia» resta disattivato, niente richiesta (il back-end risponderebbe 422).
- Risposta di errore senza `messaggio` (i 422 di validazione hanno `{"detail": …}`): messaggio generico «Richiesta non valida.»; qualunque altra risposta non leggibile: «Risposta inattesa dal back-end (codice N).».
- Chat creata al primo invio ma turno fallito (es. agente spento): la chat resta (vuota, «Nuova chat») e resta aperta; il nuovo invio riusa il suo id, quindi niente chat doppie.
- 409 (`turno_in_corso`, `conferma_in_attesa`, nessuna conferma) e 404 (chat eliminata altrove): si mostra il `messaggio` e si ricarica la chat (`GET /chats/{id}`); con 404 si torna alla vista vuota e si ricarica l'elenco.
- «Interrompi»: il back-end salva comunque se l'agente era già arrivato al `fine`. Dopo l'interruzione la pagina ricarica chat ed elenco: se la domanda risulta salvata la mostra, altrimenti la rimette nella casella.
- Back-end spento (fetch rifiutata) e agente spento (503 dal back-end) sono due messaggi diversi: il primo è quello del front-end, il secondo è il `messaggio` del back-end. Un errore 500 imprevisto del back-end arriva al browser senza intestazioni CORS (il gestore degli errori sta fuori dal middleware) e quindi appare come rete giù: limite accettato e annotato nel README.
- Chat senza messaggi: nell'elenco si mostra la data di `creata`.
- Payload degli eventi SSE (inoltrati dall'agente così come sono): `strumento {nome, argomenti}`, `esito_strumento {nome, contenuto, errore}`, `risposta {testo}` (pezzo incrementale), `riga {testo}`, `ragionamento {testo}`, `fine` = corpo di `TurnResult`, `errore {codice, messaggio}`. Gli elementi di `strumenti` nei messaggi salvati sono `{nome, argomenti, esito, errore}`.

**Misure della risposta** (richiesta dell'utente del 2026-11-25, dopo l'approvazione): sotto ogni risposta arrivata in streaming nella sessione, una riga discreta con **tempo totale** (dall'invio all'evento `fine`), **tempo al primo token** (dall'invio al primo evento `risposta`, che comprende router e strumenti) e **≈ token** (numero di eventi `risposta` ricevuti: con LM Studio di solito un pezzo per token, quindi un'approssimazione dichiarata). Si misurano nel browser e non si salvano: le risposte rilette dal back-end non le mostrano. Conteggio esatto dei token (uso riportato dal modello) fuori ambito: richiederebbe di modificare agente e back-end.

**Direzione visiva** (scelta dell'utente con impeccable): «Sala dei reperti» (cartellini smaltati del Museo della Scienza e della Tecnologia di Milano) per palette e ordine, con gli strumenti mostrati come le schede magnetiche della Olivetti Programma 101. Il contratto di direzione sta in `.impeccable/surfaces/`.

**Accessibilità e aspetto**: design con la skill impeccable (palette, tipografia, spaziature, stati vuoti, stato di attesa); contrasto sufficiente, focus visibile, pulsanti con etichetta, area messaggi `aria-live="polite"`; tema chiaro e scuro secondo il sistema. Nessun font o script esterno (funziona offline).

## 6. Test

- Automatici (pytest, senza modello e senza browser):
  - `frontend_service`: `/` restituisce la pagina; i file statici esistono e sono serviti; `/config.js` contiene l'URL configurato, è JavaScript valido nella forma attesa ed è protetto dall'iniezione (URL con virgolette); `__main__` rifiuta URL senza schema e usa il predefinito.
  - `backend_service`: CORS — origine ammessa riceve `access-control-allow-origin` (anche nella preflight `OPTIONS` di `POST` con `Content-Type: application/json`), origine non ammessa no; `BACKEND_CORS_ORIGINS` letta e divisa correttamente.
  - Contratto: un test controlla che ogni percorso chiamato da `app.js` (elenco fisso nel test) esista in `/openapi.json` del back-end con il metodo giusto.
- La logica JavaScript (parser SSE, renderer, stati della pagina) non ha test automatici (niente Node, scelta per la scadenza): si prova nel browser con la prova reale. Limite dichiarato nel README.
- **Prova reale** (utente, con LM Studio): le tre evidenze, più streaming, conferma di una nota (sì e no), eliminazione di una chat, interruzione, agente spento durante una risposta, finestra stretta.

## 7. Lasciato al costruttore

Nomi interni di funzioni e classi CSS; formato della data nell'elenco (relativo «oggi 13:12» o assoluto); testi esatti degli stati vuoti; dettagli visivi decisi con impeccable entro i vincoli della sezione 5.
