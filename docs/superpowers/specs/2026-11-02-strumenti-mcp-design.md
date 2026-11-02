# Strumenti MCP (prima parte) — specifica

Data: 2026-11-02 · Stato: approvata dall'utente il 2026-11-02

Riferimenti: lezione 5 del corso (slide «MCP: dalle funzioni agli strumenti condivisi»); specifica precedente `2026-10-26-assistente-laboratorio-design.md`, che resta valida per tutto ciò che qui non cambia.

## 1. Intento

Estendere l'assistente del laboratorio con strumenti esposti da un **server MCP scritto con FastMCP**, che l'assistente scopre (discovery) e invoca tramite un client MCP. Il ciclo del grafo resta quello di oggi: il modello propone la chiamata, il nodo `tools` la esegue, il risultato rientra come `ToolMessage` correlato alla richiesta, il limite di passaggi resta in vigore.

Questa consegna copre la prima parte delle proposte della lezione: l'orologio esistente spostato nel server MCP e i tre strumenti «base» (convertitore di unità, calcolatrice sicura, giorni e scadenze). Gli strumenti intermedi e avanzati arrivano dopo, con una specifica propria.

Il completamento si dimostra con evidenze (slide 31): catalogo ottenuto dal server, invocazione diretta con input noto, chiamata reale del modello con `ToolMessage` correlato, errore controllato senza falso successo, cronologia e limite ancora funzionanti, comandi documentati.

## 2. Obiettivi

- Un server FastMCP nel progetto, avviato dall'assistente come sottoprocesso con trasporto **stdio**.
- Discovery: nomi, descrizioni e schemi dei tool arrivano dal server (`tools/list`), non sono riscritti a mano nel client.
- Quattro gruppi di strumenti nel server: orologio, convertitore di unità, calcolatrice sicura, giorni e scadenze.
- Log che permettono di seguire ogni chiamata (tool, id della chiamata, argomenti, esito) e di distinguere un errore dello strumento da un errore di collegamento.
- Test automatici del server e dell'integrazione senza modello; prova reale con LM Studio per ogni strumento.
- Avvio locale e con Docker Compose come oggi.
- README e `CLAUDE.md` aggiornati con la nuova struttura e i nuovi comandi.

## 3. Non obiettivi (in questa consegna)

- Catalogo locale, note persistenti, meteo: specifica successiva.
- Trasporto Streamable HTTP, più server MCP, resources e prompts MCP.
- Equazioni (`2x = 28`) nella calcolatrice: il modello le riscrive come espressione (`28 / 2`).
- Unità anglosassoni (miglia, piedi, libbre, galloni, Fahrenheit) e cm³.
- Festività regionali, patronali o di altri paesi; validità legale delle date.
- Cambio di modello: si resta su `google/gemma-4-e2b`; se la prova reale mostra che sceglie male gli strumenti, si valuta un modello più grande cambiando solo `LMSTUDIO_MODEL`.
- Streaming della risposta, persistenza della cronologia (invariati rispetto alla specifica precedente).

**Anti-obiettivi:**
- schemi o descrizioni dei tool scritti a mano nel client (annullerebbe la discovery);
- `eval`, `exec` o simili nella calcolatrice;
- un risultato inventato o un falso successo quando l'input non è valido;
- un test con modello simulato presentato come prova che il modello sa usare gli strumenti;
- un nuovo processo server avviato a ogni chiamata.

## 4. Architettura

| Ruolo MCP (slide 9) | Nel progetto |
|---|---|
| Host | l'applicazione CLI con LangGraph (`assistant/`) |
| Client MCP | modulo dell'assistente che avvia il server, apre la sessione, legge il catalogo e converte i tool tramite `langchain-mcp-adapters` |
| Server MCP | nuovo pacchetto del progetto (nome proposto `lab_server/`), con FastMCP |

