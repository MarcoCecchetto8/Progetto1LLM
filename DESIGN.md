---
name: Pico
description: Chat dell'assistente del laboratorio, dove ogni strumento eseguito è un reperto catalogato accanto alla risposta.
colors:
  ground: "#dfe4df"
  ground-deep: "#d3d9d4"
  rail: "#1f3b33"
  rail-hover: "#284a40"
  rail-active: "#315a4e"
  rail-ink: "#eef3ef"
  rail-mute: "#b5c7bd"
  rail-line: "#3d5f54"
  card: "#fbfbf8"
  line: "#c3cbc5"
  line-strong: "#8d9b93"
  ink: "#1b1f1d"
  mute: "#4f5c55"
  brass: "#8a6a2a"
  brass-bright: "#c9a35a"
  focus: "#b08a3e"
  strip: "#2b2b2a"
  strip-ink: "#f1f0ea"
  strip-mute: "#b9b8b0"
  signal: "#c8102e"
  signal-soft: "#fbe9ec"
  user: "#1f3b33"
  user-ink: "#f6f8f6"
  action: "#1f3b33"
  action-hover: "#315a4e"
  action-text: "#1f3b33"
typography:
  display:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  brand:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "28px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "0.01em"
  title:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
    fontFeature: "tnum"
  label:
    fontFamily: "\"Segoe UI\", system-ui, -apple-system, \"Helvetica Neue\", Arial, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    letterSpacing: "0.14em"
  mono:
    fontFamily: "Consolas, \"Cascadia Mono\", ui-monospace, \"SFMono-Regular\", Menlo, monospace"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.45
rounded:
  tag: "3px"
  sheet: "4px"
  control: "6px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  gutter: "40px"
components:
  button-primary:
    backgroundColor: "{colors.action}"
    textColor: "{colors.user-ink}"
    rounded: "{rounded.control}"
    padding: "0 24px"
    width: "116px"
  button-primary-hover:
    backgroundColor: "{colors.action-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.card}"
    textColor: "{colors.mute}"
  button-secondary:
    backgroundColor: "{colors.card}"
    textColor: "{colors.signal}"
    rounded: "{rounded.control}"
    padding: "0 24px"
  button-secondary-hover:
    backgroundColor: "{colors.signal-soft}"
  button-rail:
    backgroundColor: "{colors.rail}"
    textColor: "{colors.rail-ink}"
    rounded: "{rounded.control}"
    padding: "9px 12px"
  button-rail-hover:
    backgroundColor: "{colors.rail-hover}"
  input-composer:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
    height: "56px"
  card-answer:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sheet}"
    padding: "12px 18px"
    width: "680px"
  card-tool:
    backgroundColor: "{colors.strip}"
    textColor: "{colors.strip-ink}"
    typography: "{typography.mono}"
    rounded: "{rounded.sheet}"
    width: "680px"
  message-user:
    backgroundColor: "{colors.user}"
    textColor: "{colors.user-ink}"
    rounded: "{rounded.sheet}"
    padding: "10px 16px"
    width: "620px"
  tag-tool:
    backgroundColor: "{colors.strip}"
    textColor: "{colors.strip-ink}"
    typography: "{typography.mono}"
    rounded: "{rounded.tag}"
    padding: "2px 8px"
  nav-chat-item-active:
    backgroundColor: "{colors.rail-active}"
    textColor: "{colors.rail-ink}"
    rounded: "{rounded.control}"
---

# Design System: Pico

## Overview

**Creative North Star: "La sala del museo della scienza"**

Pico vive in una sala di museo della scienza: intonaco grigio-verde come fondo, una colonna verde museo a sinistra che fa da indice delle sale (le chat), cartellini smaltati chiari a bordo sottile per le risposte. Gli strumenti che l'assistente esegue davvero non spariscono dietro la risposta: compaiono come schede magnetiche della Programma 101, bande grafite a tutta cornice con testo monospaziato, numero in ottone e l'esito su una riga propria. Il meccanismo è il reperto esposto.

