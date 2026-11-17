# Prompt MCP richiamati dalla CLI (lezione 6, step 5) — specifica

Data: 2026-11-17 · Stato: approvata dall'utente il 2026-11-17

Riferimenti: lezione 6, slide 9 (prompt: istruzioni scelte dall'utente), 10 (step 5 · prompt: comandi riusabili nella CLI), 11 (tool, resource e prompt; evidenza minima «/prompts e /prompt funzionanti, con argomenti validati»). Specifiche precedenti valide per tutto ciò che qui non cambia, in particolare `2026-11-17-preferenze-resource-design.md` (MCPClient e resource) e le specifiche di router, revisore, riassunto e streaming.

## 1. Intento

Il server MCP offre già **tool** (li sceglie il modello) e una **resource** (la legge il programma all'avvio). Questo step aggiunge la terza primitiva: i **prompt**, modelli di domanda con argomenti salvati sul server e richiamati **esplicitamente dall'utente** con un comando della CLI. MCP non prevede un comando standard: i comandi `/prompts` e `/prompt` li definisce la nostra CLI. Il testo compilato dal server entra nella cronologia e passa dal grafo **come qualsiasi altra domanda**: router, strumenti, revisore, riassunto.

## 2. Che cosa è stato verificato (2026-11-17, sonda in memoria con `fastmcp==3.4.11`)

- `@mcp.prompt` su una funzione con argomenti `Annotated[str, Field(description=...)]`: `list_prompts()` dà nome, descrizione (docstring) e per ogni argomento `name`, `required` (vero se senza valore predefinito) e `description`. FastMCP **aggiunge alla descrizione** dell'argomento `\n\nProvide as a JSON string matching the following schema: {...}`.
- `get_prompt(nome, argomenti)` restituisce i messaggi (`role`, `content.text`).
- Argomento obbligatorio mancante → `McpError` «Error rendering prompt 'spiega': Missing required arguments: {'argomento'}». Prompt inesistente → `McpError` «Unknown prompt: 'inesistente'».
- **Argomento sconosciuto** (`tema=x`) → **nessun errore**: il server lo ignora. Il controllo nell'host è quindi necessario.
- Valore non ammesso con `Literal`: errore inglese lungo («Could not convert argument 'livello' …»). Con un controllo nella funzione che solleva `ValueError("livello 'esperto' non ammesso (ammessi: base, intermedio, avanzato)")` l'errore arriva come `McpError` «Error rendering prompt 'spiega': livello 'esperto' non ammesso (ammessi: base, intermedio, avanzato)».
- `langchain_mcp_adapters.prompts.load_mcp_prompt` esiste, ma non serve: la sessione `mcp` di `assistant/mcp_client.py` offre già `list_prompts` e `get_prompt`.

## 3. Obiettivi (slide 10)

1. Prompt `spiega(argomento, livello)` e `riassumi_conversazione(stile)`.
2. Comando `/prompts` con nome, descrizione e argomenti di ogni prompt.
3. Comando `/prompt nome argomento=valore`: i messaggi ottenuti si aggiungono alla cronologia e vanno al grafo.
4. Controllo nell'host rispetto a `prompts/list`: argomenti obbligatori mancanti o sconosciuti bloccano la richiesta, senza chiamare il modello.

Evidenze richieste: `/prompt spiega argomento="Model Context Protocol" livello=base` → risposta adeguata al livello; `riassumi_conversazione` riassume i turni della sessione corrente; log con prompt richiamato, argomenti e messaggi ottenuti dal server.

**Non obiettivi**: prompt diversi dai due della slide; completamento automatico dei comandi; prompt con più messaggi o con messaggi dell'assistente (gestiti se arrivano, ma non prodotti); tradurre i testi fissi.

## 4. Scelte dell'utente (proposta di Claude approvata in chat)

- `spiega(argomento, livello)`: `argomento` obbligatorio; `livello` facoltativo, predefinito `base`, ammessi `base`, `intermedio`, `avanzato`. Il testo dice il livello e che cosa significa.
- `riassumi_conversazione(stile)`: `stile` facoltativo, predefinito `sintetico`, ammessi `sintetico`, `dettagliato` (come nelle preferenze). Il server non conosce la conversazione: restituisce la richiesta di riassunto, e riassume l'agente, che ha la cronologia.
- `/prompts`: per ogni prompt `nome — descrizione`, poi una riga per argomento `  nome (obbligatorio|facoltativo): descrizione`.
- `/prompt nome k=v k="valore con spazi"`: virgolette solo per i valori con spazi. Dopo il comando una riga con il testo compilato, poi il turno come una domanda normale (fuori ambito rifiutato dal router, per esempio `argomento="tiramisù"`).
- Errori senza chiamare il modello: obbligatorio mancante «Argomento obbligatorio mancante per spiega: argomento.»; sconosciuto «Argomento sconosciuto per spiega: tema (ammessi: argomento, livello).»; prompt inesistente → messaggio con l'elenco; valore non ammesso rifiutato dal server, errore mostrato senza chiamare il modello.
- `help` mostra i due comandi; log con nome, argomenti e messaggi.

## 5. Comportamento

### 5.1 Server MCP

- Nuovo modulo `lab_server/prompts.py` con funzioni pure che compongono i testi e validano i valori (sollevano `ValueError` con il messaggio in italiano), come gli altri moduli del server. `lab_server/server.py` registra i due prompt con `@mcp.prompt`; l'errore della funzione arriva al client come errore MCP (verificato, 2).
- Descrizioni (docstring): `spiega` «Spiega un argomento al livello richiesto.»; `riassumi_conversazione` «Riassume i turni della sessione corrente.». Descrizioni degli argomenti: `argomento` «concetto da spiegare»; `livello` «base, intermedio o avanzato»; `stile` «sintetico o dettagliato».
- Testi (esatti al piano, indicativi qui):
  - `spiega`: `Spiegami «<argomento>» a livello <livello>. <indicazione>` con indicazione: base «Usa parole semplici, spiega i termini tecnici e fai un esempio concreto.»; intermedio «Dai per note le basi: spiega come funziona, con un esempio.»; avanzato «Entra nei dettagli tecnici: funzionamento interno, scelte di progetto e limiti.».
  - `riassumi_conversazione`: `Riassumi la conversazione fin qui, basandoti solo sui messaggi precedenti e senza usare strumenti: <indicazione>` con sintetico «in poche frasi, solo gli argomenti principali.» e dettagliato «per ogni argomento, che cosa è stato chiesto e che cosa è stato risposto, in un breve elenco.».
- Valori non ammessi: `livello '<valore>' non ammesso (ammessi: base, intermedio, avanzato)`, `stile '<valore>' non ammesso (ammessi: sintetico, dettagliato)`. `argomento` vuoto o fatto di soli spazi: `argomento vuoto: indica il concetto da spiegare` (*scelta di Claude*).
- `python -m lab_server.check` elenca anche i prompt (nome, descrizione, argomenti) dopo tool e resource (*scelta di Claude*, come per la resource).

### 5.2 Client MCP

- `MCPClient.list_prompts() -> list[PromptInfo]` e `MCPClient.get_prompt(name, arguments) -> list[tuple[str, str]]` (ruolo, testo), sincroni sulla stessa sessione di tool e resource. Un errore del server (prompt inesistente, argomenti, valore non ammesso) → `MCPPromptError(<messaggio>)`; connessione persa o timeout → `MCPConnectionError`, con la stessa distinzione per codice già usata da `read_resource`.
- `PromptInfo` e i suoi argomenti tengono nome, descrizione e `required`. La descrizione di ogni argomento è **solo la prima parte**, prima di `\n\n` (toglie la frase aggiunta da FastMCP, 2).
- Il messaggio di `MCPPromptError` toglie il prefisso `Error rendering prompt '<nome>': ` quando c'è, così resta il testo in italiano.
- L'elenco dei prompt si legge **una volta all'avvio**, dopo il catalogo dei tool e le preferenze, con la riga `INFO` `[mcp] prompt: spiega, riassumi_conversazione` (*scelta di Claude*: come il catalogo dei tool). Un elenco vuoto non ferma l'avvio.

### 5.3 Comandi della CLI

Nuovo modulo `assistant/prompts.py` (comandi `/prompts` e `/prompt`: analisi, controllo, testi), usato da `cli.run`.

- **`/prompts`** (esatto, minuscole o maiuscole come gli altri comandi): stampa l'elenco letto all'avvio.
  ```
  spiega — Spiega un argomento al livello richiesto.
    argomento (obbligatorio): concetto da spiegare
    livello (facoltativo): base, intermedio o avanzato
  riassumi_conversazione — Riassume i turni della sessione corrente.
    stile (facoltativo): sintetico o dettagliato
  ```
  Nessun prompt disponibile: «Nessun prompt disponibile sul server.».
- **`/prompt <nome> [k=v …]`**: il resto della riga si divide sugli spazi; solo le virgolette doppie raggruppano un valore con spazi (si tolgono), così `argomento="Model Context Protocol"` diventa un solo valore. L'apostrofo è un carattere ordinario, quindi `argomento=l'IA` funziona (con `shlex` darebbe «virgolette non chiuse»): scostamento da shlex deciso nel piano e approvato dall'utente. Controlli, nell'ordine, **senza chiamare il modello né il server** fino all'ultimo:
  1. nome mancante → `Uso: /prompt <nome> argomento=valore …  (elenco con /prompts)`;
  2. virgolette non chiuse → `Virgolette non chiuse: controlla il comando.`;
  3. prompt non nell'elenco → `Prompt sconosciuto: <nome>. Disponibili: spiega, riassumi_conversazione.`;
  4. elemento senza `=` o con nome vuoto → `Argomento non valido: '<elemento>'. Usa nome=valore, per esempio argomento="Model Context Protocol".`;
  5. nome ripetuto → `Argomento ripetuto per <prompt>: <nome>.` (*scelta di Claude*);
  6. argomento sconosciuto → `Argomento sconosciuto per <prompt>: <nome> (ammessi: <nomi in ordine dell'elenco>).` (il primo trovato);
  7. obbligatorio mancante → `Argomento obbligatorio mancante per <prompt>: <nome>.` (il primo mancante);
  8. richiesta al server: un `MCPPromptError` → `Il server ha rifiutato il prompt: <messaggio>` (per esempio il valore non ammesso), senza chiamare il modello; un `MCPConnectionError` → stesso messaggio di oggi per il server degli strumenti caduto.
- **Comando sconosciuto** che inizia con `/` (per esempio `/promt`) → `Comando sconosciuto: /promt. Comandi: help, clear, /prompts, /prompt.` senza chiamare il modello (*scelta di Claude*: altrimenti un errore di battitura finirebbe al modello come domanda).
- **Esito valido**: i messaggi ricevuti diventano `HumanMessage` (ruolo `user`) o `AIMessage` (ruolo `assistant`) e prendono il posto della `HumanMessage(text)` di una domanda normale: cronologia + messaggi → grafo. Il turno da lì è identico a una domanda (streaming, ragionamento, strumenti, revisore, riassunto, conferme, Ctrl+C, errori); a turno riuscito i messaggi del prompt restano nella cronologia.
- `help`: due righe nuove, `  /prompts    elenca i prompt del server` e `  /prompt     richiama un prompt: /prompt nome argomento=valore …`.

### 5.4 Terminale e log

- Prima del turno, una riga `INFO` dedicata (visibile come le righe `[router]`): `[prompt] <nome> <argomenti in JSON> → <testo del primo messaggio>` (testo esatto al piano). Con più messaggi, il numero e il testo di ciascuno a `DEBUG`.
- Gli errori di analisi e controllo sono righe nel terminale (non log), come gli altri messaggi della CLI.
- Con `LOG_LEVEL=DEBUG` le richieste `prompts/list` (avvio) e `prompts/get` compaiono nei log MCP, separate da `tools/call` e `resources/read`.

### 5.5 Router

- `config/ambito.txt`: esempio in più `«Riassumi la conversazione fin qui» → conversazione (domanda sulla conversazione)` (*scelta di Claude*: il testo di `riassumi_conversazione` è una domanda sulla conversazione, già in ambito con «Di cosa abbiamo parlato?»; l'esempio la rende esplicita). `spiega` su informatica o IA è già in ambito; su altri argomenti viene rifiutato, come previsto.

## 6. Test e verifiche

### Test automatici (senza LM Studio)
- `lab_server/prompts.py`: testi esatti per ogni livello e stile; predefiniti; valori non ammessi e argomento vuoto → `ValueError` con il messaggio.
- Server (client FastMCP in memoria): i due prompt elencati con descrizioni e argomenti (`required` giusto); `get_prompt` restituisce il testo; valore non ammesso → errore con il messaggio italiano.
- Client MCP (server di prova di `tests/mcp_test_server.py` esteso con un prompt): `list_prompts` con descrizioni ripulite; `get_prompt`; errore del server → `MCPPromptError` senza prefisso inglese; la sessione resta utilizzabile; connessione persa → `MCPConnectionError`.
- `assistant/prompts.py`: ogni controllo di 5.3 con il testo esatto; divisione con sole virgolette doppie (non `shlex`); formato di `/prompts`; conversione dei messaggi.
- `cli.run`: `/prompts`; `/prompt` valido → il grafo riceve cronologia + messaggi del prompt e la cronologia li conserva; ogni errore → il grafo **non** viene chiamato; comando sconosciuto con `/`; `help`.
- `check`: righe dei prompt.
- Restano verdi tutti i test esistenti.

### Prova reale con LM Studio (separata, attivata esplicitamente)
- `/prompts`.
- `/prompt spiega argomento="Model Context Protocol" livello=base` e poi `livello=avanzato`: risposte di livello diverso.
- Qualche domanda, poi `/prompt riassumi_conversazione` e `stile=dettagliato`: riassume i turni della sessione.
- Errori: obbligatorio mancante, sconosciuto, prompt inesistente, `livello=esperto`, virgolette non chiuse, `/promt`: nessuna chiamata al modello.
- `/prompt spiega argomento="tiramisù"`: rifiutato dal router.
- Log `[prompt]` con nome, argomenti e testo; con `LOG_LEVEL=DEBUG` `prompts/get` distinto da `tools/call`.
- Docker via pipe: `/prompts` e un `/prompt spiega`.
Esiti nel README.

## 7. Ordine di lavoro e branch

Branch `feature/prompt` da `developer`; merge `--no-ff` dopo la prova reale e l'ok dell'utente, push, eliminazione del branch. README (comandi, sezione sui prompt, diagnosi, esiti), `CLAUDE.md` (struttura: `lab_server/prompts.py`, `assistant/prompts.py`) aggiornati.

## 8. Scelte fatte da Claude (da rivedere)

- Controllo dei valori nel server con messaggi in italiano (invece di `Literal`, che dà un errore inglese); argomento vuoto rifiutato.
- Descrizioni degli argomenti ripulite dalla frase aggiunta da FastMCP; prefisso inglese tolto dagli errori del server.
- Elenco dei prompt letto una volta all'avvio, con la riga `[mcp] prompt: …`.
- Comandi sconosciuti che iniziano con `/` bloccati con un messaggio; argomenti ripetuti rifiutati.
- Esempio «Riassumi la conversazione fin qui» in `config/ambito.txt`.
- `lab_server.check` che elenca anche i prompt.
- Testi dei due prompt e delle indicazioni di livello e stile.
- Divisione degli argomenti con le sole virgolette doppie, apostrofo ordinario: scostamento da shlex deciso nel piano e approvato dall'utente.

## 9. Lasciato al piano

- Testi esatti dei prompt, delle righe di log e dei messaggi d'errore (quelli in 5.3 sono già esatti).
- Nomi e firme (`PromptInfo`, `MCPPromptError`, funzioni di `assistant/prompts.py`, nuova firma di `cli.run`).
