---
version: 1
slug: "frontend-service-static-index-html"
primary_target: "frontend_service/static/index.html"
related_targets: ["frontend_service/static/app.js","frontend_service/static/style.css"]
---

# Superficie: chat di Pico (frontend_service/static/index.html)

Modo: Operate. Pubblico: l'autore che presenta dal vivo a un docente e a un dipendente di un'azienda. Compito: conversare con Pico, vedere gli strumenti veri all'opera, gestire chat e conferme. Vincoli: HTML/CSS/JS senza framework, nessuna risorsa esterna, testi in italiano, solo il back-end come interlocutore. Requisiti completi: spec `docs/superpowers/specs/2026-11-25-frontend-chat-design.md`, sezione 5.

## Direction contract

THESIS: la chat dove ogni strumento davvero eseguito è un reperto catalogato accanto alla risposta; rifiuta la chat grigia con bolle e accento blu, dove gli strumenti spariscono.

OWN-WORLD: sala di museo della scienza: intonaco grigio-verde (#dfe4df) come fondo, colonna verde museo (#1f3b33) con testo chiaro, cartellini smaltati bianchi (#fbfbf8) a bordo sottile, numeri in ottone (#b08a3e), inchiostro #1b1f1d. Strumenti come schede magnetiche della Programma 101: banda grafite (#2b2b2a) a tutta cornice con testo monospaziato chiaro, etichetta-numero in ottone, esito su riga propria; rosso Olivetti (#c8102e) riservato a errori e avvisi. Una sola famiglia sans di sistema, scala stretta, gerarchia con peso e maiuscoletto spaziato, cifre tabellari.

STORY: chi guarda capisce che Pico è un assistente locale che usa strumenti veri; vede la domanda, la scheda dello strumento con dati ed esito, la risposta che si scrive, il giudizio del revisore e i tempi; prova a scrivere una domanda o sceglie un esempio.

FIRST VIEWPORT: a sinistra colonna verde di 300px con «Pico», sottotitolo, «Nuova chat» ed elenco delle chat (sala); a destra intestazione col titolo della chat e lo stato del turno; filo dei messaggi centrato (max 860px); casella e «Invia» in basso, azione primaria. Vista vuota: presentazione breve di Pico e quattro domande d'esempio cliccabili.

FORM: candidato 6 della lista ordinata (cartellini del Museo della Scienza), con la scheda degli strumenti presa dalla Programma 101 per scelta dell'utente. seed:6cf794ad6a8458e6. Mossa distintiva: la scheda-reperto numerata dello strumento, che si accende «in corso» e si chiude con l'esito; vocabolario degli stati del turno (in attesa, strumento in corso, in revisione, completato, interrotto); riga delle misure (tempo totale, primo token, ≈ token).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