La densità è quella di uno strumento di lavoro, non di una vetrina: scala tipografica stretta, gerarchia affidata al peso e al maiuscoletto spaziato più che alla dimensione, cifre tabellari ovunque perché tempi, numeri di scheda e conteggi dei token si leggano in colonna. Il rosso Olivetti è raro e significa sempre la stessa cosa: errore, avviso, scelta irreversibile. Tema chiaro e scuro seguono il sistema; lo scuro mantiene gli stessi ruoli con superfici più profonde e accenti più luminosi.

**Key Characteristics:**
- Fondo intonaco, colonna verde museo, cartellini chiari a bordo sottile.
- Schede-strumento grafite e monospaziate, numerate in ottone, con stato «in esecuzione» ed esito.
- Un'unica famiglia sans, gerarchia per peso e etichette in maiuscolo spaziato.
- Rosso riservato a errori, avvisi ed eliminazioni.
- Movimento minimo: transizioni di 160ms e un solo impulso per l'attesa.

## Colors

Una tavolozza da museo tecnico: neutri grigio-verdi, un verde profondo strutturale, grafite per le macchine, ottone per i numeri e un rosso segnaletico.

### Primary
- **Verde museo** (`rail`, `action`, `user`): la colonna delle chat, il pulsante «Invia» e i messaggi dell'utente. È il colore dell'architettura della sala e dell'azione principale; in scuro l'azione schiarisce (`#3d7d69`) per restare leggibile sul fondo.
- **Verde museo, varianti** (`rail-hover`, `rail-active`, `action-hover`): stati di passaggio e selezione dentro la colonna e sul pulsante primario. `action-text` è lo stesso verde usato come testo (stato «completato», bordo al passaggio sugli esempi).

### Secondary
- **Ottone** (`brass`): testo degli stati in corso del turno e delle etichette del revisore, cursore della casella. Su fondo chiaro.
- **Ottone chiaro** (`brass-bright`): numeri di scheda, frecce dell'esito, cursore lampeggiante, numerazione nella colonna. Solo su superfici scure (grafite e verde).
- **Ottone del focus** (`focus`): l'anello del focus visibile, uguale in tutta l'interfaccia.

### Tertiary
- **Rosso Olivetti** (`signal`, con il fondo tenue `signal-soft`): errori, avvisi, scheda in errore, giudizio «non coerente», pulsante «Interrompi», riquadro di conferma e scelta «Elimina».

### Neutral
- **Intonaco** (`ground`, `ground-deep`): fondo della pagina e della zona in basso; il più profondo per i passaggi dei pulsanti-icona.
- **Smalto** (`card`): cartellini delle risposte, esempi, casella di testo, avvisi informativi.
- **Grafite** (`strip`, `strip-ink`, `strip-mute`): schede degli strumenti, blocchi di codice, etichette degli strumenti negli esempi.
- **Inchiostro** (`ink`, `mute`): testo principale e testo secondario.
- **Filetti** (`line`, `line-strong`): bordi dei cartellini e divisori; il più forte per la casella e i controlli.
- **Colonna** (`rail-ink`, `rail-mute`, `rail-line`): testo, testo secondario e bordi dentro la colonna verde.

### Named Rules
**The Red Means Stop Rule.** Il rosso compare solo per errori, avvisi e azioni irreversibili. Mai come decorazione, mai come accento di marca.

**The Brass On Dark Rule.** L'ottone chiaro sta solo su grafite o verde; sul fondo chiaro si usa l'ottone scuro, che regge il contrasto.

## Typography

**Body Font:** Segoe UI (con system-ui, -apple-system, Helvetica Neue, Arial)
**Label/Mono Font:** Consolas (con Cascadia Mono, ui-monospace, SFMono-Regular, Menlo)

**Character:** una sola sans di sistema, sobria e leggibile anche proiettata; il monospaziato appartiene solo alla macchina (schede, codice, nomi degli strumenti).

