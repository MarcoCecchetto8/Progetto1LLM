# Assistente del laboratorio

Applicazione da terminale in Python che conversa con un modello locale servito da LM Studio. Il flusso è un grafo LangGraph esplicito (nodi `model`, `tools`, `step_limit`), la cronologia resta in memoria per la sola sessione e il modello può chiedere l'ora tramite lo strumento `get_current_time`, con fuso orario IANA esplicito.

Gli strumenti sono esposti da un **server MCP** scritto con FastMCP (`lab_server/`):

| Ruolo MCP | Nel progetto |
|---|---|
| Host | l'applicazione da terminale con LangGraph (`assistant/`) |
| Client MCP | `assistant/mcp_client.py`: avvia `python -m lab_server` come sottoprocesso (trasporto stdio), tiene una sola sessione aperta per tutto il programma, legge il catalogo (`tools/list`) e lo converte in tool LangChain con `langchain-mcp-adapters` |
| Server MCP | `lab_server/`: registra gli strumenti con `@mcp.tool` ed esegue le chiamate (`tools/call`) |

Nome, descrizione e schema degli strumenti arrivano dal server (discovery): l'assistente non li riscrive. Dopo `bind_tools` il percorso nel grafo è lo stesso di prima: il modello propone la chiamata, il nodo `tools` la esegue tramite MCP e il risultato rientra come `ToolMessage` con lo stesso `tool_call_id`.

Le **note** seguono un'altra strada: sono salvate in un database SQLite (`data/notes.db`, non versionato) dietro un piccolo servizio **FastAPI** (`notes_service/`), e i tre strumenti `add_note`, `list_notes` e `delete_note` sono wrapper scritti a mano in `assistant/notes.py` che chiamano il servizio via HTTP. A differenza degli strumenti MCP, qui non c'è discovery: nome, descrizione e schema sono definiti nell'assistente. L'eliminazione chiede conferma da terminale (`[s/N]`).

Un controllo del programma, non del modello, segnala i falsi successi: se la risposta finale dice di aver salvato o eliminato una nota ma nello stesso turno lo strumento corrispondente (`add_note` o `delete_note`) non ha risposto con successo, sotto la risposta compare un avviso (`⚠ Attenzione: nessuna nota è stata salvata (lo strumento non l'ha confermato).` oppure `... eliminata ...`). L'avviso fa parte della risposta e resta nella cronologia. Serve perché il modello locale a volte afferma di aver fatto un'operazione che non ha eseguito.

I comandi qui sotto sono stati eseguiti su Windows 11 con PowerShell, Python 3.14.2 e Docker Desktop (Docker 29.9.2).

## Requisiti

