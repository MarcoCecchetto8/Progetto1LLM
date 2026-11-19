# Note persistenti con FastAPI — specifica

Data: 2026-11-09 · Stato: approvata dall'utente il 2026-11-09 · **Revisione 2026-11-11** (sezione 5.4, controllo dei falsi successi, dopo la prova reale): approvata dall'utente il 2026-11-11 · **Revisione 2026-11-15** (5.4: solo avviso, niente nuovo tentativo): scelta dell'utente · **Revisione 2026-11-18** (sezione 5.5: frasi brevi e avviso legato alla richiesta, dopo la prova reale dell'agente come servizio): approvata dall'utente il 2026-11-18, comprese le due scelte di Claude

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
- un falso successo: nota dichiarata salvata o eliminata quando il servizio ha risposto con un errore o non ha risposto, **oppure quando il modello non ha chiamato lo strumento affatto** (caso visto nella prova reale, sezione 5.4): non deve mai arrivare all'utente senza un avviso;
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

*Revisione 2026-11-11:* per i giorni come «venerdì» o «domani» il prompt dice di **non chiedere la data all'utente** ma di ricavarla con `get_current_time` e `add_days` e poi chiamare `add_note`, e che la nota esiste solo se lo strumento risponde «Nota N salvata». Sull'eliminazione resta la formulazione originale: la frase aggiunta «non chiedere tu conferma» è tolta, perché nella misura il modello ha cominciato a parlare della conferma invece di chiamare `delete_note` (2 volte su 5).

### 5.3 Errori

- **Errore dello strumento** (torna al modello come `ToolMessage` con stato `error`): testo vuoto o troppo lungo, data non valida, `limit` fuori intervallo, ID inesistente. Il wrapper traduce le risposte d'errore del servizio in messaggi italiani.
- **Errore di collegamento** (servizio terminato o non raggiungibile durante la sessione, timeout): distinto dall'errore dello strumento, trattato come quello del server MCP: turno interrotto, messaggio all'utente («Il servizio delle note non risponde…»), domanda non in cronologia. *Scelta di Claude:* timeout di 5 secondi per le richieste HTTP.
- **Log nell'assistente**: le righe esistenti `[strumento] … esito=…` del nodo strumenti; in più una riga `INFO` quando l'utente conferma o annulla un'eliminazione.

### 5.4 Controllo dei falsi successi (revisione 2026-11-11)

**Perché.** Nella prova reale (sonda end-to-end: grafo vero, `gemma-4-e2b`, archivio temporaneo, 5 conversazioni per domanda) il modello a volte chiude il turno scrivendo «Ho salvato la nota» **senza aver chiamato `add_note`**: 1 volta su 5 con «Ricordami di comprare il latte», 3 su 5 con «…il report venerdì» (dopo `add_days` scambia il risultato della data per il salvataggio). Il codice delle note è corretto: la risposta del modello non contiene chiamate e il grafo la manda all'utente. Il prompt da solo non ha ridotto il problema, quindi il controllo lo fa il **programma**, come la conferma dell'eliminazione (slide 6).

**Che cosa controlla.** Quando il modello risponde senza chiamate (la risposta che andrebbe all'utente), il programma guarda:
1. se il testo **dichiara** un salvataggio o un'eliminazione di una nota (famiglie di parole come «salvat…», «memorizzat…», «annotat…», «registrat…» per il salvataggio; «eliminat…», «cancellat…», «rimoss…» per l'eliminazione; elenco esatto al piano, in minuscolo e senza distinzione di accenti);
2. se **nello stesso turno** (dopo l'ultima domanda dell'utente) c'è una conferma dello strumento corrispondente: un risultato di `add_note` senza errore per il salvataggio; un risultato di `delete_note` senza errore (eliminata **o** annullata dall'utente) per l'eliminazione.

Dichiarazione senza conferma = **falso successo**. Le frasi negative che contengono le stesse parole (per esempio «non ho salvato nulla») sono un caso limite: il piano stabilisce come trattarle, con un test; nel dubbio si preferisce un avviso di troppo a un falso successo che passa.