### Hierarchy
- **Display** (700, 30px, 1.2): solo il saluto della vista vuota.
- **Brand** (700, 28px, 1.1): il nome «Pico» in cima alla colonna.
- **Title** (600, 18px, 1.3): titolo della chat nell'intestazione, troncato con i puntini.
- **Body** (400, 15px, 1.55, cifre tabellari): messaggi e risposte; il testo di presentazione sale a 16px con misura massima di 64ch.
- **Label** (700, 11px, 0.14em, maiuscolo): intestazione dell'elenco delle chat, stato del turno (0.12em), etichetta del revisore (10.5px), dicitura «Scheda» (10px, 0.16em).
- **Mono** (400, 13.5px, 1.45): corpo delle schede e blocchi di codice; 12px per le etichette degli strumenti negli esempi.
- **Note** (400, 12.5px): riga delle misure e righe secondarie, con i valori in grassetto 600.

### Named Rules
**The Weight Not Size Rule.** La gerarchia si fa con peso e maiuscolo spaziato; la scala resta stretta (10px-30px).

**The Tabular Rule.** Le cifre sono sempre tabellari: tempi, numeri di scheda e token devono allinearsi.

## Layout

Griglia a due colonne: colonna delle chat di 300px, sala principale fluida. La sala è a tre righe: intestazione, filo dei messaggi che scorre, zona in basso fissa (avvisi, conferma, casella). Il filo e la zona in basso sono centrati a 860px al massimo; risposte e schede a 680px, messaggi dell'utente a 620px (o 85%), allineati a destra. Margine laterale della sala 40px.

Ritmo su multipli di 4: 4, 8, 12, 16, 24px, con 20px tra i messaggi e 10px tra gli elementi di una risposta. La vista vuota parte al 6vh dall'alto, con gli esempi in griglia di due colonne.

Sotto 860px la colonna diventa un cassetto che entra da sinistra (min(300px, 86vw)) sopra un velo scuro, aperto dal pulsante menu; da chiusa esce anche dall'ordine del tasto Tab. Margini a 16px, esempi su una colonna, numero di scheda ristretto a 76px.

## Elevation & Depth

Quasi piatto: la profondità viene dai toni (intonaco, smalto, grafite) e dai filetti. Un'unica ombra morbida e bassa stacca i cartellini che si possono toccare o che portano un reperto.

### Shadow Vocabulary
- **Cartellino** (`box-shadow: 0 1px 2px rgba(27, 47, 40, 0.10), 0 4px 12px rgba(27, 47, 40, 0.06)`): esempi, schede degli strumenti, riquadro di conferma. In scuro diventa `0 1px 2px rgba(0,0,0,0.35), 0 4px 12px rgba(0,0,0,0.25)`.
- **Risposta** (`box-shadow: 0 1px 2px rgba(27, 47, 40, 0.08)`): appena un contatto sotto la risposta.
- **Cassetto** (`box-shadow: 0 0 24px rgba(0, 0, 0, 0.25)`): solo la colonna aperta su schermo stretto.

### Named Rules
**The Tonal First Rule.** Prima il tono e il filetto, poi l'ombra. L'ombra non cresce al passaggio: gli esempi si sollevano di 1px e cambiano bordo.

## Shapes

