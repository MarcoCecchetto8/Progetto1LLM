"""Client 1: domanda fissa al server locale di LM Studio.

A ogni Invio invia la stessa domanda, scritta nel codice, e stampa
la risposta del modello. Scrivere "esci" per terminare il programma.
"""

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
    "max_tokens": 300,
    "reasoning_effort": "none",
    "stream": False,
}

# --- Chiamata -------------------------------------------------------------
print("Domanda:", messages[1]["content"])
while True:
    comando = input('\nInvio per inviare la domanda, "esci" per terminare: ')
    if comando.strip().lower() == "esci":
        break

    try:
        response = requests.post(
            f"{base_url}/chat/completions", json=payload, timeout=60
        )
        response.raise_for_status()
        print("Risposta:", response.json()["choices"][0]["message"]["content"])
    except requests.exceptions.Timeout:
        print("Attesa scaduta: controllare server, carico e tempi.")
    except requests.exceptions.ConnectionError:
        print("Connessione fallita: controllare server, URL e porta.")
    except requests.exceptions.HTTPError:
        print("Errore HTTP:", response.status_code, response.text)

print("Fine.")
