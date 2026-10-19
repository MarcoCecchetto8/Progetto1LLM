"""Client 1: domande da terminale al server locale di LM Studio.

Legge una domanda alla volta con input() e stampa la risposta del modello.
Ogni domanda e' indipendente: nessuna cronologia. Le righe vuote vengono
ignorate; "esci" o Ctrl+C terminano il programma.
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
system = {
    "role": "system",
    "content": "Sei un assistente che risponde in italiano, in modo chiaro e conciso.",
}

# --- Chiamata -------------------------------------------------------------
try:
    while True:
        domanda = input('\nDomanda ("esci" per terminare): ').strip()
        if not domanda:
            continue
        if domanda.lower() == "esci":
            break

        # --- Payload ------------------------------------------------------
        # reasoning_effort "none": senza, il modello consuma i token ragionando.
        payload = {
            "model": model,
            "messages": [system, {"role": "user", "content": domanda}],
            "temperature": 0.5,
            "reasoning_effort": "none",
            "stream": False,
        }

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
except (KeyboardInterrupt, EOFError):
    # Ctrl+C (o Ctrl+Z su Windows): uscita pulita, senza traceback.
    print()

print("Fine.")