- Python 3.14
- Docker Desktop (solo per l'avvio con Docker)
- LM Studio con il server attivo (porta predefinita `1234`) e un modello caricato che supporti il tool calling. È stato provato con `google/gemma-4-e2b`.

## Configurazione

Tutta la configurazione arriva da variabili d'ambiente, lette dal file `.env` (non versionato):

```powershell
Copy-Item .env.example .env
```

L'identificativo del modello va preso da quelli restituiti dal server, non inventato:

```powershell
Invoke-RestMethod http://localhost:1234/v1/models | Select-Object -ExpandProperty data | Select-Object id
```

| Variabile | Obbligatoria | Default | Note |
|---|---|---|---|
| `LMSTUDIO_BASE_URL` | sì | — | `http://localhost:1234/v1` in locale; con Docker Compose viene sovrascritta con `http://host.docker.internal:1234/v1` |
| `LMSTUDIO_MODEL` | sì | — | id restituito da `GET /v1/models` |
| `LMSTUDIO_TIMEOUT` | no | `120` | secondi |
| `LMSTUDIO_TEMPERATURE` | no | `0.2` | |
| `MAX_STEPS` | no | `5` | invocazioni massime del modello per domanda (≥ 1) |
| `DEFAULT_TIMEZONE` | no | `Europe/Rome` | nome IANA esatto (maiuscole comprese), validato all'avvio sull'elenco del pacchetto `tzdata` |
| `LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SHOW_REASONING` | no | `true` | `true` o `false`: mostra o nasconde il ragionamento del modello durante il turno |
| `SCOPE_FILE` | no | `config/ambito.txt` | file con l'ambito dell'assistente per il router (percorso relativo alla radice del progetto); se manca o è vuoto l'avvio si ferma con `SCOPE_FILE non valida: '<percorso>' non esiste o è vuoto.` |
| `NOTES_SERVICE_URL` | no | vuota | vuota in locale: l'assistente avvia da solo il servizio delle note su `http://127.0.0.1:8000`; con Docker Compose viene impostata a `http://notes:8000` |

## Avvio locale (PowerShell)

Dalla cartella del progetto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m assistant
```

Il servizio delle note viene avviato dall'assistente (all'avvio compare `[note] servizio: http://127.0.0.1:8000`) e fermato all'uscita. Finché l'assistente è in esecuzione, la documentazione interattiva è su http://127.0.0.1:8000/docs. Le note stanno in `data/notes.db`, escluso da Git.

## Avvio con Docker

LM Studio resta sull'host: il container lo raggiunge tramite `host.docker.internal`.

```powershell
docker compose build
docker compose run --rm app
```

Si usa `run` e non `up`, perché `up` non collega il terminale all'input dell'applicazione.

Compose avvia anche un secondo container, `notes`, con il servizio delle note (porta 8000 pubblicata solo su `127.0.0.1` dell'host, non raggiungibile dalla rete). Le note stanno nella cartella `data/` del progetto, montata nel container: sono le stesse dell'avvio locale. Per fermare il servizio dopo l'uso:

```powershell
docker compose down
```

Non usare insieme l'assistente locale e quello Docker: entrambi vogliono la porta 8000.

## Comandi

| Input | Effetto |
|---|---|
| `help` | elenca comandi e modi di uscita |
| `clear` | svuota la cronologia, pulisce lo schermo (solo se l'output è un terminale), ristampa l'intestazione e conferma con `Cronologia svuotata.` |
| `quit`, `exit` | uscita con `Arrivederci!` |
| Ctrl+C al prompt, Ctrl+D (Linux/Docker), Ctrl+Z + Invio (Windows) | uscita con `Arrivederci!` |
| Ctrl+C mentre il modello lavora | ferma solo il turno: compare `Risposta interrotta.` e si torna al prompt |
| Ctrl+C alla domanda `[s/N]` di un'eliminazione | esce senza eliminare nulla |
| riga vuota | ignorata |

I comandi non distinguono maiuscole e minuscole.

Un turno interrotto con Ctrl+C non entra nella cronologia. Uno strumento già eseguito non viene annullato: una nota già salvata resta salvata. Il Ctrl+C ferma il modello al pezzo successivo della risposta; uno strumento già in esecuzione (chiamata MCP o HTTP al servizio delle note) viene invece atteso fino alla fine, poi compare `Risposta interrotta.`. Il servizio delle note e il server degli strumenti dovrebbero restare attivi dopo l'interruzione: è da verificare nella prova reale.

## Che cosa si vede durante un turno

La risposta arriva in streaming, mentre il modello la scrive:

- il **ragionamento** del modello, attenuato (grigio), sotto l'intestazione `[ragionamento]`, nella lingua in cui il modello lo scrive;
- ogni **strumento** richiesto, su una riga propria con nome e argomenti (`[strumento] <nome> <argomenti>`), poi l'esito (`[strumento] <nome> → <risultato>`, oppure `[strumento] <nome> errore → <risultato>`);
- la **risposta**, token per token; senza colori (pipe, file, `-T`), se prima c'è il ragionamento, la risposta comincia sotto l'intestazione `[risposta]`, su una riga propria;
- l'eventuale avviso del controllo dei falsi successi, in fondo, dopo la risposta.

Con `SHOW_REASONING=false` il ragionamento non compare e resta solo la riga «…sto pensando» fino al primo strumento o al primo token della risposta. Se il modello non invia il ragionamento, non c'è nulla da mostrare. Il ragionamento non entra nella cronologia. I colori compaiono solo se l'uscita è un terminale: con pipe, file o `docker compose run -T` il contenuto è lo stesso, senza sequenze di colore.

## Router dell'ambito

Prima dell'agente, un router decide se la domanda rientra nell'ambito dell'assistente: strumenti del laboratorio, linguaggi di programmazione, informatica, intelligenza artificiale, saluti e domande sull'assistente stesso. Usa lo stesso modello di LM Studio, con il ragionamento spento e un output strutturato (categoria e motivo); riceve la domanda e gli ultimi messaggi di testo della conversazione, così un seguito come «e a Tokyo?» resta in ambito.

- **In ambito**: la domanda passa all'agente come sempre.
- **Fuori ambito**: nessuna chiamata al modello dell'agente e nessuno strumento; la risposta è un messaggio fisso con il motivo: `Posso aiutarti solo con gli strumenti del laboratorio, i linguaggi di programmazione, l'informatica e l'intelligenza artificiale. Motivo: <motivo>`. Domanda e rifiuto entrano nella cronologia.
- **Errore del router** (risposta non valida): la domanda passa all'agente e nel log compare un avviso.
- **Dove si modifica l'ambito**: `config/ambito.txt` (descrizione ed esempi con la categoria attesa); un altro file si indica con `SCOPE_FILE`. La modifica vale dalla sessione successiva, senza toccare il codice. Con Docker il file è copiato nell'immagine: dopo una modifica serve `docker compose build`.
- **Log**: a ogni decisione una riga `[router] categoria=<categoria> motivo=<motivo> → agente` oppure `→ rifiuto`; all'avvio `[router] ambito: <percorso> (<n> righe)`.
- **Limite, il tempo**: il router è una chiamata in più al modello per ogni domanda: circa 23 s per decisione, misurati su questo computer.
- **Limite, la precisione**: nelle sonde con 9 domande il router ha classificato bene 6 su 9 con la sola descrizione dell'ambito e 9 su 9 con gli esempi di `config/ambito.txt`. Sono domande di sonda, non ancora la prova reale; il modello può comunque sbagliare.

## Log

I log vanno su stderr. All'avvio compare il catalogo letto dal server MCP; con `LOG_LEVEL=INFO` compare poi una riga per ogni chiamata a uno strumento, con l'id della chiamata del modello, gli argomenti e l'esito (`ok` o `errore`), per esempio:

```
[mcp] catalogo: get_current_time
[strumento] get_current_time call_id=1polVGvPjXs42xILRLFmbMpl47V0LucQ argomenti={"timezone": "Asia/Tokyo"} esito=ok → Asia/Tokyo: 2026-11-09T02:09:34+09:00
```

Compaiono anche un avviso quando si raggiunge il limite di passaggi e, se il server MCP si ferma durante la sessione, la riga `[mcp] collegamento con il server perso: ...`, distinta dagli errori degli strumenti (`esito=errore`). Le righe `[strumento] ... call_id=... esito=...` sono a livello `DEBUG`: si vedono con `LOG_LEVEL=DEBUG` (durante il turno gli strumenti si vedono già nel flusso descritto sopra). Con `LOG_LEVEL=DEBUG` si vedono anche i nodi del grafo, l'instradamento, il contatore `steps/MAX_STEPS`, i messaggi rimossi dalla pulizia, i log HTTP delle librerie e i log del server MCP, che altrimenti non scrive nulla sul terminale.

## Test

I test automatici non richiedono LM Studio: usano un modello finto e un istante fisso per l'orologio.

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest
```

Esito al 2026-11-09: 295 test superati. Alcuni test avviano davvero un server MCP di prova in stdio (`tests/mcp_test_server.py`): ogni avvio richiede alcuni secondi.

## Verifica diretta del server MCP

Senza assistente e senza modello, si possono controllare catalogo e chiamate del server (lo stesso avvio in stdio usato dall'assistente):

```powershell
python -m lab_server.check
python -m lab_server.check get_current_time timezone=Asia/Tokyo
python -m lab_server.check get_current_time timezone=Mars/Olympus
python -m lab_server.check convert_units value=3 from_unit=hl to_unit=l
python -m lab_server.check convert_units value=3 from_unit=hl to_unit=kg
python -m lab_server.check calculate "expression=10 * 7 / 9"
python -m lab_server.check calculate "expression=__import__('os')"
python -m lab_server.check find_holiday name=Pasqua
python -m lab_server.check add_days days=24
python -m lab_server.check date_info date=25/12/2026
python -m lab_server.check search_catalog query=funzionale
python -m lab_server.check get_item code=PY
python -m lab_server.check get_item code=XYZ
```

Il primo comando stampa nome, descrizione e schema di ogni strumento; il secondo il risultato (`Asia/Tokyo: ...`); il terzo `ERRORE: Fuso orario sconosciuto: "Mars/Olympus". ...` con codice d'uscita 1. Il quarto stampa `3 hl = 300 l`; il quinto `ERRORE: Conversione impossibile: hl è un'unità di volume, kg di peso.` con codice d'uscita 1. Il sesto stampa `10 * 7 / 9 = 7.777777777777778`; il settimo `ERRORE: Carattere "_" non ammesso: ...` con codice d'uscita 1. Le date: `find_holiday` stampa per esempio `Pasqua 2026 (2026-04-05, domenica) è già passata; la prossima è il 2027-03-28, domenica, fra 139 giorni. Indicativo, non normativo.` (con oggi 2026-11-09); `add_days` la data fra 24 giorni (per esempio `2026-11-09 + 24 giorni = 2026-12-03, giovedì — futura, fra 24 giorni. ...`); `date_info` con `25/12/2026` stampa `ERRORE: Data "25/12/2026" non valida: formato atteso AAAA-MM-GG ...` con codice d'uscita 1. Il catalogo dei linguaggi: `search_catalog` con `query=funzionale` stampa `Trovati 8 linguaggi per "funzionale", mostrati 5:` seguito da un elenco di codice, nome e anno (da `HS: Haskell (1990)` a `PY: Python (1991)`) e dall'invito a ripetere la ricerca con `max_results` più alto; `get_item` con `code=PY` stampa la scheda di Python (anno, autori, paradigmi, tipizzazione, descrizione); con `code=XYZ` stampa `ERRORE: Codice "XYZ" non presente nel catalogo: usa search_catalog per trovare il codice.` con codice d'uscita 1. In PowerShell un argomento con spazi va tra virgolette. Gli argomenti si scrivono come `chiave=valore`; i numeri (`value=2.5`) vengono letti come numeri.

## Verifica diretta del servizio delle note

Senza assistente e senza modello. In un terminale si avvia il servizio (database temporaneo, porta 8000 libera):

```powershell
python -m notes_service --db $env:TEMP\notes-prova.db
```

In un secondo terminale:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/notes -ContentType 'application/json' -Body '{"text":"prova","due_date":"2026-11-13"}'
Invoke-RestMethod http://127.0.0.1:8000/notes
Invoke-RestMethod -Method Delete http://127.0.0.1:8000/notes/1
```

La `POST` restituisce `{"id":1,"text":"prova","due_date":"2026-11-13","created_at":"2026-11-09T16:06:38+00:00"}` (`created_at` è in UTC), la `GET` `{"total":1,"notes":[...]}` con quella nota, la `DELETE` la nota eliminata. Il servizio scrive su stderr una riga per ogni creazione (`nota creata id=1 testo=prova scadenza=2026-11-13`) ed eliminazione. `http://127.0.0.1:8000/docs` risponde 200. Si ferma con Ctrl+C.

Con Docker (2026-11-09): `docker compose config`, `docker compose build` e `docker compose up -d notes` vanno a buon fine; `docker compose ps` mostra `notes` acceso con `127.0.0.1:8000->8000/tcp` (porta pubblicata solo su localhost). Dall'host le stesse tre chiamate funzionano e `data/notes.db` viene scritto attraverso la cartella montata (l'utente non root `appuser` del container riesce a scrivere). `docker compose down` ferma e rimuove il container.

## Prova reale

Va eseguita esplicitamente, con LM Studio acceso e il modello caricato. È l'unica prova che dimostra che il modello locale sa usare lo strumento. Esiti ottenuti il 2026-10-27 con `google/gemma-4-e2b`, in locale (`python -m assistant`) e con Docker (`docker compose run --rm -T app`), in entrambi i casi con le domande inviate da pipe. Il 2026-10-30 la sessione è stata provata anche a mano, in PowerShell e con `docker compose run --rm app` (con terminale).

| Passo | Atteso | Esito |
|---|---|---|
| 1. Avvio | intestazione con il modello | ok |
| 2. `ciao` | il modello si presenta | ok |
| 3. `che ora è?` | log con `timezone=Europe/Rome`, ora uguale a quella di Windows, domanda su un altro fuso | ok |
| 4. `e a Tokyo?` | log con `timezone=Asia/Tokyo` e ora corretta (+8 ore rispetto a Roma in ora solare) | ok |
| 5. `mi chiamo Marco, ricordatelo`, poi `come mi chiamo?`; quindi `clear` e di nuovo `come mi chiamo?` | prima ricorda il nome, dopo `clear` no | ok |
| 6a. LM Studio irraggiungibile (`LMSTUDIO_BASE_URL` su una porta chiusa) | messaggio con l'indirizzo provato, codice d'uscita 1 | ok (solo in locale) |
| 6b. `LMSTUDIO_MODEL=inventato` | messaggio con l'elenco dei modelli disponibili, codice d'uscita 1 | ok (solo in locale) |
| 6c. `quit` | `Arrivederci!`, codice d'uscita 0 | ok |
| 6d. Ctrl+C durante l'attesa e al prompt | `Arrivederci!` senza traceback | ok, in locale e con Docker |

### Prova reale con il server MCP (orologio)

Dal 2026-11-08 l'orologio passa dal server MCP. Esiti:

| Passo | Atteso | Esito |
|---|---|---|
| 1. Avvio | `[mcp] catalogo: get_current_time` nel log, poi l'intestazione | ok (2026-11-08, locale, domande da pipe) |
| 2. `che ora è a Tokyo?` | riga `[strumento] get_current_time call_id=... argomenti={"timezone": "Asia/Tokyo"} esito=ok` e ora corretta | ok (2026-11-08, locale, domande da pipe) |
| 3. `che ora è?`, poi `e a Tokyo?`, a mano in PowerShell | due chiamate con `Europe/Rome` e `Asia/Tokyo` | ok (2026-11-08) |
| 4. Memoria e `clear` | come nella prova precedente | ok (2026-11-08) |
| 5. `docker compose run --rm app` con `che ora è a Tokyo?` | catalogo e chiamata come in locale | ok (2026-11-08) |
| 6. Ctrl+C ripetuto al prompt e durante l'avvio | un solo `Arrivederci!`, senza traceback | ok (2026-11-08) |

### Prova reale del convertitore di unità

Lo strumento `convert_units` accetta solo unità metriche di un elenco chiuso (lunghezza `mm`…`km`; peso `mg`…`kg`, `q`, `t`; volume `ml`…`hl`, `m3`; temperatura `C`, `K`) e rifiuta con un errore le conversioni fra categorie diverse, le quantità negative e le temperature sotto lo zero assoluto.

| Domanda | Atteso | Esito |
|---|---|---|
| `quanti cm sono 2,5 km?` | `convert_units` km → cm, `250000 cm` | ok (2026-11-08, domande da pipe) |
| `converti 3 hl in litri` | `convert_units` hl → l, `300 l` | ok (2026-11-08, domande da pipe) |
| `quanti kg sono 2 quintali?` | `convert_units` q → kg, `200 kg` | ok (2026-11-08, domande da pipe) |
| `20 gradi celsius in kelvin` | `convert_units` C → K, `293.15 K` | ok (2026-11-08, domande da pipe) |
| `converti 5 km in kg` | nessun numero inventato | il modello spiega che le categorie sono diverse **senza chiamare lo strumento** (nessuna riga `[strumento]`); l'errore dello strumento è verificato con `python -m lab_server.check` e nei test |
| Le stesse domande a mano, in PowerShell e con Docker | come sopra | ok (2026-11-08) |

### Prova reale della calcolatrice sicura

Lo strumento `calculate` analizza l'espressione con il modulo `ast` di Python, senza `eval`: accetta solo numeri, `+ - * /`, parentesi e potenza (`^` o `**`) e rifiuta con un errore lettere, funzioni, equazioni, divisioni per zero, espressioni malformate, troppo lunghe (oltre 200 caratteri) o con risultati oltre 10^100.

| Domanda | Atteso | Esito |
|---|---|---|
| `quanto fa 10 * 7 / 9?` | `calculate` con `10 * 7 / 9`, `7.777777777777778` | ok (2026-11-08, domande da pipe) |
| `2 alla 5` | `calculate` con `2^5`, `32` | ok (2026-11-08, domande da pipe) |
| `risolvi 2x = 28` | `calculate` con `28 / 2`, `x = 14` | con la prima versione delle istruzioni il modello ha risolto da solo, senza strumento; con le istruzioni attuali chiama `calculate` con `28 / 2` (2026-11-08, domande da pipe) |
| `calcola sqrt(16)` | nessun risultato inventato | il modello spiega che le funzioni non sono disponibili, senza chiamare lo strumento (2026-11-08, domande da pipe) |
| Le stesse domande a mano, in PowerShell e con Docker | come sopra | ok (2026-11-08) |

### Prova reale di giorni e scadenze

Quattro strumenti, tutti con date ISO (`AAAA-MM-GG`) e «oggi» calcolato nel fuso `DEFAULT_TIMEZONE`: `date_info` (giorno della settimana, festività, passata/oggi/futura con i giorni di distanza, per esempio «futura, fra 53 giorni» o «passata, 1 giorno fa»), `find_holiday` (data di una festività nazionale; se quest'anno è già passata lo dice e dà la prossima, con i giorni che mancano), `add_days` (data fra N giorni, anche negativi) e `days_between` (giorni fra due date). Le festività a data fissa sono nel file `lab_server/holidays.json`; Pasqua e Lunedì dell'Angelo sono calcolati. Anni ammessi: 1900–2200. Ogni risultato termina con «Indicativo, non normativo.».

| Domanda | Atteso | Esito |
|---|---|---|
| `che giorno della settimana è pasqua?` | `find_holiday` Pasqua: avviso che Pasqua 2026 è passata e data della prossima (2027-03-28, domenica) | ok (2026-11-08, domande da pipe) |
| `che giorno sarà natale?` | `find_holiday` Natale: 2026-12-25, venerdì | ok (2026-11-08, domande da pipe) |
| `che giorno sarà tra 24 giorni?` | `add_days` 24 | ok (2026-11-08, domande da pipe): il modello ha chiesto prima l'ora a `get_current_time` e poi `add_days` con la data di oggi → 2026-12-02, mercoledì |
| `quanti giorni mancano a natale?` | `days_between` fino al 2026-12-25 | ok (2026-11-08, domande da pipe): 47 giorni |
| `quanti giorni mancano a pasqua?` | numero dato dagli strumenti (`find_holiday` scrive «fra N giorni», oppure `days_between`), mai contato dal modello | prima prova (2026-11-09) fallita: solo `find_holiday` e «49 giorni» contati dal modello (erano 139). Dopo la correzione ok (2026-11-09): `find_holiday` Pasqua → «fra 139 giorni», riportato dal modello; anche `quanti giorni mancano a natale?` → `find_holiday` Natale «fra 46 giorni». Subito dopo, `che giorno della settimana è pasqua?` ha avuto risposta dalla cronologia senza nuove chiamate: data giusta (2027-03-28, domenica), ma senza ripetere che la Pasqua 2026 è già passata |
| Le stesse domande a mano, in PowerShell e con Docker; memoria e `clear` | come sopra | ok (2026-11-08) |

Con Docker Desktop su Windows il container ha raggiunto LM Studio con l'indirizzo `http://host.docker.internal:1234/v1` senza altre modifiche.

### Prova reale del catalogo

Due strumenti sul catalogo dei linguaggi di programmazione (20 linguaggi, file locale `lab_server/catalog.json`): `search_catalog` cerca per parole chiave (nome, autore, paradigma, anno, descrizione) e restituisce codice, nome e anno con il totale trovato (da 1 a 20 risultati, 5 per default); `get_item` dà la scheda completa di un linguaggio dal suo codice (per esempio `PY`, `HS`).

| Domanda | Atteso | Esito |
|---|---|---|
| `chi ha creato Haskell?` | `search_catalog` poi `get_item` con il codice `HS`, autori nella risposta | prima prova (2026-11-09) fallita: nessuno strumento chiamato e risposta «non ho trovato informazioni». Dopo l'aggiunta alle istruzioni di sistema («chiama sempre gli strumenti del catalogo prima di rispondere») ok, anche ripetuta: `search_catalog` «Haskell», `get_item` `HS`, risposta «Comitato Haskell» |
| `quali linguaggi funzionali ci sono nel catalogo?` | `search_catalog` con `funzionale`, elenco dei risultati (8 in totale) | ok (2026-11-09): query al singolare `funzionale`; letto «ci sono altri 3 risultati», il modello ha ripetuto la ricerca con `max_results` 10 e ha elencato tutti gli 8 |
| `quali linguaggi funzionali sono nati prima del 1980?` | ricerca e controllo degli anni, nessun anno inventato | ok (2026-11-09): risposta dalla cronologia della domanda precedente, senza nuove chiamate: solo Lisp (1958) |
| `c'è Brainfuck nel catalogo?` | `search_catalog` senza risultati, risposta che dice che non c'è | ok (2026-11-09) |
| `dimmi tutto sul linguaggio con codice XYZ` | `get_item` con errore, nessuna scheda inventata | prima prova (2026-11-09) fallita: nessuna chiamata, il modello ha chiesto il codice. Dopo l'aggiunta alle istruzioni («se l'utente indica un codice, chiama subito `get_item`») ok, anche ripetuta: `get_item` `XYZ` con `esito=errore` ed errore spiegato all'utente |
| Le stesse domande a mano, in PowerShell e con Docker; memoria e `clear` | come sopra | ok (2026-11-09) |

Anche due domande su Python e sul linguaggio C hanno prodotto la sequenza `search_catalog` → `get_item` (`PY`, `C`); la ricerca «C» ha trovato solo C e C++.

### Prova reale delle note

Tre strumenti sulle note persistenti (`add_note`, `list_notes`, `delete_note`), con il servizio FastAPI. Va provata in locale e con Docker, con LM Studio acceso.

Esiti del 2026-11-15 con `google/gemma-4-e2b`, domande inviate da pipe (la conferma `[s/N]` legge la riga successiva dell'input, quindi `s` o `n` vanno sulla riga dopo la domanda).

| Domanda | Atteso | Esito |
|---|---|---|
| `Ricordami di comprare il latte` (e altre due note con scadenza AAAA-MM-GG) | una chiamata `add_note` per richiesta | ok: 3 note salvate, scadenze corrette |
| `Ricordami di consegnare il report venerdì` | una sola chiamata `add_note`, scadenza = il prossimo venerdì | **non superata (limite del modello)**: vedi sotto |
| `Che note ho?` | `list_notes`, ordine per scadenza | ok: scadenze in ordine, poi quelle senza scadenza |
| `Elimina la nota 99` | errore chiaro, nessuna richiesta di conferma, nulla eliminato | ok 4 volte su 5 (errore «Nessuna nota con ID 99»); 1 volta il modello non chiama `delete_note` e risponde che dovrebbe prima verificare |
| eliminazione di una nota vera, rispondendo `n` e poi `s` | con `n` la nota resta, con `s` sparisce | ok |
| riavvio dell'assistente | le note salvate ci sono ancora; le stesse note si vedono da Docker | ok in locale e con Docker (`docker compose run --rm -T app`); una nota salvata da Docker si ritrova nel file locale `data/notes.db` |
| `Elimina le note 3 e 4`, rispondendo `s` e poi `n` | le due conferme arrivano una alla volta, ognuna con la sua nota | ok: la 3 eliminata, la 4 resta |
| Ctrl+C alla domanda `[s/N]` | nessuna eliminazione, «Arrivederci!», porta 8000 liberata | ok (prova a mano dell'utente) |
| `/docs` nel browser mentre l'assistente è in esecuzione | pagina della documentazione interattiva | ok (prova a mano dell'utente) |

**Limite del modello: giorni della settimana.** Con «Ricordami di consegnare il report venerdì» il modello chiama `get_current_time` e spesso `add_days` con un numero di giorni sbagliato, poi risponde «Ho salvato un promemoria…» **senza chiamare `add_note`**. Misura su 5 conversazioni (archivio temporaneo): prima della modifica al prompt 0 salvataggi; dopo, 1 su 5; con il controllo dei falsi successi 0 su 5, ma in tutte e 5 la risposta arriva con l'avviso `⚠ Attenzione: nessuna nota è stata salvata…`. Il rimedio è indicare la data nel formato AAAA-MM-GG.

**Falsi successi.** Senza controllo il modello dichiarava note salvate che non esistevano (1 volta su 5 con «Ricordami di comprare il latte», 3 su 5 con «venerdì»). Con il controllo, nelle stesse misure nessun falso successo è arrivato all'utente senza avviso. Il controllo non rende il modello affidabile: lo rende onesto verso l'utente. Può comparire un avviso ridondante quando il modello stesso dice che nulla è stato eliminato o salvato.

### Prova reale dello streaming

Esiti del 2026-11-16 con `google/gemma-4-e2b`. Le prove con input da pipe (senza terminale, quindi senza colori) le ha eseguite Claude; quelle in un terminale vero (colori, Ctrl+C) le ha eseguite l'utente, tutte con esito positivo.

| Prova | Atteso | Esito |
|---|---|---|
| `Quanto fa 17*23?` | ragionamento attenuato che scorre, poi risposta che scorre | ok: via pipe ragionamento (in inglese), `calculate`, esito `391`, risposta; in PowerShell ragionamento attenuato (prova dell'utente) |
| `Che ore sono a Tokyo?` | ragionamento, riga dello strumento con argomenti, esito, risposta | ok via pipe, in locale e con Docker |
| `SHOW_REASONING=false` | solo «…sto pensando», strumenti e risposta | ok via pipe |
| Ctrl+C durante un ragionamento lungo, poi una domanda con uno strumento MCP e una nota | `Risposta interrotta.` subito, poi strumento e nota funzionano; Ctrl+C al prompt chiude | ok (prova a mano dell'utente) |
| Ctrl+C alla domanda `[s/N]` di un'eliminazione | nessuna eliminazione, `Arrivederci!` | ok in Windows e Docker (prova a mano dell'utente) |
| `Ricordami di consegnare il report venerdì` | se il modello dichiara un salvataggio mai avvenuto, avviso in fondo | ok via pipe: `get_current_time`, `add_days` sbagliato, poi l'avviso in fondo (limite del modello già noto) |
| Docker con terminale (`docker compose run --rm app`) | colori e streaming | ok (prova a mano dell'utente) |
| Docker con `-T` e input da pipe | stesso contenuto, nessun colore, `[risposta]` prima della risposta se c'è il ragionamento | ok (nessun carattere di colore nell'uscita) |

### Prova reale del router

Da eseguire con LM Studio (locale e Docker `-T` con input da pipe). Non ancora eseguita.

| Prova | Atteso | Esito |
|---|---|---|
| Le 9 domande della sonda | ogni domanda classificata come previsto; tempo del router per ciascuna | da provare |
| Almeno 3 domande nuove, non presenti fra gli esempi di `config/ambito.txt` | classificate come previsto | da provare |
| Domanda in ambito | log con categoria, motivo e `→ agente`, poi la risposta dell'agente | da provare |
| Domanda fuori ambito | rifiuto con il motivo, nessuna riga del nodo agente nei log | da provare |
| Modifica di `config/ambito.txt` (per esempio togliere «note») e nuova sessione | il comportamento cambia senza toccare il codice | da provare |
| Docker (`docker compose run --rm -T app` con input da pipe) | stesso comportamento del locale | da provare |

## Diagnosi

| Sintomo | Causa probabile e rimedio |
|---|---|
| `... non valida` o `... mancante` all'avvio | variabile del `.env` assente o con valore non valido: il messaggio indica quale |
| `LM Studio non raggiungibile o risposta non valida su .../models` all'avvio | server di LM Studio spento o su un'altra porta: avviarlo e controllare `LMSTUDIO_BASE_URL` |
| `Modello '...' non trovato. Modelli disponibili: ...` | `LMSTUDIO_MODEL` non corrisponde a un id di `GET /v1/models`: copiarne uno dall'elenco |
| `LM Studio non è raggiungibile all'indirizzo ...` durante la sessione | il server si è fermato: riavviarlo e ripetere la domanda (la sessione continua) |
| `Il modello non ha risposto entro N secondi. Riprova.` | modello lento o ancora in caricamento: riprovare o aumentare `LMSTUDIO_TIMEOUT` |
| `Il contesto del modello è pieno: usa 'clear' ...` | cronologia troppo lunga per il modello: usare `clear` |
| `Limite di passaggi raggiunto: ...` | il modello ha chiamato lo strumento troppe volte per una domanda: riformulare o aumentare `MAX_STEPS` |
| `Impossibile avviare il server degli strumenti (...)` all'avvio | il server MCP non parte: controllare con `python -m lab_server.check` e reinstallare le dipendenze (`pip install -r requirements.txt`) |
| `Il server degli strumenti non espone nessuno strumento.` all'avvio | catalogo vuoto: controllare con `python -m lab_server.check` |
| `Il server degli strumenti non risponde: esci e riavvia l'assistente.` | il server MCP si è fermato durante la sessione: uscire e riavviare l'assistente (con `LOG_LEVEL=DEBUG` si vede il dettaglio) |
| `La porta 8000 è già in uso ...` all'avvio | un altro servizio delle note è già acceso (di solito quello di Docker): `docker compose down` e riavviare |
| `Il servizio delle note non risponde: esci e riavvia l'assistente.` | il servizio delle note si è fermato durante la sessione: uscire e riavviare l'assistente |
| Domande in ambito rifiutate dal router | il modello classifica male: aggiungere esempi di quel tipo in `config/ambito.txt` e riavviare |
| Il ragionamento non compare | il modello non invia `reasoning_content` oppure `SHOW_REASONING=false` nel `.env` |
| Il modello risponde senza riga `[strumento]` nel log | il modello non ha chiamato lo strumento: la risposta non è verificata; riformulare la domanda |
| Il container non raggiunge LM Studio | controllare che il server sia attivo sull'host; se serve, attivare in LM Studio l'opzione per servire sulla rete locale e riprovare |
