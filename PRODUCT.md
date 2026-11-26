# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

HTML, CSS e JavaScript senza framework né build, serviti da `frontend_service/` (FastAPI, porta 8003); nessun font o script esterno. Scelta dell'utente nella specifica dello step 8 (`docs/superpowers/specs/2026-11-25-frontend-chat-design.md`).

## Users

L'autore del progetto (studente del corso «Deep Learning e LLM: costruire chatbot e agenti»), che la usa e la **presenta dal vivo a un docente e a un dipendente di un'azienda**. Chi guarda non conosce il progetto: deve capire in pochi secondi che cosa fa l'assistente e vederlo usare strumenti veri.

## Product Purpose

Interfaccia di chat web per **Pico**, l'assistente del laboratorio: un agente LangGraph con un modello locale (LM Studio) che usa strumenti reali (orologio con fuso orario, convertitore di unità, calcolatrice, festività, giorni e scadenze, catalogo dei linguaggi di programmazione, note). Successo: una conversazione completa dal browser con uso di uno strumento, chat che restano dopo il riavvio, errori chiari quando un servizio è spento.

## Positioning

Tutto gira in locale: il modello sta sul computer, gli strumenti li esegue davvero il programma (non il modello che inventa), le chat si salvano in PostgreSQL. L'interfaccia deve rendere visibile questo meccanismo (quale strumento è stato chiamato, con che risultato, il giudizio del revisore) senza diventare un pannello tecnico.

## Operating Context

Demo su un portatile Windows, spesso proiettata o condivisa a schermo; modello locale lento (risposte da alcuni secondi a oltre un minuto), quindi l'attesa è parte normale dell'esperienza. Servizi separati (back-end 8002, agente 8001, database) che possono essere spenti: l'interfaccia comunica solo con il back-end.

## Capabilities and Constraints

- Elenco, creazione (al primo invio) ed eliminazione delle chat; vista dei messaggi; invio con risposta in streaming; interruzione.
- Conferma esplicita dell'eliminazione delle note (riquadro con «Elimina» / «Non eliminare»).
- Righe degli strumenti usati e righe informative (revisore) accanto alle risposte; il ragionamento non si mostra.
- Testi in italiano; il modello usa markdown leggero (grassetto, codice).
- Il modello piccolo a volte sbaglia o dichiara azioni non fatte: l'avviso «⚠ Attenzione: nessuna nota è stata salvata/eliminata…» arriva nel testo e va mostrato.
- Niente autenticazione, una sola persona.

## Brand Commitments

- Nome dell'assistente: **Pico** (da Pico della Mirandola, famoso per la memoria), scelto dall'utente: serio ma simpatico.
- Nessun logo, colore o tono imposto (delegato).

## Evidence on Hand

Nessuna immagine o asset. Contenuti reali: le domande d'esempio di `config/ambito.txt` e gli strumenti di `lab_server/`. Non inventare funzioni non presenti (niente meteo, niente ricerca web).

## Product Principles

1. Far vedere il meccanismo: lo strumento chiamato e il suo esito sono parte della risposta, non un dettaglio nascosto.
2. L'attesa è onesta: si vede che Pico sta lavorando e si può interrompere.
3. Mai bloccarsi: ogni errore dice che cosa non risponde e la domanda scritta non si perde.
4. Chiaro a chi lo vede per la prima volta, durante una presentazione.

## Accessibility & Inclusion

Contrasto adeguato anche su proiettore, focus visibile, uso completo da tastiera, area dei messaggi annunciata ai lettori di schermo; tema chiaro e scuro secondo il sistema.