**Che cosa fa (revisione 2026-11-15: solo avviso, scelta dell'utente).**
1. La risposta del modello arriva all'utente **con un avviso aggiunto dal programma** in fondo, per esempio `⚠ Attenzione: nessuna nota è stata salvata (lo strumento non l'ha confermato).` per il salvataggio e `⚠ Attenzione: nessuna nota è stata eliminata (lo strumento non l'ha confermato).` per l'eliminazione (testo esatto al piano). Se la risposta dichiara entrambe le cose senza conferma, compaiono entrambi gli avvisi.
2. L'avviso resta **nella cronologia** insieme alla risposta, così nei turni successivi il modello «vede» che la nota non è stata salvata.
3. Il controllo non chiama di nuovo il modello e non consuma passaggi.
4. Ogni avviso lascia una riga di log `INFO` (`[controllo] falso successo: …, avviso all'utente`).

**Perché niente nuovo tentativo.** La prima versione di questa sezione (2026-11-11) prevedeva di rimandare la risposta al modello una volta, con un messaggio di correzione. Misurato prima di pianificare (risposta falsa «Ho salvato la nota» + correzione, tool delle note legati, 5 prove per tipo): correzione come messaggio di sistema → 0 su 5 chiamano `add_note` (il modello ripete la frase falsa); come messaggio dell'utente → 0 su 5 (si scusa o ripete «Ho salvato»). Con `gemma-4-e2b` il nuovo tentativo costerebbe un altro giro del modello senza correggere nulla: resta solo l'avviso.

**Dove sta.** Il grafo riceve un **controllo della risposta facoltativo** (una funzione passata a `build_graph`): senza controllo il grafo si comporta come oggi, quindi i test esistenti e gli altri strumenti non cambiano. La funzione che riconosce i falsi successi delle note sta nel modulo delle note dell'assistente, perché conosce i nomi e i testi dei suoi tool. Nel grafo il controllo è un passaggio riconoscibile (nodo o instradamento dopo `model`; forma esatta al piano), con lo stesso stile di `step_limit`.

**Limiti dichiarati.**
- Il controllo riconosce **parole**, non intenzioni: una risposta come «Ti ricordo di consegnare il report venerdì» senza `add_note` non dichiara un salvataggio e passa senza avviso. Si registra come limite del modello nella prova reale.
- Non risolve il caso «Elimina la nota 99» in cui il modello risponde «Dovrai prima confermare» senza chiamare `delete_note`: non è un falso successo (non dichiara nulla di fatto). Per questo si torna alla formulazione originale del prompt (sezione 5.2).
- **Streaming** (prossima funzionalità richiesta dall'utente): se la risposta verrà mostrata mentre si genera, il controllo arriverebbe dopo che l'utente l'ha già letta. La specifica dello streaming dovrà dire come convivono (per esempio avviso dopo il testo, o niente streaming per le risposte che toccano le note).

### 5.5 Frasi brevi e avviso legato alla richiesta (revisione 2026-11-18)

**Perché.** Nella prova reale dell'agente come servizio (2026-11-18, `gemma-4-e2b`) il modello ha risposto «Nota salvata.» a «Salva una nota: …» senza chiamare `add_note`, e l'avviso non è comparso: il riconoscimento della 5.4 cerca solo forme con l'ausiliare («ho salvato», «è stata salvata»). In un altro turno, a «Elimina la nota 6» ha risposto «Dovrai prima confermare l'eliminazione» senza chiamare `delete_note` (caso già dichiarato come limite nella 5.4). L'utente vuole una regola semplice: **se chiedo di salvare o eliminare una nota, o vedo la conferma dello strumento o vedo l'avviso**; e, altrettanto importante, **se parlo d'altro non deve mai comparire un avviso sulle note**.

**Che cosa cambia.** Il controllo della 5.4 resta (stesso posto, stessi testi degli avvisi, solo avviso, log `INFO`) e si allarga in due direzioni indipendenti.

1. **Dichiarazioni brevi del modello.** Oltre alle forme con l'ausiliare, conta come dichiarazione anche il participio senza ausiliare quando **apre la frase** e si riferisce a una nota: «Nota salvata.», «Ok, nota salvata!», «Fatto: promemoria registrato.», «Nota 6 eliminata.». Le frasi in cui il participio è un aggettivo restano escluse, come oggi: «Nessuna nota salvata.», «Non hai note salvate.» (risposte vere di `list_notes`). Regola invariata per la conferma: serve un risultato **senza errore** dello strumento corrispondente nello stesso turno (per l'eliminazione vale anche «annullata dall'utente»).
2. **Richiesta esplicita dell'utente.** Se la domanda del turno (l'ultima dell'utente, esclusi i messaggi del revisore) contiene una **richiesta esplicita** di salvare o di eliminare una nota e nello stesso turno lo strumento corrispondente **non è stato chiamato**, compare l'avviso corrispondente, qualunque cosa abbia scritto il modello. Esplicita vuol dire una forma imperativa rivolta all'assistente da un **elenco stretto**, per esempio:
   - salvataggio: «salva / salvami / annota / segna / segnati / scrivi» seguito da «una nota», «un promemoria» o «che …»; «aggiungi / crea una nota (un promemoria)»; «ricordami di …» (con «di» subito dopo: «ricordami come mi chiamo» non conta); «nota:» o «promemoria:» all'inizio della domanda;
   - eliminazione: «elimina / cancella / rimuovi» seguito da «la nota», «le note», «il promemoria» (con o senza ID).
   L'elenco esatto si fissa al piano **dopo una misura** (sotto). In caso di dubbio una forma **non** entra nell'elenco: per questa parte un avviso mancato è meglio di un avviso sbagliato, perché l'utente non vuole avvisi sulle note quando parla d'altro.

**Due avvisi uguali non si ripetono:** se la richiesta e la dichiarazione scattano insieme per il salvataggio, compare un solo avviso di salvataggio (lo stesso per l'eliminazione); salvataggio ed eliminazione restano indipendenti (una domanda che chiede entrambe le cose può avere entrambi gli avvisi).

**Misura prima del piano.** Con la sonda end-to-end (grafo vero, archivio temporaneo) e il modello che l'utente userà (vedi sotto), circa 20 domande: richieste vere di salvataggio ed eliminazione in forme diverse, e domande che parlano d'altro usando le stesse parole («ricordami come mi chiamo», «cos'è una nota a piè di pagina?», «come si cancella un file in Python?», «salva il mondo» …). Si registrano le risposte del modello e quali avvisi scatterebbero. Obiettivo: **zero avvisi sulle domande che parlano d'altro**; i numeri vanno nel README.

**Limiti dichiarati.**
- Le richieste in forme non previste («metti in agenda…») passano senza avviso, come oggi.
- Se il modello risponde con una domanda di chiarimento a una richiesta esplicita («Salva una nota» → «Che testo vuoi salvare?») e non chiama lo strumento, l'avviso compare: dice il vero (nessuna nota è stata salvata) ma è superfluo. Proposta di Claude per evitarlo: per la parte 2, nessun avviso se la risposta del modello **termina con un punto interrogativo** (la parte 1 resta valida).
- Il controllo riconosce ancora parole, non intenzioni.

**Scelta del modello.** In parallelo l'utente valuta `liquid/lfm2-24b-a2b` al posto di `google/gemma-4-e2b`. Prima della misura si confrontano i due modelli con le sonde esistenti (strumenti, router, revisore, tempi); la misura delle frasi si fa sul modello scelto. Il cambio di modello non tocca il codice (`LMSTUDIO_MODEL`) e non fa parte di questa revisione.

### 5.6 Date relative nella scadenza (revisione 2026-11-19)

`due_date` di `add_note` accetta anche oggi, domani, dopodomani e i giorni della settimana, calcolati dal programma: vedi `2026-11-19-data-nel-prompt-design.md`, revisione 2026-11-19.

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
- **Controllo dei falsi successi** (revisione 2026-11-11), con il modello finto:
  - «Ho salvato la nota» senza `add_note` → risposta con l'avviso di salvataggio, avviso presente anche nel messaggio in cronologia, nessuna nuova chiamata al modello (stesso numero di passaggi);
  - risposta che dichiara salvataggio ed eliminazione senza conferme → entrambi gli avvisi;
  - «Ho salvato…» dopo un `add_note` riuscito nello stesso turno → nessun intervento; dopo un `add_note` **fallito** (errore dello strumento) → avviso;
  - dopo il limite di passaggi (`LIMIT_MESSAGE`) → nessun avviso (non è una risposta del modello);
  - un `add_note` riuscito in un turno **precedente** non vale come conferma per il turno attuale;
  - eliminazione: «Ho eliminato…» senza `delete_note` → intervento; dopo `delete_note` annullata dall'utente → nessun intervento;
  - risposte che non parlano di note (ora, catalogo) → nessun intervento; grafo senza controllo → comportamento invariato;
  - funzione di riconoscimento testata a parte su frasi reali raccolte nella prova (comprese le negative scelte al piano).
- **Frasi brevi e richiesta esplicita** (revisione 2026-11-18), senza modello:
  - «Nota salvata.», «Ok, nota salvata!», «Nota 6 eliminata.» senza strumento → avviso; con lo strumento riuscito nello stesso turno → nessun avviso;
  - «Nessuna nota salvata.», «Non hai note salvate.» → nessun avviso (invariato);
  - ogni forma dell'elenco di richieste, senza chiamata allo strumento e con una risposta qualsiasi (anche «Ti ricordo di…» o «Dovrai prima confermare…») → avviso; con lo strumento chiamato → nessun avviso;
  - le domande che parlano d'altro raccolte nella misura → nessun avviso;
  - richiesta e dichiarazione insieme → un solo avviso; richiesta di salvare ed eliminare insieme → entrambi gli avvisi;
  - i messaggi del revisore non contano come domanda dell'utente;
  - (se approvato) risposta che termina con «?» → nessun avviso legato alla richiesta.
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

*Revisione 2026-11-11:* dopo il controllo si ripete la misura con la sonda end-to-end (5 conversazioni per «Ricordami di comprare il latte», «Ricordami di consegnare il report venerdì», «Elimina la nota 99») e si riportano nel README, prima/dopo: salvataggi riusciti, avvisi mostrati, e quanti falsi successi sono arrivati all'utente **senza** avviso (atteso: zero). Il controllo non rende il modello affidabile: lo rende **onesto verso l'utente**, e il README lo dice.

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
- *Revisione 2026-11-18:* participio senza ausiliare riconosciuto solo a inizio frase; per la parte legata alla richiesta vale la stessa conferma della 5.4 (risultato senza errore), quindi anche un `add_note` fallito o «Elimina la nota 99» con ID inesistente mostrano l'avviso (dice il vero); elenco stretto delle richieste fissato dopo la misura; un solo avviso per tipo; nessun avviso legato alla richiesta se la risposta termina con «?» (confermato).
- *Revisione 2026-11-11/15:* controllo dei falsi successi nel programma, **solo avviso** (scelta dell'utente dopo la misura sul nuovo tentativo); riconoscimento per parole; controllo passato a `build_graph` come funzione facoltativa e implementato nel modulo delle note; avviso aggiunto in fondo alla risposta e conservato in cronologia.

## 11. Lasciato al piano

- Versioni esatte di `fastapi`, `uvicorn`, `httpx`.
- Testi esatti di risultati, errori, descrizioni dei tool e istruzioni di sistema.
- Codici HTTP d'errore esatti e formato JSON delle risposte.
- Meccanismo di attesa del servizio all'avvio e tempo massimo.
- Come la conferma legge dal terminale senza disturbare la riga «…sto pensando».