- **Server**: pacchetto separato da `assistant/`, avviabile da solo (`python -m lab_server`) in stdio. La logica di ogni strumento sta in funzioni Python pure, in moduli piccoli (uno per gruppo), testabili senza MCP; il modulo del server registra quelle funzioni con `@mcp.tool`. Con stdio, `stdout` è riservato al protocollo: tutti i log del server vanno su `stderr`.
- **Client**: all'avvio l'assistente lancia il server con lo stesso interprete Python (`sys.executable -m lab_server`), apre **una sola sessione per tutta la durata del programma**, legge il catalogo e lo registra nei log (nome di ogni tool). I tool convertiti entrano in `bind_tools` e nel `ToolNode` come oggi: il grafo non sa che dietro c'è MCP. Alla chiusura (`quit`, Ctrl+C, EOF) la sessione e il sottoprocesso vengono chiusi.
- **Sincrono/asincrono**: le librerie MCP sono asincrone, l'assistente è sincrono. L'asincronia resta confinata nel modulo client (per esempio un ciclo di eventi in un thread dedicato che tiene aperta la sessione); grafo e CLI restano sincroni. La soluzione esatta è lasciata al piano, purché la sessione sia unica e le chiamate funzionino dal `ToolNode` sincrono.
- **Configurazione condivisa**: il server riceve dall'ambiente `DEFAULT_TIMEZONE` (e `LOG_LEVEL`); l'assistente passa queste variabili al sottoprocesso. Nessuna nuova variabile d'ambiente è prevista; la validazione di `DEFAULT_TIMEZONE` resta all'avvio dell'assistente.
- **Orologio locale**: `assistant/tools.py` viene rimosso (o svuotato della logica dell'orologio); l'orologio vive solo nel server. Il modulo dei fusi (`timezones.py`, elenco da `tzdata`) va reso usabile da entrambi i lati; dove collocarlo è lasciato al piano.

## 5. Strumenti

Regole comuni:
- testi dei risultati e degli errori in italiano;
- un input non valido produce un **errore dello strumento** (in FastMCP un `ToolError`, che arriva al client come risultato con `isError`), mai un risultato di successo con dentro un messaggio d'errore. Nel grafo diventa un `ToolMessage` con stato `error`, così il modello può correggersi o spiegarlo all'utente;
- descrizioni dei tool chiare e distinguibili, perché il modello sceglie fra 7 strumenti in base a quelle.

### 5.1 Orologio — `get_current_time(timezone)`

Stesso contratto della consegna precedente (sez. 6 della specifica del 2026-10-26), ora nel server:
- `timezone` facoltativo, nome IANA esatto; vuoto o assente → `DEFAULT_TIMEZONE`; spazi ai bordi ignorati;
- calcolo da UTC con `zoneinfo`, elenco dei fusi dal pacchetto `tzdata`;
- risultato `Europe/Rome: 2026-10-26T14:32:05+01:00`;
- fuso sconosciuto → errore dello strumento `Fuso orario sconosciuto: "X". Usa un nome IANA, es. Europe/Rome.` (oggi è un risultato normale; diventa un errore, secondo la regola comune);
- sorgente dell'istante iniettabile per i test.

Va migrato per primo: è la prova che il collegamento MCP funziona con uno strumento che il modello sa già usare.

### 5.2 Convertitore di unità — `convert_units(value, from_unit, to_unit)`

Unità ammesse, **elenco chiuso** pubblicato nello schema come valori enumerati (il modello le vede nel catalogo; il server le controlla comunque):

| Categoria | Unità (simbolo nello schema) |
|---|---|
| lunghezza | `mm`, `cm`, `dm`, `m`, `dam`, `hm`, `km` |
| peso | `mg`, `cg`, `dg`, `g`, `dag`, `hg`, `kg`, `q` (quintale, 100 kg), `t` (tonnellata, 1000 kg) |
| volume | `ml`, `cl`, `dl`, `l`, `dal`, `hl`, `m3` (1000 l) |
| temperatura | `C` (gradi Celsius), `K` (kelvin) |

La descrizione del tool spiega i simboli (per esempio `q` = quintale, `m3` = metro cubo, `C` = gradi Celsius).

Comportamento:
- conversione solo fra unità della **stessa categoria**; fra categorie diverse (`km` → `kg`) → errore che nomina le due categorie;
- unità fuori elenco → errore che elenca le unità ammesse (anche se lo schema già lo impedisce);
- valori negativi ammessi solo per la temperatura; per lunghezza, peso e volume → errore;
- temperatura sotto lo zero assoluto (< 0 K, cioè < −273,15 °C) → errore;
- temperatura: K = °C + 273,15; le altre categorie sono rapporti;
- `from_unit` uguale a `to_unit` è valido e restituisce lo stesso valore;
- risultato con valore e unità di partenza e di arrivo, per esempio `1.5 km = 150000 cm`, senza artefatti della virgola mobile (`1.1 km` deve dare `110000 cm`, non `110000.00000000001 cm`). *Scelta di Claude:* nessun arrotondamento a un numero fisso di decimali oltre a quanto serve per eliminare quegli artefatti; la presentazione è lasciata al modello.

### 5.3 Calcolatrice sicura — `calculate(expression)`

Ammesso:
- numeri interi e decimali (con il punto), `+`, `-`, `*`, `/`, parentesi, segno meno e più unari;
- potenza scritta `^` oppure `**` (entrambe significano elevamento a potenza).

Calcolo **senza `eval`**: l'espressione viene analizzata (per esempio con il modulo `ast` di Python) e si accettano solo i nodi ammessi; tutto il resto è rifiutato prima di calcolare.

Rifiutato con un errore esplicito che dice perché:
- lettere, nomi, funzioni, attributi, virgolette (`x + 1`, `sqrt(4)`, `__import__('os')`);
- `=` e quindi le equazioni (il messaggio suggerisce di riscriverle come espressione);
- divisione per zero;
- espressioni malformate (`3 +* 4`, `(2 + 3`) o vuote;
- espressioni troppo lunghe, esponenti o risultati troppo grandi (`9^9^9`), che bloccherebbero il programma. *Scelta di Claude:* i limiti esatti (lunghezza dell'espressione, valore massimo dell'esponente, grandezza del risultato) sono lasciati al piano, purché nessuna espressione ammessa richieda più di una frazione di secondo.

Risultato: espressione e valore, per esempio `10 * 7 / 9 = 7.777777777777778`, `2^5 = 32` (un risultato intero si mostra senza `.0`).

### 5.4 Giorni e scadenze

Quattro tool. Tutte le date in ingresso e in uscita sono **ISO 8601** (`AAAA-MM-GG`). «Oggi» è la data corrente nel fuso `DEFAULT_TIMEZONE`, con sorgente dell'istante iniettabile per i test. Ogni risultato riporta:
- la data ISO e il **giorno della settimana in italiano**;
- se la data è una festività, il suo nome;
- se la data è **passata, oggi o futura** rispetto a oggi;
- la dicitura «indicativo, non normativo».

| Tool | Argomenti | Risponde a |
|---|---|---|
| `date_info(date)` | data ISO | «che giorno della settimana è il 25 dicembre 2026?» |
| `find_holiday(name, year)` | nome della festività; anno facoltativo | «che giorno della settimana è Pasqua?», «che giorno sarà Natale?» |
| `add_days(days, start)` | numero di giorni, anche negativo; data di partenza facoltativa (default oggi) | «che giorno sarà tra 24 giorni?» |
| `days_between(end, start)` | data di arrivo; data di partenza facoltativa (default oggi) | «quanti giorni mancano a Natale?» (*proposta di Claude*, non richiesta) |

**Date passate (richiesta dell'utente).** Quando la data trovata è nel passato, il risultato lo dice esplicitamente invece di sostituirla in silenzio:
- `find_holiday` senza anno, se la festività di quest'anno è già passata: segnala che è passata e dà anche la prossima. Esempio, con oggi 2026-11-02: «Pasqua 2026 (2026-04-05, domenica) è già passata; la prossima è il 2027-03-28, domenica». Se non è ancora passata (o è oggi), dà quella dell'anno corrente;
- `find_holiday` con un anno esplicito nel passato: dà quella data e segnala che è passata;
- `date_info`, `add_days` (con giorni negativi o partenza nel passato) e `days_between`: segnalano quando la data risultante è passata.

Le date devono attraversare correttamente il **cambio d'anno** (per esempio 2026-12-20 + 24 giorni = 2027-01-13) e gli anni bisestili.

**Festività.** File JSON locale nel pacchetto del server, con le festività nazionali italiane:
- a data fissa: Capodanno (1/1), Epifania (6/1), Festa della Liberazione (25/4), Festa del Lavoro (1/5), Festa della Repubblica (2/6), Ferragosto (15/8), Ognissanti (1/11), Immacolata Concezione (8/12), Natale (25/12), Santo Stefano (26/12);
- mobili: Pasqua e Lunedì dell'Angelo (Pasquetta), descritte nel file come spostamento rispetto a Pasqua (0 e +1 giorno); la data di Pasqua la **calcola il programma** con l'algoritmo del calendario gregoriano (computus), quindi vale per qualunque anno ammesso.

Il nome passato a `find_holiday` si riconosce senza distinzione di maiuscole e con alcuni nomi alternativi presenti nel file (per esempio «Pasquetta», «25 aprile», «Liberazione»). Nome sconosciuto → errore che elenca i nomi disponibili.

Errori (errore dello strumento, messaggio chiaro):
- data non in formato ISO (`25/12/2026`) → indica il formato atteso;
- data inesistente (`2026-02-30`);
- anno o risultato fuori dall'intervallo ammesso. *Scelta di Claude:* anni dal 1900 al 2200;
- festività sconosciuta.

## 6. Grafo, istruzioni di sistema e limite di passaggi

- Il grafo non cambia struttura: `START → model → (tools | step_limit | END)`, `tools → model`, `step_limit → END`. La lista dei tool passata a `build_graph` è quella ottenuta dal catalogo MCP.
- Istruzioni di sistema aggiornate: usare sempre gli strumenti per ora, date, conversioni e calcoli, senza inventare risultati; riscrivere le equazioni semplici come espressione per la calcolatrice; per le date usare il formato ISO; se uno strumento restituisce un errore, spiegarlo all'utente o correggere gli argomenti. Restano le indicazioni attuali (italiano, presentazione al saluto, fuso predefinito, domanda su un altro fuso).
- `MAX_STEPS` resta 5 di default; la prova reale verifica che basti per le domande previste.

## 7. Log ed errori

- **Avvio**: una riga `INFO` con il catalogo letto dal server (nomi dei tool). Server che non parte o catalogo vuoto/illeggibile → messaggio chiaro e uscita con codice 1, come per LM Studio non raggiungibile.
- **Ogni chiamata** (lato assistente, `INFO`): tool, id della chiamata del modello, argomenti, esito (`ok` o `errore`) e risultato o messaggio d'errore. Formato ispirato alla traccia della slide 23; il testo esatto è lasciato al piano.
- **Lato server** (`stderr`): una riga per chiamata eseguita. Il sottoprocesso scrive sullo stesso terminale dell'assistente. *Scelta di Claude:* con `LOG_LEVEL=INFO` l'utente vede solo la riga dell'assistente per ogni chiamata; le righe del server compaiono solo con `DEBUG`. Il banner di avvio di FastMCP non deve comparire.
- **Errore dello strumento** (input non valido): torna al modello come `ToolMessage` con stato `error`; la sessione continua.
- **Errore di collegamento** (server terminato, sessione chiusa, nessuna risposta): è diverso da un errore dello strumento. *Scelta di Claude:* il turno viene interrotto con un messaggio all'utente («Il server degli strumenti non risponde…»), la domanda non entra in cronologia (come gli errori di LM Studio); il messaggio indica di riavviare l'assistente. Riavvio automatico del server: non previsto.
- `DEBUG` mostra in più i dettagli del protocollo e delle librerie MCP, come oggi per HTTP.

## 8. Dipendenze

Verifica su PyPI del 2026-11-02:
- `fastmcp` 4.1.5 (ultima) richiede `mcp >= 2.3`, mentre `langchain-mcp-adapters` 0.3.2 (ultima) richiede `mcp < 2.0`: le due ultime versioni non sono installabili insieme.
- *Scelta di Claude:* `fastmcp` 3.4.11 (ultima della serie 3, 2026-10-20, richiede `mcp < 2.0, >= 1.24`), `mcp` 1.30.0, `langchain-mcp-adapters` 0.3.2 (richiede `langchain-core >= 1.3.3`, compatibile con la 1.7.0 in uso). Il codice del server resta quello delle slide (`from fastmcp import FastMCP`, `@mcp.tool`). Alternativa scartata: `fastmcp` 4 con un adattatore scritto a mano, più codice da mantenere senza vantaggi in questo progetto.
- Versioni da confermare installando e importando su Python 3.14, insieme alle dipendenze già fissate (`langgraph` 1.2.17, `langchain-core` 1.7.0, `langchain-openai` 1.7.2), prima di fissarle con `==` in `requirements.txt`. *Scelta di Claude:* se la combinazione non si installa o non funziona, il lavoro si ferma e si torna dall'utente; nessun ripiego automatico (per esempio la classe FastMCP inclusa in `mcp`, che non corrisponde al codice delle slide).

| Pacchetto | Motivo |
|---|---|
| `fastmcp` | scrivere il server MCP e i tool con decoratori; schema ricavato dalla firma |
| `mcp` | protocollo (dipendenza di `fastmcp` e dell'adattatore), fissato per evitare il conflitto sopra |
| `langchain-mcp-adapters` | convertire il catalogo MCP in tool LangChain e invocarli dal `ToolNode` |

Nessun'altra dipendenza nuova: calcolatrice (`ast`), date (`datetime`), conversioni, JSON delle festività usano la libreria standard.

## 9. Docker

- Il server gira nello stesso container, avviato dall'assistente come sottoprocesso: nessun nuovo servizio in `compose.yaml`, nessuna porta.
- Il `Dockerfile` copia anche il pacchetto del server, compreso il file JSON delle festività.
- Avvio invariato: `docker compose build`, `docker compose run --rm app`.

## 10. Test e verifiche

### Test automatici (senza modello e senza LM Studio)
- **Logica degli strumenti** (funzioni pure): per ogni gruppo, i casi di successo e tutti gli errori delle sezioni 5.1–5.4. In particolare: orologio con istante fisso (come oggi, ora legale compresa); conversioni in ogni categoria, fra categorie diverse, negativi, zero assoluto, artefatti della virgola mobile; calcolatrice con espressioni ammesse e rifiutate (`__import__('os')`, `9^9^9`, `1/0`, `2x = 28`); date con oggi fisso, cambio d'anno, bisestili, Pasqua di più anni noti (2026-04-05, 2027-03-28), festività già passata con e senza anno, formati errati.
- **Server MCP**: con un client FastMCP in memoria, catalogo con i 7 tool e i loro schemi (le unità come valori enumerati); invocazione diretta con input noto; un input non valido produce un errore MCP, non un successo.
- **Integrazione**: il client dell'assistente avvia davvero il server in stdio, legge il catalogo e invoca un tool; il grafo con il modello finto chiama un tool MCP e riceve il `ToolMessage` correlato (stesso `tool_call_id`); errore dello strumento → `ToolMessage` con stato `error`; errore di collegamento → messaggio all'utente e cronologia invariata; limite di passaggi ancora rispettato.
- Restano verdi i test esistenti di grafo, CLI, configurazione e avvio (adattati dove l'orologio non è più locale).

### Verifiche dirette sul server
Un modo documentato nel README per elencare il catalogo e invocare un tool **senza l'assistente e senza il modello** (slide 24 e 31). Lo strumento esatto (piccolo script del progetto, CLI di FastMCP o MCP Inspector) è lasciato al piano, purché il comando sia verificato in PowerShell.

### Prova reale con LM Studio (manuale, attivata esplicitamente)
Per ogni strumento, in locale e almeno una volta con Docker, registrando l'esito nel README:
- orologio: «che ora è?», «e a Tokyo?» (come la prova precedente, ora passando da MCP);
- convertitore: «quanti cm sono 2,5 km?», «converti 3 hl in litri», «quanti kg sono 2 quintali?», «20 °C in kelvin», e una conversione impossibile come «converti 5 km in kg»;
- calcolatrice: «quanto fa 10 * 7 / 9?», «2 alla 5», «risolvi 2x = 28» (il modello deve chiedere `28 / 2`), e un input da rifiutare;
- date: «che giorno della settimana è Pasqua?» (deve avvisare che Pasqua 2026 è passata e dare la 2027), «che giorno sarà Natale?», «che giorno sarà tra 24 giorni?», «quanti giorni mancano a Natale?»;
- continuità: memoria tra due domande, `clear`, limite di passaggi.

Nei log deve comparire la chiamata reale con argomenti ed esito. Se il modello sceglie lo strumento sbagliato o non lo chiama, si registra il punto esatto e non si dichiara completato quel passo.

## 11. Ordine di lavoro e branch

**Branch (richiesta dell'utente).** Ogni funzionalità si sviluppa in un branch `feature/<nome>` creato da `developer`. Quando la funzionalità è completa e verificata, il branch viene unito in `developer` (con `--no-ff`, per lasciare traccia), `developer` viene pushato e il branch feature viene eliminato. Si riparte da `developer` aggiornato per la funzionalità successiva.

**Pezzi piccoli (richiesta dell'utente).** Dentro ogni branch il lavoro procede a passi piccoli, ciascuno con test, verifica e commit (Conventional Commits in italiano); niente blocchi grandi di codice in un solo passo, salvo diversa indicazione dell'utente.

Funzionalità, in ordine (nomi dei branch proposti da Claude):
1. `feature/mcp-orologio`: server FastMCP con l'orologio, client MCP nell'assistente, rimozione dell'orologio locale; prova reale dell'orologio via MCP;
2. `feature/convertitore-unita`: convertitore di unità;
3. `feature/calcolatrice-sicura`: calcolatrice sicura;
4. `feature/giorni-scadenze`: giorni e scadenze.

Ogni branch aggiorna README e `CLAUDE.md` per la parte che introduce (struttura con il server, comandi, verifiche dirette, prove reali, diagnosi; confini aggiornati: MCP ora in uso; catalogo, note e meteo ancora da fare), così `developer` resta documentato dopo ogni unione.

## 12. Struttura prevista

```
Progetto1LLM/
├── assistant/          # host: config, llm, graph, cli, avvio, client MCP (nuovo)
├── lab_server/         # server MCP FastMCP (nome proposto)
│   ├── __main__.py     # avvio in stdio
│   ├── server.py       # registrazione dei tool
│   ├── clock.py, units.py, calculator.py, dates.py
│   └── holidays.json
├── tests/
└── ...                 # invariati: Dockerfile (con COPY del server), compose.yaml, requirements, README, CLAUDE.md
```

## 13. Scelte fatte da Claude (da rivedere)

- FastMCP 3.4.11 invece della 4 per compatibilità con `langchain-mcp-adapters` (sez. 8).
- Un solo server con tutti gli strumenti, trasporto stdio, sessione unica per la durata del programma.
- Orologio spostato nel server e rimosso dall'assistente; fuso sconosciuto ora restituito come errore dello strumento.
- Simboli delle unità nello schema (`C`, `K`, `m3`, `q`, `t`); negativi ammessi solo per la temperatura; nessun arrotondamento oltre a eliminare gli artefatti della virgola mobile.
- Potenza con `^` e `**`; limiti di lunghezza ed esponente nella calcolatrice.
- `days_between` aggiunto; anno facoltativo in `find_holiday`; intervallo di anni 1900–2200; Pasqua calcolata, Pasquetta come spostamento.
- Errore di collegamento con il server: turno interrotto, nessun riavvio automatico.
- Log del server visibili solo con `DEBUG`; senza banner di FastMCP.
- Se le versioni non si installano insieme su Python 3.14: stop e domanda all'utente, nessun ripiego.
- Nessuna nuova variabile d'ambiente.

## 14. Lasciato al piano

- Collocazione del modulo dei fusi, condiviso fra assistente e server.
- Meccanismo esatto per usare il client MCP asincrono dal grafo sincrono.
- Formato esatto delle righe di log e dei testi di successo/errore non fissati qui.
- Limiti numerici della calcolatrice.
- Strumento per la verifica diretta del server.
