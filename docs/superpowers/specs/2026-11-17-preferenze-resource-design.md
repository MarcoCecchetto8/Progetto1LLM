# Preferenze dell'utente come resource MCP (lezione 6, step 4) — specifica

Data: 2026-11-17 · Stato: approvata dall'utente il 2026-11-17; revisione 5.4 (fuso fuori dal blocco) del 2026-11-17 da confermare

Riferimenti: lezione 6, slide 7 (resource: contesto scelto dall'host), 8 (step 4 · preferenze dell'utente), 9 (tool, resource e prompt: chi li attiva e quando; evidenza minima «preferenze applicate; modifica del file senza modifica del codice»). Specifiche precedenti valide per tutto ciò che qui non cambia, in particolare `2026-11-16-riassunto-design.md` (riassunto in fondo al primo messaggio di sistema) e le specifiche di router, revisore, streaming e note.

## 1. Intento

Oggi il modo in cui l'assistente risponde è scritto nel codice o nel `.env`: la lingua nel prompt di sistema («Rispondi sempre in italiano»), il fuso orario predefinito in `DEFAULT_TIMEZONE`, lo stile non esiste come impostazione. Con questo step queste scelte stanno in un **file di preferenze** che il server MCP espone come **resource** `utente://preferenze`. È l'**host** (il programma `assistant/`), non il modello, a leggerla una volta all'avvio della sessione e a metterla in cima al prompt di sistema. Cambiando il file, la sessione successiva risponde diversamente senza toccare il codice.

È la seconda primitiva MCP del corso dopo i tool: un tool lo decide il modello durante la conversazione, una resource la decide l'host prima di chiamare il modello (slide 9). La variante (MCP invece di FastAPI o funzione locale) è fissata dallo step stesso.

## 2. Che cosa è stato verificato (2026-11-17)

- Con le versioni fissate (`fastmcp==3.4.11`, `mcp==1.30.0`) una prova in memoria nello scratchpad: `@mcp.resource("utente://preferenze", name="preferenze", mime_type="application/json")` su una funzione che restituisce testo; il client vede `list_tools` → solo il tool, `list_resources` → `utente://preferenze` (`application/json`), `read_resource` → il testo. Nessuna nuova dipendenza.
- `ClientSession.read_resource(uri: AnyUrl)` esiste nella sessione `mcp` già usata da `assistant/mcp_client.py`; `load_mcp_tools` carica solo i tool.

## 3. Obiettivi (slide 8)

1. Resource `utente://preferenze` con lingua delle risposte, fuso orario predefinito e stile (sintetico o dettagliato).
2. Lettura da parte dell'host a inizio sessione e inserimento in cima al prompt di sistema.
3. La resource non compare tra i tool passati a `bind_tools`.
4. Resource non disponibile: valori predefiniti, segnalati nei log.

Evidenze richieste: «Che ore sono?» usa il fuso predefinito senza chiederlo, con un fuso non ovvio come `America/New_York`; cambiando lingua o stile nel file, la sessione successiva risponde di conseguenza; lettura della resource visibile nei log, separata dalle chiamate ai tool.

**Non obiettivi**: tradurre i testi fissi del programma (rifiuto del router, avviso sulle note, messaggi del terminale, prompt di router, revisore e riassunto), che restano in italiano (*scelta dell'utente*); cambiare le preferenze durante la sessione (si leggono una volta all'avvio; `clear` non le rilegge); preferenze per più utenti; il passo 5 (prompt MCP).

## 4. Scelte dell'utente

