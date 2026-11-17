"""Testi dei prompt MCP: funzioni pure che sollevano ValueError."""

LEVELS = {
    "base": "Usa parole semplici, spiega i termini tecnici e fai un esempio concreto.",
    "intermedio": "Dai per note le basi: spiega come funziona, con un esempio.",
    "avanzato": "Entra nei dettagli tecnici: funzionamento interno, scelte di progetto e limiti.",
}

SUMMARY_STYLES = {
    "sintetico": "in poche frasi, solo gli argomenti principali.",
    "dettagliato": "per ogni argomento, che cosa è stato chiesto e che cosa è stato risposto, in un breve elenco.",
}


def explain_text(argomento: str, livello: str = "base") -> str:
    if not argomento.strip():
        raise ValueError("argomento vuoto: indica il concetto da spiegare")
    if livello not in LEVELS:
        raise ValueError(f"livello '{livello}' non ammesso (ammessi: {', '.join(LEVELS)})")
    return f"Spiegami «{argomento.strip()}» a livello {livello}. {LEVELS[livello]}"


def summary_text(stile: str = "sintetico") -> str:
    if stile not in SUMMARY_STYLES:
        raise ValueError(f"stile '{stile}' non ammesso (ammessi: {', '.join(SUMMARY_STYLES)})")
    return ("Riassumi la conversazione fin qui, basandoti solo sui messaggi precedenti "
            "e senza usare strumenti: " + SUMMARY_STYLES[stile])
