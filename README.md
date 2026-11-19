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

## Architettura: l'agente come servizio

L'agente (grafo, router, revisore, riassunto, strumenti MCP e note) non sta più dentro il programma da terminale: è un **servizio HTTP** FastAPI (`agent_service/`, porta 8001), e la CLI (`assistant/cli.py`) ne è un **client** (`assistant/agent_client.py`, con `httpx`).

```
terminale (assistant)  --HTTP/SSE-->  agente (agent_service)  --API OpenAI-->  LM Studio (host)
                                         |-- stdio --> server MCP (lab_server)
                                         '-- HTTP  --> servizio delle note (notes_service, porta 8000)
```

- L'agente **non ha stato**: a ogni richiesta il client manda cronologia e riassunto e li riceve aggiornati a turno completato. Il messaggio di sistema non viaggia mai: lo costruisce l'agente.
- Il turno si può chiedere in JSON (`POST /chat`) o in streaming SSE (`POST /chat/stream`); la CLI usa lo streaming e mostra le stesse cose di prima (ragionamento, strumenti, risposta, revisore).
- Il server MCP e il servizio delle note sono avviati dall'agente (in locale) o da Compose (`notes`); la CLI parla solo con l'agente.
- In locale la CLI avvia l'agente da sola (`AGENT_SERVICE_URL` vuota) e lo chiude all'uscita; con `AGENT_SERVICE_URL` valorizzata si collega a quell'indirizzo.

I comandi qui sotto sono stati eseguiti su Windows 11 con PowerShell, Python 3.14.2 e Docker Desktop (Docker 29.9.2), salvo dove indicato «da provare» o «da riprovare».

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
| `MAX_REVIEWS` | no | `3` | revisioni massime della risposta per domanda (≥ 0); con `0` il revisore giudica ma non rimanda mai indietro |
| `SUMMARY_THRESHOLD` | no | `4000` | token stimati (caratteri ÷ 4, riassunto compreso) oltre i quali la cronologia viene riassunta (≥ 1) |
| `SUMMARY_KEEP_TURNS` | no | `2` | ultimi turni lasciati intatti dal riassunto (≥ 1) |
| `SCOPE_FILE` | no | `config/ambito.txt` | file con l'ambito dell'assistente per il router (percorso relativo alla radice del progetto); se manca o è vuoto l'avvio si ferma con `SCOPE_FILE non valida: '<percorso>' non esiste o è vuoto.` |
| `PREFERENCES_FILE` | no | `config/preferenze.json` | file delle preferenze dell'utente, esposto dal server come resource `utente://preferenze` (percorso relativo alla radice del progetto); se manca o non è valido l'avvio prosegue con le riserve e un avviso `[preferenze]` |
| `AGENT_SERVICE_URL` | no | vuota | vuota in locale: l'assistente avvia da solo l'agente su `http://127.0.0.1:8001`; con Docker Compose viene impostata a `http://agent:8001` |
| `NOTES_SERVICE_URL` | no | vuota | vuota in locale: l'assistente avvia da solo il servizio delle note su `http://127.0.0.1:8000`; con Docker Compose viene impostata a `http://notes:8000` |

## Avvio locale (PowerShell)

Dalla cartella del progetto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m assistant
```

L'assistente avvia l'agente (porta 8001), che a sua volta avvia il server MCP e il servizio delle note; all'uscita li ferma tutti. Il servizio delle note risponde su http://127.0.0.1:8000 (la riga `[note] servizio: ...` si vede solo con `LOG_LEVEL=DEBUG`: vedi «Log»). Finché l'assistente è in esecuzione, la documentazione interattiva è su http://127.0.0.1:8000/docs. Le note stanno in `data/notes.db`, escluso da Git.

## Avvio con Docker

LM Studio resta sull'host: il container lo raggiunge tramite `host.docker.internal`.

```powershell
docker compose build
docker compose run --rm app
```

Si usa `run` e non `up`, perché `up` non collega il terminale all'input dell'applicazione.

Compose avvia anche due container di servizio: `notes`, con il servizio delle note, e `agent`, con l'agente (`depends_on` avvia i container in ordine, ma non aspetta che l'agente sia pronto: è la CLI a restare in attesa, fino a 60 secondi, che `agent` risponda su `/stato`; `agent` a sua volta aspetta `notes`). Le porte 8000 e 8001 sono pubblicate solo su `127.0.0.1` dell'host, non raggiungibili dalla rete. Il container `app` è solo la CLI e parla con `http://agent:8001`; LM Studio, preferenze e servizio note servono all'agente. Le note stanno nella cartella `data/` del progetto, montata nel container: sono le stesse dell'avvio locale. Per fermare il servizio dopo l'uso:

```powershell
docker compose down
```

Non usare insieme l'assistente locale e quello Docker: vogliono le stesse porte (8000 e 8001).

I log dell'agente (traccia dei turni, strumenti, revisore) si leggono con `docker compose logs agent`. Se l'agente perde il collegamento con il server MCP o con le note non si riconnette da solo: `docker compose restart agent`.

## Comandi