- **Fonte principale**: la resource. **Riserva**: per il fuso, `DEFAULT_TIMEZONE` del `.env`, che resta; per lingua e stile, valori fissi.
- **Stile**: due valori. «sintetico»: una o due frasi, solo ciò che è chiesto (il comportamento di oggi). «dettagliato»: la risposta più il contesto utile preso dai risultati degli strumenti, in qualche frase o in un breve elenco (esempio approvato: per «chi ha creato Python?» anche anno, paradigmi, tipizzazione, ambiti d'uso).
- **Lingua**: elenco chiuso: `italiano`, `inglese`, `spagnolo`. Risponde nella lingua scelta solo il modello; i testi fissi restano in italiano.
- **Valore non ammesso** (lingua o stile fuori elenco, fuso inesistente): si parte comunque; per quel campo vale la riserva e un avviso nel log nomina il campo; gli altri campi validi restano.
- **Docker**: il file delle preferenze è **montato** nel container, così una modifica vale dalla sessione successiva senza `docker compose build`.
- **Avviso sui falsi successi delle note**: resta solo in italiano. Con `inglese` o `spagnolo` una nota dichiarata salvata o eliminata senza lo strumento non produce l'avviso: è un limite da registrare nel README e da osservare nella prova reale.
- **Revisore**: invariato. Il timore era che scambiasse il contesto dello stile «dettagliato» per una deviazione dal tema o una risposta in inglese per un errore; la sonda (5.7) non lo conferma, quindi si verifica nella prova reale e si interviene solo se succede.

## 5. Comportamento

### 5.1 Il file

- `config/preferenze.json`, versionato (non contiene credenziali), con i valori di oggi:
  ```json
  {"lingua": "italiano", "fuso_orario": "Europe/Rome", "stile": "sintetico"}
  ```
- Percorso configurabile con la variabile `PREFERENCES_FILE` (predefinito `config/preferenze.json`, relativo alla radice del progetto, come `SCOPE_FILE`). L'host la passa al server nell'ambiente, come oggi `DEFAULT_TIMEZONE` (`server_env`).
- Campi: `lingua` (`italiano` | `inglese` | `spagnolo`), `fuso_orario` (nome IANA esatto, validato con `lab_server/timezones.py` come `DEFAULT_TIMEZONE`), `stile` (`sintetico` | `dettagliato`). Valori confrontati esattamente come scritti (*scelta di Claude*: come il fuso IANA, maiuscole comprese). Un campo assente vale come non valido: riserva e avviso. Campi in più sono ignorati (*scelta di Claude*).

### 5.2 Server MCP

- `create_server` registra `@mcp.resource("utente://preferenze", name="preferenze", mime_type="application/json")`, con descrizione «Preferenze dell'utente per le risposte: lingua, fuso orario predefinito, stile.». Restituisce il **testo del file così com'è**, letto a ogni richiesta (slide 7). Se il file non si legge, la lettura fallisce con un errore MCP (la resource «non è disponibile» per l'host).
- **Fuso del server** (*scelta di Claude*): il server usa come fuso predefinito (`get_current_time` senza `timezone`, «oggi» degli strumenti delle date) il `fuso_orario` delle preferenze se valido, altrimenti `DEFAULT_TIMEZONE` come oggi. Così host e server non sono mai in disaccordo (per esempio New York nel prompt e Roma negli strumenti). Lo stabilisce `lab_server/__main__.py` all'avvio, con la stessa funzione di validazione dell'host (5.3).
- `python -m lab_server.check` elenca anche le resource (URI, nome, tipo) dopo i tool, per verificare dal terminale che la resource c'è e non è un tool (*scelta di Claude*).

### 5.3 Validazione (funzione pura)

Un modulo `lab_server/preferences.py` (usato sia dal server sia dall'host, come già `lab_server/timezones.py`) con una funzione pura che riceve il testo della resource (o `None` se non disponibile) e il fuso di riserva, e restituisce le preferenze valide più l'elenco degli avvisi:
- testo `None` → tutte le riserve, avviso «resource non disponibile»;
- JSON non valido o non un oggetto → tutte le riserve, avviso «contenuto non valido»;
- per ogni campo assente o non ammesso → riserva di quel campo, un avviso che nomina il campo e il valore trovato.
Riserve: `lingua=italiano`, `stile=sintetico` (il comportamento di oggi), `fuso_orario=` il fuso di riserva (`DEFAULT_TIMEZONE`).

### 5.4 Host

- `MCPClient` offre una lettura sincrona di una resource per URI, sulla stessa sessione dei tool. Un errore della lettura (resource assente, file illeggibile) non ferma l'avvio: diventa testo `None` per la validazione. Un collegamento caduto al server resta l'errore di oggi.
- `__main__` legge `utente://preferenze` **una volta**, subito dopo l'avvio del server e la scoperta dei tool, prima della prima domanda; valida (5.3); passa le preferenze a terminale e grafo.
- **Prompt di sistema**: il blocco delle preferenze sta **in cima** al primo messaggio di sistema, prima delle istruzioni di oggi (slide 7 e 8). Testo indicativo (esatto al piano):
  ```
  Preferenze dell'utente (dalla resource utente://preferenze):
  - Rispondi sempre in <lingua>.
  - Stile: <sintetico: rispondi in una o due frasi, solo con ciò che è chiesto | dettagliato: aggiungi alla risposta il contesto utile preso dai risultati degli strumenti, in qualche frase o in un breve elenco>.
  - Fuso orario predefinito: <fuso>; usalo quando l'utente non indica un fuso orario, senza chiederglielo.
  ```
  Le istruzioni di oggi perdono «Rispondi sempre in italiano» e «in modo chiaro e conciso» (sostituiti dalle preferenze) e la frase del fuso usa lo stesso fuso. Il riassunto resta in fondo al primo messaggio di sistema, come oggi.
- Revisione del 2026-11-17 dopo la prova reale (scelta di Claude in autonomia concessa dall'utente): la riga «Fuso orario predefinito» esce dal blocco, che resta di due righe (lingua e stile). Misurato con il grafo reale su 6 temperature, «Che ore sono?»: con la riga del fuso il modello chiamava `get_current_time` 3/6 volte, senza 6/6 (con America/New_York: strumento chiamato e ora di New York 6/6). Il fuso resta nel prompt tramite la frase delle istruzioni «Se l'utente non indica un fuso orario usa `<fuso>`; …» ed è il predefinito del server.
- Il fuso delle preferenze sostituisce `settings.default_timezone` anche per l'«oggi» degli strumenti delle note (oggi `datetime.now(zone)` in `__main__`).
- La resource **non** finisce fra i tool: i tool passati a `build_graph`/`bind_tools` restano quelli di `load_mcp_tools` più le note.

### 5.5 Log e terminale

- All'avvio, una riga `INFO` dedicata, distinta dalle chiamate ai tool (`[strumento] …`, a `DEBUG`): `[preferenze] utente://preferenze: lingua=<…>, fuso_orario=<…>, stile=<…>` (testo esatto al piano). Con preferenze tutte valide nessun altro messaggio.
- Ogni avviso della validazione è una riga `WARNING` `[preferenze] …` che dice che cosa è successo e quale riserva vale (per esempio `[preferenze] stile 'medio' non ammesso: uso 'sintetico'`; `[preferenze] resource non disponibile (…): uso italiano, sintetico, Europe/Rome`).
- Con `LOG_LEVEL=DEBUG` la richiesta MCP `resources/read` compare nei log del client/server, separata dalle `tools/call`.

### 5.6 Docker

- `compose.yaml`, servizio `app`: il file delle preferenze montato in sola lettura in `/app/config/preferenze.json` (*scelta dell'utente*: modifica valida alla sessione successiva). `config/ambito.txt` resta copiato nell'immagine come oggi.

### 5.7 Revisore

- **Il revisore non cambia** (*scelta dell'utente dopo la sonda*).
- Sonda del 2026-11-17 (revisore reale, risultati degli strumenti nella richiesta, 3 ripetizioni): senza informazioni sulle preferenze approva la risposta dettagliata su Python (3/3) e la risposta in inglese (3/3) e boccia la risposta dettagliata ma incompleta (3/3). Con una riga «Preferenze dell'utente: risposte in …, stile …» gli stessi 9/9: nessun beneficio misurato.
- L'indicazione `FEEDBACK` resta in italiano; il blocco preferenze in cima al prompt dell'agente indica comunque la lingua. Nella prova reale si osservano stile dettagliato, inglese e, se capita, una nuova risposta dopo una bocciatura (torna all'italiano?): se succede, si registra come limite.

## 6. Test e verifiche

### Test automatici (senza LM Studio)
- Validazione: tutto valido; testo `None`; JSON non valido; non un oggetto; ogni campo assente o non ammesso singolarmente (riserva solo per quel campo, avviso con nome e valore); fuso di riserva usato quando il fuso non è valido; campi in più ignorati.
- Server (client FastMCP in memoria): la resource è elencata con URI, nome e tipo; la lettura restituisce il testo del file; file mancante → errore; `list_tools` non contiene la resource; fuso predefinito del server dalle preferenze e, se non valido, da `DEFAULT_TIMEZONE`.
- Client MCP (server di prova di `tests/mcp_test_server.py` esteso con una resource): lettura sincrona; resource assente → `None` senza fermare la sessione; i tool caricati non contengono la resource.
- Prompt di sistema: il blocco preferenze è in cima, con lingua, stile e fuso; per ciascuna lingua e ciascuno stile il testo atteso; nessun «Rispondi sempre in italiano» rimasto nelle istruzioni fisse; il riassunto resta in fondo.
- Avvio: riga `INFO` `[preferenze] …`; con resource non disponibile, riserve e `WARNING`, l'avvio prosegue.- Restano verdi tutti i test esistenti.

### Prova reale con LM Studio (separata, attivata esplicitamente)
- `fuso_orario: America/New_York`, «Che ore sono?» → ora di New York senza chiedere il fuso (slide 8).
- `lingua: inglese`, nuova sessione → risposte in inglese; `stile: dettagliato` → «chi ha creato Python?» più lunga con paradigmi e tipizzazione.
- Valore non ammesso e file mancante → avvio con riserve e avvisi nel log.
- Con `inglese` e `dettagliato`: giudizi del revisore (bocciature inutili?) e, se capita, lingua della risposta rifatta; una richiesta di nota per osservare il limite dell'avviso solo italiano.
- Log con `LOG_LEVEL=DEBUG`: lettura della resource una volta, prima della prima domanda, distinta dalle chiamate ai tool.
- Docker via pipe: modifica del file montato, nuova sessione senza `build`, comportamento cambiato.
Esiti nel README.

## 7. Ordine di lavoro e branch

Branch `feature/preferenze` da `developer`; merge `--no-ff` dopo la prova reale e l'ok dell'utente, push, eliminazione del branch. README (configurazione con `PREFERENCES_FILE`, sezione sulle preferenze, diagnosi, esiti), `.env.example` e `CLAUDE.md` (struttura: `lab_server/preferences.py`, `config/preferenze.json`) aggiornati.

## 8. Scelte fatte da Claude (da rivedere)

- Server che usa anche lui il fuso delle preferenze (5.2), con validazione condivisa in `lab_server/preferences.py`.
- File in `config/preferenze.json`, versionato, percorso in `PREFERENCES_FILE`; resource che restituisce il testo del file e host che valida.
- Valori confrontati esattamente; campi in più ignorati; campo assente = non valido.
- Preferenze lette una volta per sessione; `clear` non le rilegge.
- `lab_server.check` che elenca anche le resource.
- Testo del blocco preferenze in cima al prompt e rimozione di «Rispondi sempre in italiano» e «in modo chiaro e conciso» dalle istruzioni fisse.

## 9. Lasciato al piano

- Testi esatti del blocco preferenze, delle righe di log e degli avvisi.
- Nomi e firme delle funzioni (validazione, lettura sincrona della resource in `MCPClient`, nuova firma di `system_prompt`).
