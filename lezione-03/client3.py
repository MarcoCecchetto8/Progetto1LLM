"""Client 3: conversazione in memoria con risposta in streaming.

Legge una domanda alla volta con input() e la invia insieme a tutta la
conversazione precedente, cosi' il modello ricorda cosa e' stato detto.
La cronologia resta solo in memoria: alla chiusura si perde.
Le righe vuote vengono ignorate; "esci" o Ctrl+C terminano il programma.
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
SYSTEM = "Sei un assistente che risponde in italiano, in modo chiaro e conciso."

# Cronologia: parte dal system e riceve ogni domanda e ogni risposta.
messages = [{"role": "system", "content": SYSTEM}]


# --- Chiamata -------------------------------------------------------------
def invia(messages):
    """Invia l'intera conversazione, stampa i frammenti e restituisce il testo completo."""
    # --- Payload ----------------------------------------------------------
    # reasoning_effort "none": senza, il modello consuma i token ragionando.
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.5,
        "reasoning_effort": "none",
        "stream": True,
    }

    # stream=True: requests consegna le righe man mano, senza attendere la fine.
    # Il timeout vale per la connessione e per l'attesa fra due frammenti.
    response = requests.post(
        f"{base_url}/chat/completions", json=payload, stream=True, timeout=120
    )
    response.raise_for_status()

    frammenti = []
    print("Modello> ", end="", flush=True)
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


try:
    while True:
        domanda = input("\nTu> ").strip()
        if not domanda:
            continue
        if domanda.lower() == "esci":
            break

        messages.append({"role": "user", "content": domanda})
        # Se la richiesta fallisce, la domanda senza risposta esce dalla lista.
        try:
            risposta = invia(messages)
        except requests.exceptions.Timeout:
            messages.pop()
            print("\nAttesa scaduta: controllare server, carico e tempi.")
        except requests.exceptions.ConnectionError:
            messages.pop()
            print("\nConnessione fallita: controllare server, URL e porta.")
        except requests.exceptions.HTTPError as errore:
            messages.pop()
            print("\nErrore HTTP:", errore.response.status_code, errore.response.text)
        except requests.exceptions.RequestException:
            messages.pop()
            print("\nRichiesta interrotta: la domanda non e' stata registrata.")
        else:
            messages.append({"role": "assistant", "content": risposta})
except (KeyboardInterrupt, EOFError):
    # Ctrl+C (o Ctrl+Z su Windows): uscita pulita, senza traceback.
    print()

print("Fine.")
