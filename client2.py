"""Client 2: domanda fissa con risposta in streaming.

A ogni Invio invia la stessa domanda, scritta nel codice, e stampa
la risposta del modello frammento per frammento, appena arriva.
Scrivere "esci" per terminare il programma.
"""

import json
import os

import requests
from dotenv import load_dotenv

# --- Configurazione -------------------------------------------------------
# URL del server e nome del modello arrivano da .env, non dal codice.
load_dotenv()
base_url = os.environ["LM_BASE_URL"]
model = os.environ["LM_MODEL"]

# --- Messaggi -------------------------------------------------------------
messages = [
    {
        "role": "system",
        "content": "Sei un assistente che risponde in italiano, in modo chiaro e conciso.",
    },
    {"role": "user", "content": "Che cos'è un modello linguistico?"},
]

# --- Payload --------------------------------------------------------------
# reasoning_effort "none": senza, il modello consuma i token ragionando.
payload = {
    "model": model,
    "messages": messages,
    "temperature": 0.5,
    "reasoning_effort": "none",
    "stream": True,
}


# --- Chiamata -------------------------------------------------------------
def invia_domanda(payload):
    """Invia il payload, stampa i frammenti appena arrivano e restituisce il testo completo."""
    # stream=True: requests consegna le righe man mano, senza attendere la fine.
    # Il timeout vale per la connessione e per l'attesa fra due frammenti.
    response = requests.post(
        f"{base_url}/chat/completions", json=payload, stream=True, timeout=120
    )
    response.raise_for_status()

    frammenti = []
    print("Risposta: ", end="", flush=True)
    for riga in response.iter_lines():
        # Decodifica esplicita: il server invia UTF-8 (accenti compresi).
        riga = riga.decode("utf-8")
        if not riga.startswith("data: "):
            continue
        dati = riga[len("data: "):]
        if dati == "[DONE]":
            break
        evento = json.loads(dati)
        # Alcuni eventi non portano testo (ruolo iniziale, motivo di chiusura).
        frammento = evento["choices"][0]["delta"].get("content")
        if frammento:
            print(frammento, end="", flush=True)
            frammenti.append(frammento)
    print()
    return "".join(frammenti)


print("Domanda:", messages[1]["content"])
while True:
    comando = input('\nInvio per inviare la domanda, "esci" per terminare: ')
    if comando.strip().lower() == "esci":
        break

    try:
        testo_completo = invia_domanda(payload)
        print(f"[{len(testo_completo)} caratteri ricevuti]")
    except requests.exceptions.Timeout:
        print("Attesa scaduta: controllare server, carico e tempi.")
    except requests.exceptions.ConnectionError:
        print("Connessione fallita: controllare server, URL e porta.")
    except requests.exceptions.HTTPError as errore:
        print("Errore HTTP:", errore.response.status_code, errore.response.text)

print("Fine.")
