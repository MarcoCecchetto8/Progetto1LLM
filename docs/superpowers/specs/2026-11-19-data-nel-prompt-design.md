# Data di oggi nel messaggio di sistema — specifica breve

Data: 2026-11-19 · Stato: approvata dall'utente il 2026-11-19

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
