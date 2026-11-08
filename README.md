# Assistente del laboratorio

Applicazione da terminale in Python che conversa con un modello locale servito da LM Studio. Il flusso è un grafo LangGraph esplicito (nodi `model`, `tools`, `step_limit`), la cronologia resta in memoria per la sola sessione e il modello può chiedere l'ora tramite lo strumento `get_current_time`, con fuso orario IANA esplicito.

Gli strumenti sono esposti da un **server MCP** scritto con FastMCP (`lab_server/`):

| Ruolo MCP | Nel progetto |
|---|---|
| Host | l'applicazione da terminale con LangGraph (`assistant/`) |
| Client MCP | `assistant/mcp_client.py`: avvia `python -m lab_server` come sottoprocesso (trasporto stdio), tiene una sola sessione aperta per tutto il programma, legge il catalogo (`tools/list`) e lo converte in tool LangChain con `langchain-mcp-adapters` |
| Server MCP | `lab_server/`: registra gli strumenti con `@mcp.tool` ed esegue le chiamate (`tools/call`) |

Nome, descrizione e schema degli strumenti arrivano dal server (discovery): l'assistente non li riscrive. Dopo `bind_tools` il percorso nel grafo è lo stesso di prima: il modello propone la chiamata, il nodo `tools` la esegue tramite MCP e il risultato rientra come `ToolMessage` con lo stesso `tool_call_id`.

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

## Avvio locale (PowerShell)

Dalla cartella del progetto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m assistant
```

## Avvio con Docker

LM Studio resta sull'host: il container lo raggiunge tramite `host.docker.internal`.

```powershell
docker compose build
docker compose run --rm app
```

Si usa `run` e non `up`, perché `up` non collega il terminale all'input dell'applicazione.

## Comandi

| Input | Effetto |
|---|---|
| `help` | elenca comandi e modi di uscita |
| `clear` | svuota la cronologia, pulisce lo schermo (solo se l'output è un terminale), ristampa l'intestazione e conferma con `Cronologia svuotata.` |
| `quit`, `exit` | uscita con `Arrivederci!` |
| Ctrl+C, Ctrl+D (Linux/Docker), Ctrl+Z + Invio (Windows) | uscita con `Arrivederci!` |
| riga vuota | ignorata |

I comandi non distinguono maiuscole e minuscole.

## Log

I log vanno su stderr. All'avvio compare il catalogo letto dal server MCP; con `LOG_LEVEL=INFO` compare poi una riga per ogni chiamata a uno strumento, con l'id della chiamata del modello, gli argomenti e l'esito (`ok` o `errore`), per esempio:

```
[mcp] catalogo: get_current_time
[strumento] get_current_time call_id=1polVGvPjXs42xILRLFmbMpl47V0LucQ argomenti={"timezone": "Asia/Tokyo"} esito=ok → Asia/Tokyo: 2026-11-09T02:09:34+09:00
```

Compaiono anche un avviso quando si raggiunge il limite di passaggi e, se il server MCP si ferma durante la sessione, la riga `[mcp] collegamento con il server perso: ...`, distinta dagli errori degli strumenti (`esito=errore`). Con `LOG_LEVEL=DEBUG` si vedono anche i nodi del grafo, l'instradamento, il contatore `steps/MAX_STEPS`, i messaggi rimossi dalla pulizia, i log HTTP delle librerie e i log del server MCP, che altrimenti non scrive nulla sul terminale.

## Test

I test automatici non richiedono LM Studio: usano un modello finto e un istante fisso per l'orologio.

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest
```

Esito al 2026-11-08: 211 test superati. Alcuni test avviano davvero un server MCP di prova in stdio (`tests/mcp_test_server.py`): ogni avvio richiede alcuni secondi.

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
```

Il primo comando stampa nome, descrizione e schema di ogni strumento; il secondo il risultato (`Asia/Tokyo: ...`); il terzo `ERRORE: Fuso orario sconosciuto: "Mars/Olympus". ...` con codice d'uscita 1. Il quarto stampa `3 hl = 300 l`; il quinto `ERRORE: Conversione impossibile: hl è un'unità di volume, kg di peso.` con codice d'uscita 1. Il sesto stampa `10 * 7 / 9 = 7.777777777777778`; il settimo `ERRORE: Carattere "_" non ammesso: ...` con codice d'uscita 1. Le date: `find_holiday` stampa per esempio `Pasqua 2026 (2026-04-05, domenica) è già passata; la prossima è il 2027-03-28, domenica. Indicativo, non normativo.`; `add_days` la data fra 24 giorni; `date_info` con `25/12/2026` stampa `ERRORE: Data "25/12/2026" non valida: formato atteso AAAA-MM-GG ...` con codice d'uscita 1. In PowerShell un argomento con spazi va tra virgolette. Gli argomenti si scrivono come `chiave=valore`; i numeri (`value=2.5`) vengono letti come numeri.

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

Quattro strumenti, tutti con date ISO (`AAAA-MM-GG`) e «oggi» calcolato nel fuso `DEFAULT_TIMEZONE`: `date_info` (giorno della settimana, festività, passata/oggi/futura), `find_holiday` (data di una festività nazionale; se quest'anno è già passata lo dice e dà la prossima), `add_days` (data fra N giorni, anche negativi) e `days_between` (giorni fra due date). Le festività a data fissa sono nel file `lab_server/holidays.json`; Pasqua e Lunedì dell'Angelo sono calcolati. Anni ammessi: 1900–2200. Ogni risultato termina con «Indicativo, non normativo.».

| Domanda | Atteso | Esito |
|---|---|---|
| `che giorno della settimana è pasqua?` | `find_holiday` Pasqua: avviso che Pasqua 2026 è passata e data della prossima (2027-03-28, domenica) | ok (2026-11-08, domande da pipe) |
| `che giorno sarà natale?` | `find_holiday` Natale: 2026-12-25, venerdì | ok (2026-11-08, domande da pipe) |
| `che giorno sarà tra 24 giorni?` | `add_days` 24 | ok (2026-11-08, domande da pipe): il modello ha chiesto prima l'ora a `get_current_time` e poi `add_days` con la data di oggi → 2026-12-02, mercoledì |
| `quanti giorni mancano a natale?` | `days_between` fino al 2026-12-25 | ok (2026-11-08, domande da pipe): 47 giorni |
| Le stesse domande a mano, in PowerShell e con Docker; memoria, `clear` e limite di passaggi | come sopra | da fare |

Con Docker Desktop su Windows il container ha raggiunto LM Studio con l'indirizzo `http://host.docker.internal:1234/v1` senza altre modifiche.

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
| Il modello risponde senza riga `[strumento]` nel log | il modello non ha chiamato lo strumento: la risposta non è verificata; riformulare la domanda |
| Il container non raggiunge LM Studio | controllare che il server sia attivo sull'host; se serve, attivare in LM Studio l'opzione per servire sulla rete locale e riprovare |
