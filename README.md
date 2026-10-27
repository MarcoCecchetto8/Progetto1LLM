# Assistente del laboratorio

Applicazione da terminale in Python che conversa con un modello locale servito da LM Studio. Il flusso è un grafo LangGraph esplicito (nodi `model`, `tools`, `step_limit`), la cronologia resta in memoria per la sola sessione e il modello può chiedere l'ora tramite lo strumento `get_current_time`, con fuso orario IANA esplicito.

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
| `DEFAULT_TIMEZONE` | no | `Europe/Rome` | nome IANA, validato all'avvio |
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
| `clear` | svuota la cronologia e conferma con `Cronologia svuotata.` |
| `quit`, `exit` | uscita con `Arrivederci!` |
| Ctrl+C, Ctrl+D (Linux/Docker), Ctrl+Z + Invio (Windows) | uscita con `Arrivederci!` |
| riga vuota | ignorata |

I comandi non distinguono maiuscole e minuscole.

## Log

I log vanno su stderr. Con `LOG_LEVEL=INFO` compare una riga per ogni chiamata allo strumento, per esempio:

```
[strumento] get_current_time(timezone=Europe/Rome) → Europe/Rome: 2026-10-27T16:06:36+01:00
```

e un avviso quando si raggiunge il limite di passaggi. Con `LOG_LEVEL=DEBUG` si vedono anche i nodi del grafo, l'instradamento, il contatore `steps/MAX_STEPS`, i messaggi rimossi dalla pulizia e i log HTTP delle librerie.

## Test

I test automatici non richiedono LM Studio: usano un modello finto e un istante fisso per l'orologio.

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest
```

Esito al 2026-10-27: 58 test superati.

## Prova reale

Va eseguita esplicitamente, con LM Studio acceso e il modello caricato. È l'unica prova che dimostra che il modello locale sa usare lo strumento. Esiti ottenuti il 2026-10-27 con `google/gemma-4-e2b`, in locale (`python -m assistant`) e con Docker (`docker compose run --rm -T app`), in entrambi i casi con le domande inviate da pipe. L'avvio interattivo con `docker compose run --rm app` (con terminale) non è ancora stato provato a mano.

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
| 6d. Ctrl+C durante l'attesa e al prompt | `Arrivederci!` senza traceback | da provare a mano in una console interattiva |

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
| Il container non raggiunge LM Studio | controllare che il server sia attivo sull'host; se serve, attivare in LM Studio l'opzione per servire sulla rete locale e riprovare |