| Input | Effetto |
|---|---|
| `help` | elenca comandi e modi di uscita |
| `clear` | svuota la cronologia, pulisce lo schermo (solo se l'output è un terminale), ristampa l'intestazione e conferma con `Cronologia svuotata.` |
| `/prompts` | elenca i prompt del server MCP, con gli argomenti (vedi «Prompt MCP») |
| `/prompt <nome> argomento=valore …` | richiama un prompt del server e lo manda al modello come domanda (vedi «Prompt MCP») |
| `quit`, `exit` | uscita con `Arrivederci!` |
| Ctrl+C al prompt, Ctrl+D (Linux/Docker), Ctrl+Z + Invio (Windows) | uscita con `Arrivederci!` |
| Ctrl+C mentre il modello lavora | ferma solo il turno: compare `Risposta interrotta.` e si torna al prompt (entro circa mezzo secondo: l'agente invia un commento SSE di keepalive nei momenti di silenzio, altrimenti su Windows la lettura bloccata non vedrebbe il Ctrl+C) |
| Ctrl+C alla domanda `[s/N]` di un'eliminazione | esce senza eliminare nulla |
| riga vuota | ignorata |

I comandi non distinguono maiuscole e minuscole.

Un turno interrotto con Ctrl+C non entra nella cronologia. Uno strumento già eseguito non viene annullato: una nota già salvata resta salvata. Il Ctrl+C ferma il modello al pezzo successivo della risposta; uno strumento già in esecuzione (chiamata MCP o HTTP al servizio delle note) viene invece atteso fino alla fine, poi compare `Risposta interrotta.`. Il servizio delle note e il server degli strumenti restano attivi dopo l'interruzione. Su Windows il Ctrl+C ferma il turno subito anche durante router, revisore e strumenti, quando non arriva ancora testo: l'agente manda un evento vuoto (keepalive) ogni mezzo secondo (verificato il 2026-11-18).

## L'agente da solo (HTTP)

Senza la CLI, per provarlo a mano o per usarlo da altri programmi. Dal venv attivo, in un terminale:

```powershell
python -m agent_service
```

Parte su `http://127.0.0.1:8001` (opzioni `--host`, `--port`, `--quiet`) e avvia da solo server MCP e servizio delle note. Parte anche con LM Studio spento; non parte senza server MCP o servizio delle note (messaggio su stderr, codice d'uscita 1). Si ferma con Ctrl+C. Le variabili del `.env` valgono come per l'assistente (`SHOW_REASONING` è solo della CLI: l'agente invia sempre il ragionamento).

| Metodo e percorso | Che cosa fa |
|---|---|
| `POST /chat` | un turno, risposta unica in JSON |
| `POST /chat/stream` | lo stesso turno in streaming SSE |
| `GET /stato` | stato di agente, modello, server MCP e servizio note; 200 se tutto risponde, 503 altrimenti (stesso corpo) |
| `GET /prompts`, `POST /prompts/{nome}` | elenco dei prompt MCP e testo compilato (corpo `{"argomenti": {...}}`) |
| `GET /docs`, `GET /openapi.json` | documentazione interattiva e schema |

La documentazione interattiva con tutti i campi è su http://127.0.0.1:8001/docs.

**Una domanda da PowerShell** (con l'agente acceso e un modello che risponde):

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/chat -ContentType 'application/json; charset=utf-8' -Body '{"messaggi":[{"ruolo":"utente","contenuto":"Che ore sono?"}]}'
```

La richiesta ha `messaggi` (nuovi, ruoli `utente` o `assistente`), `cronologia` e `riassunto` (facoltativi). La risposta ha `esito` (`completato` o `conferma_richiesta`), `risposta`, `strumenti`, `righe`, `cronologia` e `riassunto`: per proseguire la conversazione si rimandano `cronologia` e `riassunto` ricevuti. I ruoli dei messaggi sono `utente`, `assistente` e `strumento`.

**Stato:**

```powershell
Invoke-RestMethod http://127.0.0.1:8001/stato
```

Con tutto raggiungibile (verificato il 2026-11-18, in locale e in Docker) risponde 200 con `agente: ok` e, per `modello`, `strumenti` e `note`, `raggiungibile: true` con un messaggio. Con LM Studio non raggiungibile risponde 503 con lo stesso corpo e `raggiungibile: false` per il modello (verificato il 2026-11-18 con un indirizzo chiuso in `LMSTUDIO_BASE_URL`; `Invoke-RestMethod` lo segnala come errore).

**Eventi dello streaming (`/chat/stream`):** ogni evento è `event: <nome>` e `data: <json>`. Nomi: `ragionamento`, `risposta` (dati `{testo}`), `strumento` (`{nome, argomenti}`), `esito_strumento` (`{nome, contenuto, errore}`), `riga` (`{testo}`: revisore, riassunto, rifiuto), `fine` (la risposta completa, come `/chat`) ed `errore` (`{codice, messaggio}`).

**Conferma prima di eliminare una nota (due chiamate).** L'agente non ha un terminale: quando il modello chiede `delete_note` non esegue nulla e risponde `esito: conferma_richiesta` con `conferme` (per ogni nota l'`id_nota` e la `domanda` già pronta) e `sospeso` (stato opaco). Il client chiede all'utente e rimanda lo stato con le decisioni (`true` elimina), omettendo `messaggi` e `cronologia`:

```powershell
$r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/chat -ContentType 'application/json; charset=utf-8' -Body '{"messaggi":[{"ruolo":"utente","contenuto":"Elimina la nota 1"}]}'
$r.conferme
$ripresa = @{ ripresa = @{ sospeso = $r.sospeso; decisioni = @{ "1" = $true } } } | ConvertTo-Json -Depth 20
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/chat -ContentType 'application/json; charset=utf-8' -Body $ripresa
```

Entrambi gli esempi sono stati eseguiti il 2026-11-18 con Windows PowerShell 5.1 e `google/gemma-4-e2b` (con l'ID di una nota di prova al posto di `1`). Le risposte JSON dichiarano `charset=utf-8`: senza, PowerShell 5.1 mostrerebbe gli accenti illeggibili.

**Errori.** Prima dello streaming e per `/chat` sono un codice HTTP con corpo `{"codice": ..., "messaggio": ...}`; durante lo streaming arrivano come evento `errore` con gli stessi codici.

| HTTP | `codice` | Quando |
|---|---|---|
| 503 | `modello_non_raggiungibile` | LM Studio spento o su un altro indirizzo |
| 504 | `modello_timeout` | il modello non risponde entro `LMSTUDIO_TIMEOUT` |
| 422 | `contesto_pieno` | cronologia troppo lunga per il modello |
| 502 | `errore_modello` | altro errore dell'API del modello |
| 503 | `strumenti_non_raggiungibili` | il server MCP non risponde |
| 503 | `note_non_raggiungibili` | il servizio delle note non risponde |
| 502 | `risposta_vuota` | il modello non ha dato una risposta |
| 422 | `prompt_rifiutato` | il server MCP ha respinto gli argomenti di un prompt |
| 422 | (quello di FastAPI) | richiesta non valida (schema, cronologia o `ripresa` incoerenti) |
| 500 | `errore_imprevisto` | errore non previsto (traceback nei log dell'agente) |

**Limiti.**

- Un turno alla volta: l'agente serializza i turni con un lock; una seconda richiesta aspetta la fine della prima.
- Nessuna riconnessione automatica: se il server MCP o il servizio delle note si fermano, il turno dà `strumenti_non_raggiungibili` o `note_non_raggiungibili` e `/stato` risponde 503. Si riavvia l'agente: in locale basta uscire dall'assistente e riavviarlo, con Docker `docker compose restart agent`.
- Nessuna autenticazione: le porte sono pubblicate solo su `127.0.0.1`.

## Che cosa si vede durante un turno

La risposta arriva in streaming, mentre il modello la scrive:

- il **ragionamento** del modello, attenuato (grigio), sotto l'intestazione `[ragionamento]`, nella lingua in cui il modello lo scrive;
- ogni **strumento** richiesto, su una riga propria con nome e argomenti (`[strumento] <nome> <argomenti>`), poi l'esito (`[strumento] <nome> → <risultato>`, oppure `[strumento] <nome> errore → <risultato>`);
- la **risposta**, token per token; senza colori (pipe, file, `-T`), se prima c'è il ragionamento, la risposta comincia sotto l'intestazione `[risposta]`, su una riga propria;
- dopo ogni risposta, la riga del **revisore** (`[revisore] coerente`, oppure `[revisore] non coerente: <motivo> → nuova risposta` seguita dalla nuova risposta);
- l'eventuale avviso del controllo dei falsi successi, in fondo, dopo la risposta.

Con `SHOW_REASONING=false` il ragionamento non compare e resta solo la riga «…sto pensando» fino al primo strumento o al primo token della risposta. Se il modello non invia il ragionamento, non c'è nulla da mostrare. Il ragionamento non entra nella cronologia. I colori compaiono solo se l'uscita è un terminale: con pipe, file o `docker compose run -T` il contenuto è lo stesso, senza sequenze di colore.

## Router dell'ambito

Prima dell'agente, un router decide se la domanda rientra nell'ambito dell'assistente: strumenti del laboratorio, linguaggi di programmazione, informatica, intelligenza artificiale, saluti e domande sull'assistente stesso. Usa lo stesso modello di LM Studio, con il ragionamento spento e un output strutturato (categoria e motivo); riceve la domanda e gli ultimi messaggi di testo della conversazione, così un seguito come «e a Tokyo?» resta in ambito.

- **In ambito**: la domanda passa all'agente come sempre.
- **Fuori ambito**: nessuna chiamata al modello dell'agente e nessuno strumento; la risposta è un messaggio fisso con il motivo: `Posso aiutarti solo con gli strumenti del laboratorio, i linguaggi di programmazione, l'informatica e l'intelligenza artificiale. Motivo: <motivo>`. Domanda e rifiuto entrano nella cronologia.
- **Errore del router** (risposta non valida): la domanda passa all'agente e nel log compare un avviso.
- **Dove si modifica l'ambito**: `config/ambito.txt` (descrizione ed esempi con la categoria attesa); un altro file si indica con `SCOPE_FILE`. La modifica vale dalla sessione successiva, senza toccare il codice. Con Docker il file è copiato nell'immagine: dopo una modifica serve `docker compose build`.
- **Log** (scritto dall'agente: vedi «Log»): a ogni decisione una riga `[router] categoria=<categoria> motivo=<motivo> → agente` oppure `→ rifiuto`; all'avvio `[router] ambito: <percorso> (<n> righe)`.
- **Limite, il tempo**: il router è una chiamata in più al modello per ogni domanda: circa 23 s per decisione, misurati su questo computer.
- **Limite, la precisione**: nelle sonde con 9 domande il router ha classificato bene 6 su 9 con la sola descrizione dell'ambito e 9 su 9 con gli esempi di `config/ambito.txt`. Nella prova reale ha classificato bene 12 domande su 12; il modello può comunque sbagliare.

## Revisore della risposta

Dopo la risposta finale dell'agente, un revisore controlla che risponda a **tutte** le parti della domanda e che resti in tema. Usa lo stesso modello di LM Studio, con il ragionamento spento e un output strutturato (`coerente` sì/no e `motivo`). Riceve solo la domanda e la risposta, non i risultati degli strumenti: controlla la coerenza, non la correttezza dei dati.

- **Coerente**: la risposta resta e il turno finisce (`[revisore] coerente`).
- **Non coerente**: il motivo torna all'agente come indicazione e l'agente risponde di nuovo (`[revisore] non coerente: <motivo> → nuova risposta`), con un nuovo budget di `MAX_STEPS` passaggi.
- **Limite**: al massimo `MAX_REVIEWS` revisioni (predefinito 3); al limite resta l'ultima risposta (`[revisore] limite raggiunto (<n> revisioni): resta l'ultima risposta`).
- **Verdetto non valido**: la risposta è approvata (`[revisore] verdetto non valido: risposta approvata`) e nel log compare un avviso.
- **Quando non interviene**: rifiuto del router, messaggio di limite di passaggi, risposta vuota.
- **Cronologia**: a fine turno restano la domanda, le chiamate agli strumenti con i loro risultati e la risposta finale; bozze bocciate e indicazioni del revisore vengono tolte. L'avviso dei falsi successi si applica alla risposta finale, dopo il revisore.
- **Scelta di streaming (slide 18 della lezione 6)**: si mostrano anche le bozze mentre vengono scritte, con il verdetto del revisore subito sotto. Lo scopo è osservare l'agente al lavoro, compresa la correzione; nascondere le bozze lascerebbe lo schermo fermo per tutta la revisione (decine di secondi con questo modello).
- **Log** (scritto dall'agente: vedi «Log»): all'avvio `[revisore] limite: <n> revisioni`; con `LOG_LEVEL=DEBUG` anche `[revisore] coerente=<sì|no> motivo=<motivo> revisione <n>/<max>` a ogni giudizio (a livello normale il verdetto si vede già nel terminale).
- **Limite, il tempo**: ogni giudizio è una chiamata in più al modello, circa 23 s su questo computer; ogni bocciatura aggiunge anche una nuova risposta dell'agente.
- **Limiti osservati nelle sonde**: giudizi corretti 6 su 6; dopo l'indicazione l'agente ha completato la risposta 3 volte su 3, ma calcolando a mente invece di usare `calculate` (il revisore non controlla come è stato ottenuto il dato).

## Riassunto della cronologia

All'inizio di ogni turno, prima del router, un nodo controlla la dimensione della conversazione. Se supera la soglia, un riassunto sostituisce i messaggi più vecchi. Usa lo stesso modello di LM Studio, con il ragionamento spento e un'uscita testuale semplice. Serve a mantenere la conversazione utilizzabile su molti turni con il contesto limitato del modello locale (su questo computer 8192 token), senza il messaggio «Il contesto del modello è pieno».

- **Quando scatta**: quando la stima dei token supera `SUMMARY_THRESHOLD` (predefinito 4000). La stima è la somma dei caratteri dei messaggi, prompt di sistema compreso, più il riassunto in vigore, divisa per 4; gli schemi degli strumenti (circa 1365 token) non sono inclusi e sono coperti dal margine della soglia. Sotto la soglia, o se i turni precedenti sono al massimo `SUMMARY_KEEP_TURNS`, il nodo non chiama il modello.
- **Che cosa conserva**: il prompt di sistema, gli ultimi `SUMMARY_KEEP_TURNS` turni completi (predefinito 2) e la domanda del turno corrente. Il taglio cade sempre all'inizio di un turno, quindi una chiamata a uno strumento e il suo risultato non vengono mai separati.
- **Che cosa chiede al modello**: un riassunto in italiano di al massimo 120 parole che conservi nome dell'utente, fuso orario o città, ID e testo delle note, argomenti principali. L'utente va chiamato «l'utente» e, se nome o città sono noti, il riassunto inizia con «L'utente si chiama … e vive a …»: con «Marco, residente a Roma, …» l'agente non collegava il nome a chi gli parlava.
- **Dove finisce il riassunto**: in un campo dello stato, sostituito a ogni nuovo riassunto e non accumulato. A ogni chiamata l'agente lo riceve in fondo al primo messaggio di sistema, con l'intestazione «Riassunto della conversazione precedente (fa parte di questa conversazione: usalo per rispondere alle domande sull'utente, come nome e città, e su ciò di cui si è parlato):»; non viene salvato nella cronologia. Con l'intestazione breve, dopo turni con strumenti, l'agente rispondeva «Non mi hai detto il tuo nome» (1 risposta giusta su 6 nella sonda; con quella esplicita 6 su 6).
- **Router e revisore**: anche il router riceve il riassunto, in fondo al suo prompt di sistema, con l'intestazione breve «Riassunto della conversazione precedente:». Il revisore riceve, prima della domanda e della risposta, il riassunto, gli ultimi messaggi di testo della conversazione (la stessa regola del router: niente strumenti, al massimo 6) e i risultati degli strumenti del turno. Senza il contesto bocciava «di cosa abbiamo parlato?» («non c'è stato un argomento precedente»); con il contesto ma senza i risultati degli strumenti bocciava le note elencate da `list_notes` e l'ora di Tokyo. Con tutti e tre: 15 giudizi giusti su 15 nella sonda.
- **Nel terminale**: prima del router compaiono una riga `[riassunto] <n> → <m> messaggi (circa <t1> → <t2> token)` e il testo del riassunto, mostrati una sola volta.
- **`clear`**: svuota anche il riassunto.
- **Errore**: se il riassunto non riesce (errore di LM Studio o testo vuoto) cronologia e riassunto restano come prima, nel log compare un avviso `[riassunto] non riuscito (...): cronologia invariata` e il turno prosegue.
- **Log** (scritto dall'agente: vedi «Log»): all'avvio `[riassunto] soglia: <n> token stimati, turni conservati: <k>`; con `LOG_LEVEL=DEBUG` anche la riga dei conteggi.
- **Limite, il tempo**: il riassunto è una chiamata in più al modello, 7–19 s nelle prove reali. Se dopo il riassunto la conversazione resta sopra la soglia (soglia bassa, riassunto lungo), il riassunto riparte a ogni turno.
- **Limite, «dove vivo?»**: il router rifiuta «dove vivo?» come fuori ambito («non posso sapere dove vivi») quando la presentazione dell'utente non è più fra gli ultimi messaggi, anche con il riassunto e con un esempio in `config/ambito.txt` (0 su 3 nelle sonde). Funzionano «come mi chiamo?», «come mi chiamo e dove vivo?» e «di cosa abbiamo parlato?». È un limite del modello.
- **Limite accettato, la memoria dei riassunti successivi**: con `google/gemma-4-e2b` nome, città e ID delle note sopravvivono ai riassunti successivi, ma gli argomenti più vecchi tendono a sparire al secondo riassunto. È un limite del modello.

## Preferenze dell'utente

Lingua delle risposte, fuso orario predefinito e stile non sono scritti nel codice: stanno in un file, che il server MCP espone come **resource** `utente://preferenze`. A leggerla è l'host (`assistant/`), non il modello: una volta sola all'avvio della sessione, prima della prima domanda; poi il blocco delle preferenze va in cima al prompt di sistema. Nel blocco in cima stanno lingua e stile; il fuso orario va nella frase delle istruzioni ed è il predefinito del server. Messo anche nel blocco, il modello saltava `get_current_time` per «Che ore sono?»: 3/6 con la riga del fuso, 6/6 senza (sonda con il grafo reale, 6 temperature). Un tool lo decide il modello durante la conversazione, una resource la decide l'host prima di chiamare il modello.

- **Il file**: `config/preferenze.json`, versionato; un altro file si indica con `PREFERENCES_FILE`. Contenuto di partenza: `{"lingua": "italiano", "fuso_orario": "Europe/Rome", "stile": "sintetico"}`. La modifica vale dalla sessione successiva, senza toccare il codice (`clear` non rilegge il file).
- **Campi e valori**: `lingua` (`italiano`, `inglese`, `spagnolo`); `fuso_orario` (nome IANA esatto, maiuscole comprese, come `DEFAULT_TIMEZONE`); `stile` (`sintetico`: una o due frasi, solo ciò che è chiesto; `dettagliato`: la risposta più il contesto utile preso dai risultati degli strumenti). I valori si confrontano esattamente come scritti; i campi in più sono ignorati.
- **Riserve e avvisi**: un campo assente o con valore non ammesso usa la riserva di quel campo (`italiano`, `sintetico`, `DEFAULT_TIMEZONE`) e un avviso `WARNING` `[preferenze] ...` lo nomina; gli altri campi validi restano. Resource non disponibile o contenuto non valido: tutte le riserve e un avviso. L'avvio non si ferma mai per le preferenze.
- **Fuso orario**: il fuso delle preferenze, se valido, è anche quello predefinito del server (`get_current_time` senza `timezone`, «oggi» degli strumenti delle date) e delle note, così host e server non sono in disaccordo.
- **La resource non è tra i tool**: i tool passati al modello restano quelli del catalogo più le note. `python -m lab_server.check` elenca la resource dopo i tool.
- **Log** (scritto dall'agente: vedi «Log»): all'avvio una riga `INFO` `[preferenze] utente://preferenze: lingua=<...>, fuso_orario=<...>, stile=<...>`, distinta dalle chiamate ai tool.
- **Docker**: `compose.yaml` monta `config/preferenze.json` in sola lettura in `/app/config/preferenze.json`: una modifica vale dalla sessione successiva senza `docker compose build`. Il file deve esistere sull'host: con la sintassi breve del bind mount, se manca Docker crea una cartella vuota `config/preferenze.json`. Con un `PREFERENCES_FILE` diverso in Docker si usa la copia dentro l'immagine, perché si monta solo `config/preferenze.json`.
- **Limiti**: i testi fissi del programma (rifiuto del router, avvisi, messaggi del terminale, prompt di router, revisore e riassunto) restano in italiano; risponde nella lingua scelta solo il modello. L'avviso sui falsi successi delle note è solo in italiano: con `inglese` o `spagnolo` una nota dichiarata salvata o eliminata senza lo strumento non produce l'avviso.
- **Limite osservato, la lingua**: con `inglese` le risposte costruite sui risultati del catalogo, che sono in italiano, escono a volte in italiano (2 sessioni su 4 per «chi ha creato Python?»). È un limite del modello.

## Prompt MCP

Oltre a tool e resource, il server MCP espone due **prompt**: modelli di richiesta con argomenti. Li sceglie l'utente (non il modello) con i comandi `/prompts` e `/prompt`. L'elenco si legge una volta all'avvio, dopo il catalogo e le preferenze, con la riga `INFO` `[mcp] prompt: spiega, riassumi_conversazione` (nel log dell'agente: vedi «Log»).

| Prompt | Argomenti | Valori |
|---|---|---|
| `spiega` | `argomento` (obbligatorio): il concetto da spiegare; `livello` (facoltativo) | `livello`: `base` (predefinito), `intermedio`, `avanzato`; `argomento` non vuoto |
| `riassumi_conversazione` | `stile` (facoltativo) | `sintetico` (predefinito), `dettagliato` |

```
> /prompts
> /prompt spiega argomento="Model Context Protocol" livello=base
> /prompt riassumi_conversazione stile=dettagliato
```

- **Virgolette**: solo le virgolette doppie raggruppano; `argomento="Model Context Protocol"` è un solo valore. Il valore non cambia maiuscole e minuscole; il nome del comando e `/prompts` sì (`/PROMPTS` funziona), il nome del prompt no (`Spiega` non è `spiega`).
- **Che cosa succede**: il testo del prompt prende il posto della domanda: il turno è identico a una domanda scritta a mano (router, strumenti, revisore, riassunto, Ctrl+C) e il messaggio resta nella cronologia. Per `spiega`, il router rifiuta gli argomenti fuori ambito (per esempio «tiramisù», verificato nella prova reale).
- **Controlli prima del modello**: nome mancante, virgolette non chiuse, prompt sconosciuto, elemento senza `=`, argomento ripetuto, argomento sconosciuto, argomento obbligatorio mancante. In tutti i casi compare un messaggio e non partono né il modello né la richiesta al server. Un valore non ammesso (`livello=esperto`) o un `argomento` vuoto lo rifiuta il server: `Il server ha rifiutato il prompt: <motivo>`, senza chiamare il modello.
- **Comando sconosciuto**: un testo che inizia con `/` e non è `/prompts` né `/prompt` (per esempio `/promt`) dà `Comando sconosciuto: /promt. Comandi: help, clear, /prompts, /prompt.` e non va al modello.
- **Server caduto**: `Il server degli strumenti non risponde: esci e riavvia l'assistente.`, come durante un turno.
- **Log** (scritto dall'agente: vedi «Log»): prima del turno una riga `INFO` `[prompt] <nome> <argomenti in JSON> → <testo del primo messaggio>`; con più messaggi, uno per ciascuno a `DEBUG`. Con `LOG_LEVEL=DEBUG` la richiesta `prompts/get` (`GetPromptRequest`) compare nei log MCP, distinta da `tools/call` e `resources/read` (verificato nella prova reale).

## Log

I log vanno su stderr e li scrive l'agente (insieme a server MCP e servizio delle note), non la CLI. Dove si vedono dipende da come si avvia:

| Avvio | Che cosa compare |
|---|---|
| `python -m assistant`, `LOG_LEVEL` normale | l'agente parte in silenzio (`--quiet`): la CLI ristampa solo gli avvisi di avvio (`[preferenze] ...`, `[modello] ...`) e, durante la sessione, gli errori che arrivano come messaggi; le righe `INFO` (`[note]`, `[mcp]`, `[router]`, `[api]`, `[strumento]`...) non compaiono |
| `python -m assistant` con `LOG_LEVEL=DEBUG` | l'agente non è silenzioso: tutti i suoi log compaiono nel terminale della CLI, con data e livello |
| `python -m agent_service` a parte (poi `AGENT_SERVICE_URL=http://127.0.0.1:8001 python -m assistant` in un altro terminale) | i log dell'agente compaiono nel suo terminale, al livello di `LOG_LEVEL` |
| Docker | `docker compose logs agent` (e `docker compose logs -f agent` per seguirli) |

Con l'agente che scrive i log (casi `DEBUG`, a parte o Docker), all'avvio compare il catalogo letto dal server MCP; con `LOG_LEVEL=INFO` compare poi una riga per ogni chiamata a uno strumento, con l'id della chiamata del modello, gli argomenti e l'esito (`ok` o `errore`), per esempio:

```
[mcp] catalogo: get_current_time
[strumento] get_current_time call_id=1polVGvPjXs42xILRLFmbMpl47V0LucQ argomenti={"timezone": "Asia/Tokyo"} esito=ok → Asia/Tokyo: 2026-11-09T02:09:34+09:00
```

Compaiono anche un avviso quando si raggiunge il limite di passaggi e, se il server MCP si ferma durante la sessione, la riga `[mcp] collegamento con il server perso: ...`, distinta dagli errori degli strumenti (`esito=errore`). Le righe `[strumento] ... call_id=... esito=...` sono a livello `DEBUG`: si vedono con `LOG_LEVEL=DEBUG` (con la CLI che avvia l'agente) oppure con l'agente a parte (durante il turno gli strumenti si vedono già nel flusso descritto sopra). Con `LOG_LEVEL=DEBUG` si vedono anche i nodi del grafo, l'instradamento, il contatore `steps/MAX_STEPS`, i messaggi rimossi dalla pulizia, i log HTTP delle librerie e i log del server MCP, che altrimenti non scrive nulla sul terminale.

## Test

I test automatici non richiedono LM Studio: usano un modello finto e un istante fisso per l'orologio.

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest
```

Esito al 2026-11-18: 641 test superati. Alcuni test avviano davvero un server MCP di prova in stdio (`tests/mcp_test_server.py`): ogni avvio richiede alcuni secondi.

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

**Regole del controllo (note).** L'avviso ⚠ compare in due casi, sempre solo se lo strumento corrispondente (`add_note`, `delete_note`) non ha dato un risultato senza errore dopo l'ultima domanda (una eliminazione annullata vale come conferma):

1. *Dichiarazione*: la risposta dice di aver salvato o eliminato («Ho salvato…», «La nota è stata salvata», anche la frase breve «Nota salvata.» a inizio frase; non gli aggettivi di `list_notes`, come «Nessuna nota salvata.»).
2. *Richiesta esplicita*: la domanda dell'utente (l'ultima vera, non le indicazioni del revisore) chiede di salvare a inizio domanda («Salva/Annota/Segna/Scrivi/Aggiungi/Crea una nota o un promemoria» seguito da «:», «per», «che», «su» o dalla fine; «Annota che…», «Segnati che…»; «Ricordami di…»; «Nota: …»), con «per favore», «ok» o «ehi» facoltativi davanti, oppure di eliminare con il numero («Elimina la nota 3», «Cancella le note 4 e 5», «Rimuovi il promemoria 3») a inizio domanda o dopo «e», «ed», «poi», virgola. Se la domanda termina con «?» non è mai una richiesta.

Le forme sono volutamente strette, perché se l'utente parla d'altro («Ricordami di cosa parlava la nota 3», «Crea una nota musicale in Python», «Annota che cos'è un type hint») l'avviso non deve mai comparire. Non contano: «Ricordami di» seguito da cosa/che/come/quando/perché/chi/quale/quanto/dove/se; «Annota che» seguito da cos/cosa/ore; «Scrivi che» e «Segna che»; i plurali per il salvataggio («Aggiungi note…»).

Eccezione: se la risposta termina con «?» (domanda di chiarimento, per esempio «Che testo vuoi salvare?») l'avviso legato alla richiesta non compare; la dichiarazione falsa avvisa comunque. Limiti: le forme di richiesta non previste passano senza avviso; l'eliminazione senza numero («Elimina la nota di ieri») e i plurali non avvisano; «Ricordami di…» con un chiarimento non avvisa.

**Misura del 2026-11-18** con `liquid/lfm2-24b-a2b` su 21 domande vere: richieste riconosciute 11/11, avvisi sulle domande d'altro 0/10. Risposte senza strumento: «Nota: comprare le uova» → dichiarazione falsa, con avviso; «Ricordami di innaffiare…» e «Segnati che venerdì…» → chiarimento, senza avviso.

Prova reale degli avvisi (da provare):

| Prova | Atteso | Esito |
|---|---|---|
| Una richiesta di salvataggio («Salva una nota: …») | nota salvata, nessun avviso | da provare |
| «Nota salvata.» senza strumento, se ricapita | avviso ⚠ | da provare |
| Una domanda d'altro con «ricordami» («Ricordami come mi chiamo») | nessun avviso | da provare |

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

Esiti del 2026-11-16 con `google/gemma-4-e2b`, domande inviate da pipe in una sola sessione (con `LOG_LEVEL=DEBUG` per vedere i passaggi del nodo agente).

| Prova | Atteso | Esito |
|---|---|---|
| Le 9 domande della sonda | ok, 9 su 9 (Roma, «e a Tokyo?», saluto, rete neurale, latte, «Quali strumenti hai?» in ambito; carbonara, mondiale 2006, Parigi rifiutate). Tempo del router fra circa 8 e 26 s per decisione |
| Almeno 3 domande nuove, non presenti fra gli esempi di `config/ambito.txt` | ok, 3 su 3: «Converti 10 miglia in chilometri» e «Che differenza c'è tra Python e Java?» in ambito, «Qual è il fiume più lungo d'Italia?» rifiutata |
| Domanda in ambito | ok |
| Domanda fuori ambito | ok: dopo `→ rifiuto` nessuna riga `[grafo] nodo model`. Il motivo dei rifiuti è spesso generico («La richiesta è fuori dall'ambito delle mie capacità di assistenza.») |
| Modifica di `config/ambito.txt` (per esempio togliere «note») e nuova sessione | ok: con `SCOPE_FILE` che punta a una copia senza le righe sulle note, «Ricordami di comprare il latte» viene rifiutata |
| Docker (`docker compose run --rm -T app` con input da pipe) | ok: carbonara rifiutata, «Che ore sono a Tokyo?» passa all'agente e usa `get_current_time` |

### Prova reale del revisore

Esiti del 2026-11-16 con `google/gemma-4-e2b`, domande inviate da pipe.

| Prova | Atteso | Esito |
|---|---|---|
| `Che ore sono a Tokyo e quanto fa il 15% di 80?` | se la prima risposta è parziale: rifiuto motivato e nuova risposta completa; se è completa: approvata (si ripete con un'altra domanda in due parti) | completa al primo colpo (`get_current_time` e `calculate`), approvata. Con «Converti 5 chilometri in miglia e dimmi chi ha creato Python» la prima risposta dava solo l'anno di Python: **bocciata con motivo** («la risposta sulla creazione di Python è incompleta») e rifatta due volte; la terza è stata approvata ma diceva ancora solo «creato nel 1991», senza l'autore (giudizio sbagliato del revisore; l'agente non ha chiamato `get_item`). In una sonda controllata la correzione dopo l'indicazione era riuscita 3 volte su 3 |
| Altre tre domande in due parti (Rust e 37 per 19; 25 dicembre 2026 e creatore del C; anno di Java e 10 km in metri) | se una parte manca: rifiuto motivato | tutte approvate al primo giudizio, nessuna bocciatura. Il revisore non controlla la correttezza: ha approvato `37 / 19` al posto di `37 * 19` e un autore di Rust scritto a memoria senza `get_item`. Per il C la prima bozza dava solo l'anno, ma conteneva anche la chiamata a `get_item`: è un passaggio intermedio, quindi il revisore non interviene, e il modello ha completato da solo («Dennis Ritchie») |
| Una domanda semplice | approvata al primo passaggio | ok: «ciao, chi sei?», «Cos'è una rete neurale?» e la domanda in tre parti su Haskell, 2^10 e il 1/1/2000 approvate al primo passaggio |
| Tempi del revisore e revisioni usate | registrati | circa 20–30 s per giudizio. Prima della correzione del prompt, una conversione spiegata come impossibile (miglia non supportate) veniva bocciata 3 volte fino al limite; con la regola «una parte spiegata come impossibile ha una risposta» la sonda dà 8 giudizi corretti su 8. Una domanda in tre parti (Natale, New York, Java) è finita in timeout del modello (120 s) dopo gli strumenti |
| Docker (`docker compose run --rm -T app` con input da pipe) | stesso comportamento del locale | ok: «Cos'è un compilatore?» approvata, righe del router e del revisore come in locale |

### Prova reale del riassunto

Esiti del 2026-11-16 e 2026-11-17 con `google/gemma-4-e2b`, domande inviate da pipe in una sola sessione, con `SUMMARY_THRESHOLD=900` (variabile d'ambiente) e `LOG_LEVEL=DEBUG` per i tempi. Domande: «ciao, mi chiamo Marco e vivo a Roma», «chi ha creato Python?», «quanto fa 12 * 7?», «quanti metri sono 3 km?», «chi ha creato Rust?», «come mi chiamo?», «quali note ho?», «di cosa abbiamo parlato?», «che ore sono a Tokyo?».

| Prova | Atteso | Esito |
|---|---|---|
| «ciao, mi chiamo Marco» al primo turno, poi alcune domande con strumenti e una nota; dopo il riassunto «come mi chiamo?» | riga e testo del riassunto visibili; la risposta contiene il nome | ok in locale: righe `[riassunto]` e testo visibili, il riassunto inizia con «L'utente si chiama Marco e vive a Roma», risposta «Mi hai detto che ti chiami Marco.» quando la presentazione era già stata riassunta. Prima delle correzioni del 2026-11-17 il router rifiutava «come mi chiamo e dove vivo?» e l'agente rispondeva «Non mi hai detto il tuo nome» |
| Sessione sotto la soglia | nessuna riga `[riassunto]` (il nodo non chiama il modello) | ok: con `SUMMARY_THRESHOLD=1500` la stessa sessione non ha prodotto nessun riassunto |
| Tempo del riassunto | registrato | 7–19 s per riassunto (5 riassunti nell'ultima sessione: 8, 10, 12, 18, 19 s) |
| Secondo riassunto nella stessa sessione | registrare che cosa resta | nome, città e argomenti restano in tutti i riassunti dell'ultima sessione (Python, 12 × 7, 3 km, Rust); in sessioni precedenti un terzo riassunto aveva perso gli argomenti più vecchi (limite accettato). Il riassunto ha chiamato «nota ID PY» la scheda del catalogo di Python. Con soglia 900 la conversazione resta sopra la soglia e il riassunto riparte a ogni turno |
| Domande sulla conversazione | «di cosa abbiamo parlato?» e «quali linguaggi abbiamo visto finora?» in ambito e approvate | ok: router «domanda sulla conversazione», revisore approva al primo giudizio; la risposta elenca Python e Rust |
| Revisore con strumenti | «quali note ho?» e «che ore sono a Tokyo?» approvate | ok in locale e in Docker dopo la correzione del 2026-11-17 (prima: note bocciate 3 volte fino al limite) |
| Docker (`docker compose run --rm -T -e SUMMARY_THRESHOLD=900 app` con input da pipe) | stesso comportamento del locale | ok (2026-11-17, dopo l'intestazione esplicita): due riassunti, entrambi iniziano con «L'utente si chiama Marco e vive a Roma»; «come mi chiamo?» → «Ti chiami Marco.»; «quali note ho?» con `list_notes` approvata al primo giudizio. Con l'intestazione breve, nella stessa prova, la risposta era «Non mi hai detto il tuo nome.» |

Limiti visti nelle prove e già noti: il revisore legge a volte «12 per 7» come una divisione; in Docker l'agente ha dichiarato salvata la nota del latte senza chiamare `add_note` e in fondo è comparso l'avviso.

### Prova reale delle preferenze

Esiti del 2026-11-17 con `google/gemma-4-e2b`, domande inviate da pipe. In locale ogni sessione usa un file di preferenze diverso indicato con `PREFERENCES_FILE`, e un servizio delle note temporaneo con 4 note di prova (`NOTES_SERVICE_URL`), così `config/preferenze.json` e `data/notes.db` restano invariati.

| Prova | Atteso | Esito |
|---|---|---|
| `fuso_orario: America/New_York`, «Che ore sono?» | ora di New York, senza chiedere il fuso | ok dopo la correzione: `get_current_time {}` e «Attualmente sono le 09:58:58 nel fuso orario America/New_York» (2 sessioni su 2; una terza sessione interrotta da un timeout di LM Studio). Con il fuso anche nel blocco delle preferenze il modello non chiamava lo strumento: nelle sonde 3 casi su 6, contro 6 su 6 senza quella riga e 12 su 12 con il prompt precedente |
| `lingua: inglese`, nuova sessione | risposte in inglese | in parte: conversioni, ora di Tokyo e nota in inglese; la risposta a «chi ha creato Python?» (dati del catalogo in italiano) è uscita in italiano in 2 sessioni su 4. Limite del modello |
| `stile: dettagliato`, «chi ha creato Python?» | risposta più lunga con paradigmi e tipizzazione | ok: autore, anno, paradigmi, tipizzazione e sintassi, approvata dal revisore |
| Valore non ammesso (per esempio `stile: medio`) | avvio con la riserva e un `WARNING` `[preferenze]` che nomina il campo | ok: con lingua `francese`, fuso `Marte/Base` e stile `medio` tre avvisi, uno per campo, e preferenze `italiano`, `Europe/Rome`, `sintetico` |
| File mancante | avvio con le riserve e un `WARNING` `[preferenze] resource non disponibile (...)` | ok: `[preferenze] resource non disponibile (Error reading resource 'utente://preferenze': file delle preferenze non leggibile: …): uso italiano, sintetico, Europe/Rome`, l'avvio prosegue |
| `LOG_LEVEL=DEBUG` | `resources/read` una sola volta, prima della prima domanda, distinta dalle `tools/call` | ok: una sola richiesta `ReadResourceRequest` all'avvio, prima della prima domanda |
| Revisore con `inglese` e `dettagliato` | nessuna bocciatura inutile; se capita, lingua della risposta rifatta | ok: tutte le risposte approvate al primo giudizio, nessuna bocciatura |
| Stile sintetico con liste: «quali note ho?» con 4 o più note e «quali linguaggi sono funzionali?» | elenco completo, approvato dal revisore | note: ok, tutte e 5 elencate. Linguaggi: «Sono stati trovati 8 linguaggi per "funzionale", mostrati 5», senza ripetere la ricerca con `max_results` più alto; risposta corretta ma parziale |
| Richiesta di una nota con `inglese` | limite dell'avviso delle note, solo italiano | «Remind me to buy milk»: `add_note` chiamato davvero, risposta in inglese; il caso del falso successo in inglese non si è presentato |
| Docker (`docker compose run --rm -T app` con input da pipe): modifica del file montato e nuova sessione senza `build` | comportamento cambiato | ok: con il file di oggi ora di Roma in italiano; cambiato il file montato in `inglese` e `America/New_York`, la sessione successiva senza `build` risponde «The current time in America/New_York is 10:10:45 AM…». Il file è stato poi ripristinato |

### Prova reale dei prompt

Esiti del 2026-11-17 con `google/gemma-4-e2b`, comandi inviati da pipe in una sola sessione (più una seconda con `LOG_LEVEL=DEBUG`).

| Prova | Atteso | Esito |
|---|---|---|
| `/prompts` | i due prompt con gli argomenti | ok: `spiega` (argomento obbligatorio, livello facoltativo) e `riassumi_conversazione` (stile facoltativo), con le descrizioni in italiano |
| `/prompt spiega argomento="Model Context Protocol" livello=base`, poi `livello=avanzato` | risposte di livello diverso | ok per il livello: la base è breve e con parole semplici, l'avanzata parla di dettagli tecnici. Il contenuto però è sbagliato: il modello non conosce MCP e lo confonde con la gestione della finestra di contesto (limite del modello, che risponde a memoria) |
| qualche domanda, poi `/prompt riassumi_conversazione` e `stile=dettagliato` | riassume i turni della sessione | ok: il sintetico in poche frasi, il dettagliato in un elenco per argomento con domanda e risposta; entrambi approvati dal revisore |
| errori: obbligatorio mancante, argomento sconosciuto, prompt inesistente, `livello=esperto`, virgolette non chiuse, `/promt` | un messaggio ciascuno, nessuna chiamata al modello | ok: i sei messaggi attesi, nessuna riga del router né del modello |
| `/prompt spiega argomento="tiramisù"` | rifiutato dal router | ok: `[router] categoria=fuori_ambito motivo=La richiesta riguarda la cucina…` e rifiuto |
| riga `[prompt]` nel log; con `LOG_LEVEL=DEBUG` `prompts/get` distinto da `tools/call` | nome, argomenti e testo | ok: `[prompt] spiega {"argomento": "l'IA"} → Spiegami «l'IA» a livello base. …` (apostrofo intatto); nel log del server una `ListPromptsRequest` all'avvio e una `GetPromptRequest` per il comando, separate da `ListToolsRequest` e `ReadResourceRequest` |
| Docker (`docker compose run --rm -T app` con input da pipe): `/prompts` e un `/prompt spiega` | come in locale | ok: `[mcp] prompt: spiega, riassumi_conversazione`, elenco, spiegazione dell'intelligenza artificiale di livello base approvata, `tema=x` bloccato |

Osservato nella stessa sessione, senza legame con i prompt: dopo le due spiegazioni lunghe il router ha rifiutato «chi ha creato Python?», che pure è fra gli esempi di `config/ambito.txt` (limite del router con un contesto lungo).

### Prova reale dell'agente come servizio

Esiti del 2026-11-18 con `google/gemma-4-e2b`. Le prove locali e Docker sono state inviate da pipe (`printf ... | python -m assistant`, `docker compose run --rm -T app`); le prove con Ctrl+C e la visualizzazione in streaming sono state fatte a mano in un terminale PowerShell.

| Prova | Atteso | Esito |
|---|---|---|
| Locale: `python -m assistant` (agente avviato in automatico), domanda con strumento («che ore sono?») | risposta con ora corretta e riga `[strumento]` | ok: `[agente] servizio: http://127.0.0.1:8001`, `get_current_time` chiamato, ora di Roma corretta, revisore «coerente» |
| Locale: domanda fuori ambito | rifiuto del router | ok: «Chi ha vinto i mondiali di calcio del 2006?» rifiutata |
| Locale: eliminare una nota, con risposta `s` e poi con `N` | domanda `[s/N]`; con `s` nota eliminata, con `N` annullata | ok (due note di prova create prima sul servizio): `Elimino la nota 6 «prova agente servizio A» · senza scadenza? [s/N]`, con `s` nota eliminata; per la nota 7 con `n` «Eliminazione della nota 7 annullata dall'utente.»; database controllato. Sulla nota 6 il modello ha prima chiesto conferma a parole senza chiamare `delete_note`: il revisore l'ha rimandato indietro e al secondo tentativo ha chiamato lo strumento |
| Locale: salvare una nota | `add_note` chiamato | non riuscito: il modello ha scritto «Nota salvata.» senza chiamare `add_note` e senza avviso ⚠ (vedi sotto) |
| Locale: Ctrl+C durante una risposta, poi un'altra domanda | `Risposta interrotta.`, il turno dopo funziona | ok (a mano): la risposta si ferma subito |
| Locale (Windows): Ctrl+C mentre router o revisore lavorano, senza testo in arrivo | `Risposta interrotta.` entro circa un secondo (keepalive SSE) | ok (a mano): si interrompe subito |
| Locale: streaming in un terminale vero | ragionamento e risposta token per token | ok (a mano). Misura: eventi ogni 0,06–0,12 s; prima del primo token 18–45 s di silenzio (router e modello); le risposte brevi compaiono quasi tutte insieme; le righe `[revisore]`, `[strumento]` e il rifiuto del router arrivano interi |
| Locale: preferenze con un valore non ammesso, `python -m assistant` senza `LOG_LEVEL=DEBUG` | l'avviso `[preferenze] ...` compare comunque all'avvio | ok: `[preferenze] lingua 'klingon' non ammesso: uso 'italiano'`, risposta in italiano |
| Locale: `/prompt spiega argomento=...` | spiegazione dal prompt MCP | ok: spiegazione della ricorsione di livello base, approvata |
| Agente da solo: `python -m agent_service`, `/docs` | pagina della documentazione | ok: `/docs` 200 e arresto con Ctrl+Break (codice 0, porte 8000 e 8001 libere); browser non provato |
| Agente da solo: `Invoke-RestMethod` su `/chat` con una domanda che usa uno strumento | risposta e traccia `[api]` nei log dell'agente | ok: `esito: completato`, chiamata `get_current_time` in `cronologia`; log `[api] turno /chat: …`, `[api] strumento …`, `[api] turno completato in 68.8 s` |
| Agente da solo: conferma in due chiamate | `conferma_richiesta`, poi eliminazione | ok: `conferme` con `id_nota` 7 e la domanda, ripresa con `{"7": true}` → nota eliminata; log `[grafo] turno sospeso`, `[api] ripresa /chat: 1 decisioni` |
| `/stato` con LM Studio non raggiungibile (503 e messaggio) e con il modello acceso (200) | 503 con il messaggio del modello / 200 | ok: 200 con tutto acceso; 503 con «LM Studio non è raggiungibile all'indirizzo http://127.0.0.1:9/v1…» (indirizzo chiuso al posto di LM Studio spento) |
| Accenti con Windows PowerShell 5.1 | «è» e «»» leggibili | prima non riuscito (`Content-Type: application/json` senza charset: «è» diventava «Ã¨»); corretto con `charset=utf-8` e riverificato |
| Docker: `docker compose build`, `docker compose run --rm app` partendo dai container fermi, una domanda con strumento | come in locale | ok: la CLI aspetta l'agente (due `GET /stato` nei log), `get_current_time`, ora corretta, revisore «coerente» |
| Docker: `docker compose logs agent` | traccia del turno | ok: righe di avvio, `[api] turno /chat/stream`, `[api] strumento get_current_time …`, `[api] turno completato in 66.7 s` |

Limiti osservati:

- Il modello piccolo a volte dichiara «Nota salvata.» senza chiamare `add_note`. Il controllo dei falsi successi ora riconosce anche la frase secca «Nota salvata.» e la richiesta esplicita non eseguita (vedi «Regole del controllo»); il limite c'era prima dell'agente come servizio.
- Una domanda mista («Spiegami la ricorsione… voglio una pompa») passa il router, perché una parte è in ambito: l'agente risponde alla parte in ambito e rifiuta l'altra. Per rifiutarle per intero basterebbe un esempio in `config/ambito.txt`.

## Diagnosi

| Sintomo | Causa probabile e rimedio |
|---|---|
| `[preferenze] resource non disponibile (...): uso italiano, sintetico, <fuso>` | (avviso mostrato anche in avvio normale) il file delle preferenze manca o non si legge: controllare `PREFERENCES_FILE` e `config/preferenze.json`; l'avvio prosegue con le riserve |
| `[preferenze] <campo> '<valore>' non ammesso: uso '<riserva>'` o `<campo> mancante: uso '<riserva>'` | campo assente, valore fuori elenco (lingua, stile) o fuso inesistente: correggere il file e riavviare; gli altri campi valgono |
| `[preferenze] contenuto non valido (...): uso italiano, sintetico, <fuso>` | il file non è un oggetto JSON valido: correggerlo e riavviare |
| il riassunto è lento o scatta troppo spesso | ogni riassunto è una chiamata in più al modello: alzare `SUMMARY_THRESHOLD` |
| `[riassunto] non riuscito (...): cronologia invariata` | il riassunto non è riuscito (errore di LM Studio o testo vuoto): la cronologia resta invariata e il turno prosegue |
| il revisore rimanda indietro risposte corrette, o il turno è lento | il revisore è un modello piccolo e ogni giudizio costa circa 23 s: ridurre `MAX_REVIEWS` (anche a `0`) |
| `... non valida` o `... mancante` all'avvio | variabile del `.env` assente o con valore non valido: il messaggio indica quale |
| `LM Studio non raggiungibile o risposta non valida su .../models` all'avvio | server di LM Studio spento o su un'altra porta: avviarlo e controllare `LMSTUDIO_BASE_URL` |
| `Modello '...' non trovato. Modelli disponibili: ...` | `LMSTUDIO_MODEL` non corrisponde a un id di `GET /v1/models`: copiarne uno dall'elenco |
| `LM Studio non è raggiungibile all'indirizzo ...` durante la sessione | il server si è fermato: riavviarlo e ripetere la domanda (la sessione continua) |
| `Il modello non ha risposto entro N secondi. Riprova.` | modello lento o ancora in caricamento: riprovare o aumentare `LMSTUDIO_TIMEOUT` |
| `Il contesto del modello è pieno: usa 'clear' ...` | cronologia troppo lunga per il modello: usare `clear` |
| `Limite di passaggi raggiunto: ...` | il modello ha chiamato lo strumento troppe volte per una domanda: riformulare o aumentare `MAX_STEPS` |
| `Impossibile avviare il server degli strumenti (...)` all'avvio | il server MCP non parte: controllare con `python -m lab_server.check` e reinstallare le dipendenze (`pip install -r requirements.txt`) |
| `Il server degli strumenti non espone nessuno strumento.` all'avvio | catalogo vuoto: controllare con `python -m lab_server.check` |
| `Il server degli strumenti non risponde: riavvia l'agente (in locale basta riavviare l'assistente).` | il server MCP si è fermato durante la sessione: uscire e riavviare l'assistente, con Docker `docker compose restart agent` (con `LOG_LEVEL=DEBUG` si vede il dettaglio) |
| `La porta 8000 è già in uso ...` o `La porta 8001 è già in uso ...` all'avvio | un altro servizio delle note o un altro agente è già acceso (di solito quello di Docker): `docker compose down` e riavviare |
| `Il servizio delle note non risponde: riavvia l'agente (in locale basta riavviare l'assistente).` | il servizio delle note si è fermato durante la sessione: uscire e riavviare l'assistente, con Docker `docker compose restart agent` |
| `L'agente non risponde: esci e riavvia l'assistente.` | la CLI non raggiunge l'agente o il flusso si è interrotto a metà turno (agente fermato o caduto): uscire e riavviare; per capire perché è caduto, rilanciare con `LOG_LEVEL=DEBUG`, o guardare `docker compose logs agent`; con `AGENT_SERVICE_URL` valorizzata controllare che l'agente sia acceso su quell'indirizzo |
| `L'agente non risponde all'indirizzo ... (atteso 60 secondi).` | con `AGENT_SERVICE_URL` valorizzata l'agente non ha risposto su `/stato` entro 60 secondi: controllare che sia acceso (`docker compose ps`, `docker compose logs agent`) |
| `/stato` risponde 503 | qualcosa non risponde: il corpo dice che cosa (`modello`, `strumenti` o `note`); con LM Studio spento l'agente resta utilizzabile appena lo si riaccende |
| `Il server ha rifiutato il prompt: ...` | il server ha respinto i valori (per esempio `livello 'esperto' non ammesso` o `argomento vuoto`): correggere il valore, gli ammessi sono in `/prompts` e in «Prompt MCP» |
| `Prompt sconosciuto: <nome>. Disponibili: ...` | nome sbagliato (maiuscole comprese): scegliere uno dei nomi di `/prompts` |
| Domande in ambito rifiutate dal router | il modello classifica male: aggiungere esempi di quel tipo in `config/ambito.txt` e riavviare |
| Il ragionamento non compare | il modello non invia `reasoning_content` oppure `SHOW_REASONING=false` nel `.env` |
| Il modello risponde senza riga `[strumento]` nel log | il modello non ha chiamato lo strumento: la risposta non è verificata; riformulare la domanda |
| Il container non raggiunge LM Studio | controllare che il server sia attivo sull'host; se serve, attivare in LM Studio l'opzione per servire sulla rete locale e riprovare |