Angoli appena smussati, in tre misure: 3px per le etichette degli strumenti, 4px per i fogli (risposte, schede, messaggi dell'utente, note del revisore), 6px per i controlli (pulsanti, casella, avvisi, conferma, voci della colonna). Bordi da 1px ovunque; la scheda dello strumento separa il numero dal corpo con un tratteggio verticale, come la perforazione di una scheda. I punti di stato e i segni delle scelte sono cerchi pieni.

## Components

### Buttons
- **Shape:** controllo smussato (6px).
- **Primary:** verde museo pieno, testo chiaro, 600, larghezza minima 116px, alto quanto la casella. Al passaggio il verde schiarisce; disabilitato diventa smalto con filetto forte e testo spento.
- **Secondary («Interrompi»):** smalto con bordo e testo rosso; al passaggio fondo rosso tenue.
- **Colonna («Nuova chat»):** trasparente con filetto della colonna, testo chiaro 600, icona + a sinistra; al passaggio fondo più chiaro.
- **Icona:** quadrati di 30-38px senza bordo (chiudi avviso, elimina chat) o con filetto (menu); icone SVG lineari di 16px, tratto 1.6.
- **Hover / Focus:** transizioni di 160ms ease-out su fondo, bordo e colore; focus con anello d'ottone di 2px a 2px di distanza.

### Chips
- **Etichetta dello strumento:** banda grafite, testo monospaziato 12px, freccia d'ottone davanti; compare sotto ogni esempio per dire quale strumento verrà usato.
- **Stato del turno:** maiuscolo spaziato con un punto pieno di 8px; ottone pulsante durante attesa, strumento e scrittura, verde a «completato», rosso a conferma ed errore.

### Cards / Containers
- **Risposta:** smalto, filetto sottile, 4px, 12px 18px, ombra di contatto. Il codice in linea su intonaco, i blocchi di codice su grafite; l'avviso «⚠» dentro la risposta su rosso tenue con bordo rosso.
- **Esempio:** smalto con ombra del cartellino, testo 600 e etichetta dello strumento; al passaggio bordo verde e sollevamento di 1px.
- **Nota del revisore:** cartellino basso su una riga, etichetta in ottone maiuscolo («Revisore») e giudizio; bordo ed etichetta rossi se «non coerente».
- **Riga delle misure:** testo secondario 12.5px, valori in grassetto («2,1 s in tutto · primo token dopo 0,8 s · ≈ 120 token»).

### Inputs / Fields
- **Casella:** smalto, filetto forte, 6px, alta da 56 a 200px, ridimensionabile in verticale, cursore d'ottone.
- **Focus:** anello d'ottone di 2px aderente e bordo d'ottone.
- **Scelte della conferma:** coppia di segmenti uniti con un cerchio di spunta; quella attiva su intonaco e inchiostro, «Elimina» attiva su rosso tenue e rosso.

### Navigation
- **Colonna delle chat:** verde museo, nome «Pico» 28px, sottotitolo spento, «Nuova chat», elenco con titolo troncato 14px 600 e data 12px. La voce corrente prende il verde più chiaro; il pulsante di eliminazione è attenuato (55%) e si accende al passaggio o al focus.

### Scheda dello strumento (signature)
La scheda-reperto della Programma 101: banda grafite a tutta cornice, 4px, ombra del cartellino. A sinistra una colonna di 96px con la dicitura «Scheda» in maiuscolo spaziato e il numero progressivo della conversazione in ottone a 22px, separata da un tratteggio; a destra, in monospaziato, il nome dello strumento in grassetto, gli argomenti spenti e l'esito su riga propria dopo una freccia d'ottone. In esecuzione l'esito è spento e un cursore d'ottone lampeggia a scatti; in errore bordo rosso ed esito rosa.

## Do's and Don'ts

### Do:
- **Do** mostrare ogni strumento eseguito come scheda grafite numerata, con argomenti ed esito su righe proprie.
- **Do** usare il verde museo per la struttura (colonna) e per l'unica azione primaria della vista.
- **Do** tenere l'ottone chiaro (`brass-bright`) solo su grafite o verde, e l'ottone scuro (`brass`) sul fondo chiaro.
- **Do** usare cifre tabellari e il monospaziato per tutto ciò che viene dalla macchina.
- **Do** mantenere transizioni di 160ms ease-out e azzerare animazioni e transizioni con `prefers-reduced-motion`.
- **Do** dare a ogni controllo l'anello di focus d'ottone di 2px.

### Don't:
- **Don't** usare il rosso per altro che errori, avvisi ed eliminazioni.
- **Don't** nascondere gli strumenti dietro la risposta o ridurli a una riga grigia.
- **Don't** usare bolle grigie e un accento blu: i messaggi dell'utente sono fogli verdi a 4px, le risposte cartellini smaltati.
- **Don't** introdurre una seconda famiglia sans o ombre più profonde del cartellino.

## Aggiornamento 2026-11-25: risposta pulita e menù dei dettagli

Nel messaggio di Pico resta solo la risposta (cartellino smaltato) con il timbro del revisore (`.stamp`: «✓ revisionata» in verde azione). Le schede Programma 101, le righe del revisore, le misure e il ragionamento si spostano nel menù `.trace` (`<details>`), la cui riga chiusa in monospaziato nomina gli strumenti: la prova del meccanismo resta leggibile senza aprire il menù. La risposta in arrivo non si mostra prima del verdetto del revisore: al suo posto il cartellino in attesa (`.answer-pending`) con lo stato.
