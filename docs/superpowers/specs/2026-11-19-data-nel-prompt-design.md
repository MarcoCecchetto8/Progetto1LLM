# Data di oggi nel messaggio di sistema — specifica breve

Data: 2026-11-19 · Stato: approvata dall'utente il 2026-11-19 · **Revisione 2026-11-19** (date relative calcolate dal programma, dopo la misura): approvata dall'utente

## Perché

Con `liquid/lfm2-24b-a2b` (modello in uso dal 2026-11-18) le date relative sono sempre sbagliate: nel confronto con gemma «Ricordami di consegnare il report venerdì» ha dato scadenze 2026-07-03, 2024-06-14, 2026-07-03 (0/3 corrette); nella misura delle frasi «domani» → 2025-11-19, «lunedì» → 2024-07-08. Il modello non chiama `get_current_time` prima di calcolare (crede di essere a luglio), anche se il messaggio di sistema glielo chiede. I promemoria finiscono con una scadenza sbagliata, spesso già passata.

## Che cosa cambia

- **Agente:** a **ogni chiamata al modello dell'agente** il messaggio di sistema riceve una riga con la data di oggi, nel fuso delle preferenze, con il giorno della settimana in italiano, per esempio `Oggi è giovedì 19 novembre 2026 (2026-11-19), fuso orario Europe/Rome.` La data si calcola al momento della chiamata, non all'avvio: l'agente è un servizio che può restare acceso per giorni (anche in Docker). Come il riassunto (`with_summary`), la riga non entra nella cronologia.
- **Revisore:** riceve la stessa riga nella richiesta di giudizio, così può accorgersi di una scadenza sbagliata (e non scambiare per «data futura» un risultato giusto).
- **Router:** invariato (per decidere l'ambito la data non serve).
- **Solo la data, non l'ora:** per l'ora resta lo strumento `get_current_time`; le istruzioni sugli strumenti delle date restano invariate.

## Approcci considerati

- **Data a ogni chiamata (scelto):** sempre giusta, stesso schema del riassunto.
- **Data scritta all'avvio in `system_prompt`:** più semplice ma sbagliata dopo mezzanotte con l'agente acceso a lungo. Scartata.
- **`add_note` che accetta «venerdì», «domani» e calcola il programma:** più robusto, ma è la strada dello strumento «prossimo giorno della settimana» già scartata dall'utente. Non in questa modifica.

## Verifica

- **Test senza modello:** con un orologio finto la riga contiene giorno della settimana, data in parole e AAAA-MM-GG e fuso; cambia se la data cambia fra due chiamate dello stesso grafo; arriva al modello dell'agente e al revisore; non resta in cronologia; testi esistenti del messaggio di sistema invariati.
- **Misura prima e dopo con lfm2** (sonda end-to-end, archivio delle note temporaneo, 3 ripetizioni): «Ricordami di consegnare il report venerdì», «Ricordami di chiamare Luca domani», «Crea una nota per lunedì: riunione» (con «:» è anche una richiesta esplicita), «Quanti giorni mancano a Natale?». Si contano scadenze corrette, chiamate agli strumenti e risposte; i numeri vanno nel README. La modifica non rende il modello affidabile sui calcoli: si registra quello che si vede.
- **Prova reale** via pipe con `python -m assistant` e una con Docker.

## Lasciato al piano

Nome e posto della funzione che compone la riga (accanto a `with_summary` o nel grafo), come passare l'orologio a `build_graph` e a `build_reviewer` (oggi `startup.py` ha già `today` nel fuso delle preferenze), nomi dei giorni e dei mesi in italiano senza dipendere dalla lingua del sistema operativo.

## Revisione 2026-11-19: date relative calcolate dal programma

**Perché.** Misura «dopo» con la riga della data (lfm2, 3 ripetizioni): «domani» 3/3, «lunedì» 3/3, Natale 3/3, ma «venerdì» 0/3: il modello salva sempre 2026-11-22 (domenica) scrivendo «venerdì 22 novembre»; il revisore non se ne accorge. Il modello conosce la data ma sbaglia il conto. L'utente sceglie la soluzione che il modello non può sbagliare: il calcolo lo fa il programma.

**Che cosa cambia.**
- Il parametro `due_date` di `add_note` accetta, oltre a `AAAA-MM-GG`: `oggi`, `domani`, `dopodomani`, i giorni della settimana `lunedì` … `domenica`, anche seguiti da `prossimo`/`prossima` e senza accento (`lunedi`); maiuscole e spazi ai lati ignorati.
- Un giorno della settimana è sempre il **prossimo** con quel nome, mai oggi: detto di giovedì, «giovedì» = fra 7 giorni (scelta dell'utente).
- Il calcolo sta nel wrapper di `add_note` (`assistant/notes.py`), con l'orologio «oggi» nel fuso delle preferenze già usato dalle note; al servizio delle note arriva sempre `AAAA-MM-GG` (servizio invariato).
- Forma non riconosciuta → errore dello strumento con l'elenco delle forme ammesse (il modello può correggersi).
- La descrizione di `add_note` dice di passare le date relative così come sono (es. `due_date="venerdì"`) senza calcolarle; nel messaggio di sistema la frase «ricavala tu con `get_current_time` e `add_days`» diventa la stessa indicazione. La riga della data di oggi resta.
- La risposta dello strumento riporta già la data calcolata («scadenza 2026-11-20 (fra 1 giorno)»).

**Aggiunta (2026-11-19, dopo la misura):** con il calcolo nel programma «venerdì» 3/3 e «lunedì» 3/3, ma «domani» 0/3: il modello (che ragiona in inglese) passa `due_date="tomorrow"`, lo strumento lo rifiuta e il modello non riprova. Si accettano anche le forme inglesi equivalenti: `today`, `tomorrow`, `day after tomorrow`, `monday` … `sunday`, anche con `next` davanti (`next friday`), con le stesse regole (prossimo giorno, mai oggi). Approvato dall'utente.

**Fuori.** «fra 3 giorni», «il 5 dicembre», «la settimana prossima»: il modello le converte in `AAAA-MM-GG` o usa `add_days`.

**Verifica.** Test senza modello con orologio finto: ogni giorno della settimana da ogni giorno, oggi/domani/dopodomani, forme senza accento e con «prossimo», maiuscole e spazi, forme non valide, passaggio di fine mese e di fine anno; misura con lfm2 sulle 4 domande (3 ripetizioni) e prova reale.
