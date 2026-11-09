# Note persistenti con FastAPI — specifica

Data: 2026-11-09 · Stato: approvata dall'utente il 2026-11-09

Riferimenti: lezione 5 del corso, slide 16 (scelta del confine), 19 e 21 (variante FastAPI + wrapper HTTP), 6 (controllo dei permessi da parte dell'applicazione), 26 («Note persistenti: un tool che produce effetti») e 31 (evidenze). Specifiche precedenti `2026-11-02-strumenti-mcp-design.md` e `2026-11-09-catalogo-linguaggi-design.md`, valide per tutto ciò che qui non cambia.

## 1. Intento

Dare all'assistente **note persistenti**: aggiungerle, elencarle, eliminarle, conservate in SQLite fra una sessione e l'altra. A differenza degli strumenti fatti finora, questi **modificano uno stato che sopravvive alla sessione** (slide 26): il contratto deve dire che cosa cambia, ogni modifica va registrata e nessuna eliminazione deve essere ambigua.

**Variante (scelta dell'utente): FastAPI**, non FastMCP. Le note vivono in un **servizio HTTP separato**, usabile anche da fuori dall'assistente (per esempio dal browser con la pagina `/docs` generata da FastAPI). Nell'assistente tre **wrapper scritti a mano** registrati con `@tool` chiamano il servizio via HTTP: è la variante della slide 19, che permette di osservare dal vivo la differenza con FastMCP (nessuna discovery: nome, descrizione e schema dei tool stanno nell'assistente; se il servizio cambia, va aggiornato il wrapper).

È la seconda delle tre proposte della seconda parte (catalogo fatto; dopo le note, il meteo).

## 2. Obiettivi

- Un servizio FastAPI nel progetto con archivio SQLite, avviabile da solo.
- Tre tool nell'assistente: `add_note`, `list_notes`, `delete_note`, che chiamano il servizio.
- **Conferma dell'eliminazione chiesta dal programma** (non dal modello) prima di inviare la richiesta al servizio.
- Note che restano dopo il riavvio dell'assistente, in locale e con Docker, nello stesso archivio.
- Log di ogni modifica eseguita.
- Avvio automatico del servizio in locale; secondo container in Docker Compose.
- Test senza modello e prova reale; README e `CLAUDE.md` aggiornati.

## 3. Non obiettivi e anti-obiettivi

**Non obiettivi:**
- Modifica di una nota esistente (non prevista dalla slide): per cambiarla la si elimina e la si ricrea.
- Ricerca nelle note, categorie, priorità, promemoria che «suonano» a una data.
- Autenticazione, più utenti, accesso dalla rete esterna: il servizio è per uso locale.
- Esporre le note anche come tool MCP o come prompt MCP (slide 29, estensione 04): possibile in futuro.
- Meteo: specifica successiva.

**Anti-obiettivi:**
- una nota eliminata senza la conferma esplicita dell'utente nel terminale;
- un'eliminazione «per descrizione» invece che per ID esatto;
- un falso successo: nota dichiarata salvata o eliminata quando il servizio ha risposto con un errore o non ha risposto;
- l'archivio SQLite o la cartella `data/` versionati in Git;
- un test con servizio o modello simulati presentato come prova reale.

## 4. Architettura

| Variante (slide 21) | Nel progetto |
|---|---|
| Servizio | nuovo pacchetto `notes_service/` (nome proposto), FastAPI + SQLite (`sqlite3` della libreria standard) |
| Wrapper nell'agente | nuovo modulo dell'assistente (nome proposto `assistant/notes.py`): tre funzioni `@tool` che chiamano il servizio con `httpx` |
| Aggancio al grafo | i tre tool si aggiungono a quelli ottenuti dal catalogo MCP in `bind_tools` e nel `ToolNode`; il grafo non sa che dietro c'è HTTP |

- Il server MCP `lab_server/` non cambia. Il modello vede 12 tool (9 MCP + 3 note).
- **Data di oggi e formattazione**: il servizio restituisce dati grezzi in JSON; il wrapper li trasforma in testo per il modello, calcolando la distanza dalla scadenza nel fuso `DEFAULT_TIMEZONE` (come gli strumenti delle date).

### 4.1 Avvio del servizio

Nuova variabile d'ambiente **`NOTES_SERVICE_URL`** (facoltativa; *proposta di Claude, approvata*):
- **vuota o assente** (uso locale, scelta dell'utente): l'assistente avvia il servizio come sottoprocesso con lo stesso interprete Python su `http://127.0.0.1:8000`, attende che risponda (con un tempo massimo) e lo chiude all'uscita (`quit`, Ctrl+C, EOF), come fa con il server MCP. Mentre l'assistente è aperto, `http://127.0.0.1:8000/docs` è raggiungibile dal browser;
- **impostata**: l'assistente usa quel servizio senza avviarne un altro (caso Docker).

All'avvio l'assistente verifica che il servizio risponda; se non parte (per esempio porta 8000 occupata) o non risponde → messaggio chiaro e uscita con codice 1, come per LM Studio irraggiungibile. Il servizio è avviabile anche da solo (`python -m notes_service`), per usarlo senza assistente.

### 4.2 Archivio

- File SQLite `data/notes.db` nella cartella del progetto; la cartella `data/` è esclusa da Git (`.gitignore`) e creata se manca.
- Una tabella con: ID intero crescente assegnato dal servizio, testo, scadenza facoltativa (data ISO), data e ora di creazione (ISO, UTC).
- Percorso dell'archivio passato al servizio (argomento o variabile), così i test usano un file temporaneo.

## 5. Contratto

### 5.1 Servizio HTTP

| Metodo e percorso | Effetto | Esito |
|---|---|---|
| `POST /notes` (JSON `text`, `due_date` facoltativa) | crea una nota | `201` con la nota creata (id, testo, scadenza, creazione) |
| `GET /notes?limit=N` | elenco ordinato per scadenza | `200` con le note (al massimo `limit`) e il totale |
| `GET /notes/{id}` | una nota | `200`, oppure `404` |
| `DELETE /notes/{id}` | elimina la nota | `200` con la nota eliminata, oppure `404` |

- **Validazione nel servizio**: testo con spazi ai bordi tolti, da 1 a 500 caratteri; `due_date` nel formato `AAAA-MM-GG` ed esistente (data passata ammessa); `limit` da 1 a 50 (predefinito 10). Errori con messaggio in italiano (codice `422` o `400`; dettaglio al piano).
- **Ordine dell'elenco (scelta dell'utente): per scadenza.** Prima le note con scadenza, dalla più vecchia alla più lontana (quindi le scadute in cima), poi quelle senza scadenza, dalla più recente; a parità, per ID.
- **Log nel servizio**: una riga `INFO` per ogni modifica eseguita (`nota creata id=… testo=…`, `nota eliminata id=…`).
- Documentazione OpenAPI generata da FastAPI su `/docs` (slide 19).

### 5.2 Tool nell'assistente

Descrizioni scritte a mano nel wrapper (non c'è discovery), chiare e distinguibili dagli altri 9 tool.

**`add_note(text, due_date=None)`** — salva una nota; `due_date` facoltativa `AAAA-MM-GG` (la descrizione dice al modello di convertire «venerdì», «domani»… in data ISO usando gli strumenti delle date se serve). Risultato, per esempio: `Nota 4 salvata: «consegnare il report» · scadenza 2026-11-13 (fra 4 giorni).` Se la scadenza è già passata il risultato lo dice («scaduta da 2 giorni»).

**`list_notes(limit=10)`** — elenco ordinato per scadenza, una riga per nota con ID, testo, scadenza e distanza calcolata dal programma, per esempio:
```
5 note, mostrate 3:
- 2: pagare la bolletta · scadenza 2026-11-07 (scaduta da 2 giorni)
- 4: consegnare il report · scadenza 2026-11-13 (fra 4 giorni)
- 1: comprare il latte · senza scadenza
```
Elenco vuoto: `Nessuna nota salvata.` (risultato normale, non errore). Totale sempre dichiarato, come nel catalogo.

**`delete_note(note_id)`** — elimina **solo per ID esatto**, con **conferma del programma** (scelta dell'utente):
1. il wrapper legge la nota con `GET /notes/{id}`; se non esiste → errore dello strumento `Nessuna nota con ID 99: nulla è stato eliminato.`;
2. l'assistente scrive nel terminale `Elimino la nota 4 «consegnare il report» (scadenza 2026-11-13)? [s/N] ` e legge la risposta;
3. solo con `s` (o `si`/`sì`, senza distinzione di maiuscole) invia `DELETE` → `Nota 4 eliminata: «consegnare il report».`;
4. con qualsiasi altra risposta, invio vuoto o fine dell'input → nulla viene inviato, e al modello torna `Eliminazione della nota 4 annullata dall'utente.` (risultato normale: non è un errore, è una decisione).

La conferma è una funzione iniettabile nel wrapper (i test la sostituiscono con risposte fisse). La descrizione del tool dice al modello che per eliminare serve l'ID (da `list_notes`) e che il programma chiederà conferma all'utente.

**Istruzioni di sistema** (testo esatto al piano): per ricordare qualcosa usa `add_note` (una sola chiamata per richiesta), con la scadenza in `AAAA-MM-GG` se l'utente ne indica una; per eliminare usa l'ID esatto preso da `list_notes`, e se la richiesta è ambigua chiedi all'utente quale nota; non dichiarare mai una nota salvata o eliminata se lo strumento non lo conferma.

### 5.3 Errori

- **Errore dello strumento** (torna al modello come `ToolMessage` con stato `error`): testo vuoto o troppo lungo, data non valida, `limit` fuori intervallo, ID inesistente. Il wrapper traduce le risposte d'errore del servizio in messaggi italiani.
- **Errore di collegamento** (servizio terminato o non raggiungibile durante la sessione, timeout): distinto dall'errore dello strumento, trattato come quello del server MCP: turno interrotto, messaggio all'utente («Il servizio delle note non risponde…»), domanda non in cronologia. *Scelta di Claude:* timeout di 5 secondi per le richieste HTTP.
- **Log nell'assistente**: le righe esistenti `[strumento] … esito=…` del nodo strumenti; in più una riga `INFO` quando l'utente conferma o annulla un'eliminazione.

## 6. Docker

- `compose.yaml`: nuovo servizio `notes` (stessa immagine, comando che avvia il servizio su `0.0.0.0:8000`), porta `8000` pubblicata sull'host (per `/docs` da Windows); il servizio `app` riceve `NOTES_SERVICE_URL=http://notes:8000` e dipende da `notes`.
- **Stesse note in locale e in Docker (scelta dell'utente):** la cartella `data/` del progetto è montata nel container `notes` (bind mount), quindi l'archivio è lo stesso file.
- Limite dichiarato: assistente locale e assistente in Docker non vanno usati **insieme** (entrambi vogliono la porta 8000).
- Il `Dockerfile` copia anche `notes_service/`. Da verificare: permessi di scrittura dell'utente non root sulla cartella montata.
- Avvio invariato per l'utente: `docker compose build`, `docker compose run --rm app` (Compose avvia anche `notes`). Il container `notes` resta acceso dopo l'uscita dall'assistente: si ferma con `docker compose down` (da documentare nel README). Da verificare che con `run` la porta di `notes` risulti pubblicata sull'host.

## 7. Dipendenze

Nuove, da fissare con `==` dopo la verifica su Python 3.14 insieme a quelle esistenti (`pip install` in un ambiente pulito e `pip check`); se non si installano insieme ci si ferma e si chiede all'utente (come per FastMCP):

| Pacchetto | Motivo |
|---|---|
| `fastapi` | il servizio HTTP e la documentazione OpenAPI |
| `uvicorn` | il server che esegue l'applicazione FastAPI |
| `httpx` | le chiamate HTTP dai wrapper (e il `TestClient` di FastAPI nei test) |

SQLite con `sqlite3` della libreria standard. `httpx` potrebbe già essere installato come dipendenza transitiva: va comunque dichiarato, perché il progetto lo usa direttamente.

## 8. Test e verifiche

### Test automatici (senza modello e senza LM Studio)
- **Servizio** (`TestClient` di FastAPI, archivio in una cartella temporanea): creazione con e senza scadenza; validazione (testo vuoto, 501 caratteri, data non ISO o inesistente, `limit` 0 e 51); ordine per scadenza con scadute, future e senza scadenza; `GET` e `DELETE` su ID esistente e inesistente; persistenza: le note restano dopo aver ricreato l'applicazione sullo stesso file; log di creazione ed eliminazione.
- **Wrapper**: contro il servizio vero (`TestClient` o servizio avviato), testi dei risultati con data di oggi fissa; conferma con `s` → eliminata, con `n` o input vuoto → annullata e nota ancora presente; ID inesistente → errore senza chiedere conferma; servizio non raggiungibile → errore di collegamento, non errore dello strumento.
- **Avvio**: con `NOTES_SERVICE_URL` vuota il servizio viene avviato e chiuso; con un URL non raggiungibile → messaggio e codice 1.
- **Grafo** con il modello finto: `add_note` → `ToolMessage` correlato; `delete_note` annullata → nessuna eliminazione e cronologia coerente.
- **Istruzioni**: il prompt cita i tre tool e la regola dell'ID.
- Restano verdi tutti i test esistenti.

### Verifica diretta
Documentata nel README, solo comandi eseguiti: avvio del servizio da solo e prova di `POST`/`GET`/`DELETE` (dal browser su `/docs` o con un comando PowerShell), senza assistente e senza modello.

### Prova reale con LM Studio (dell'utente, in locale e con Docker)
- «Ricordami di consegnare il report venerdì» → **una sola** chiamata `add_note`, scadenza = il prossimo venerdì;
- «Che note ho?» → `list_notes`, ordine per scadenza;
- «Elimina la nota 99» con ID inesistente → errore chiaro, nessuna richiesta di conferma, nulla eliminato;
- eliminazione di una nota vera: una volta rispondendo `n` (resta), una volta `s` (sparisce);
- riavvio dell'assistente: le note salvate ci sono ancora; le stesse note viste da Docker;
- `/docs` aperto nel browser mentre l'assistente è in esecuzione.

Se il modello sceglie male o dichiara un salvataggio non avvenuto, si registra il punto esatto e non si dichiara completata quella prova.

## 9. Ordine di lavoro e branch

Branch `feature/note-fastapi` da `developer`; merge `--no-ff` in `developer` dopo la prova reale e l'ok dell'utente, push di `developer`, eliminazione del branch. Pezzi piccoli, ciascuno con test e commit. Ordine indicativo (dettaglio al piano): dipendenze verificate e fissate; archivio SQLite; servizio FastAPI; wrapper e conferma; avvio automatico e integrazione nel grafo; Docker; documentazione e prova reale.

`CLAUDE.md` va aggiornato: struttura (`notes_service/`, modulo delle note nell'assistente, `data/`), comandi, confini («gli strumenti passano dal server MCP» diventa: strumenti MCP in `lab_server/`, note tramite il servizio FastAPI; resta da fare il meteo).

## 10. Scelte fatte da Claude (da rivedere)

- Nomi `notes_service/`, `assistant/notes.py`, `data/notes.db`; `sqlite3` della libreria standard.
- `NOTES_SERVICE_URL` vuota = avvio automatico su `127.0.0.1:8000`; impostata = servizio esterno.
- Formattazione dei risultati nel wrapper, con la distanza dalla scadenza calcolata dal programma.
- Limiti: testo 1–500 caratteri, `limit` 1–50 (predefinito 10); scadenza passata ammessa ma segnalata.
- Ordine a parità di scadenza per ID; note senza scadenza dalla più recente.
- `GET /notes/{id}` aggiunto per mostrare la nota nella conferma.
- Risposte di conferma accettate: `s`, `si`, `sì`; tutto il resto annulla. Annullamento = risultato normale, non errore.
- Timeout HTTP 5 secondi; servizio irraggiungibile = errore di collegamento (turno interrotto).
- Porta 8000 pubblicata in Docker; bind mount di `data/`.
- Nessuna modifica di note esistenti.

## 11. Lasciato al piano

- Versioni esatte di `fastapi`, `uvicorn`, `httpx`.
- Testi esatti di risultati, errori, descrizioni dei tool e istruzioni di sistema.
- Codici HTTP d'errore esatti e formato JSON delle risposte.
- Meccanismo di attesa del servizio all'avvio e tempo massimo.
- Come la conferma legge dal terminale senza disturbare la riga «…sto pensando».
